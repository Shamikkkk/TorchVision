"""
TorchEngine — chess engine with four modes in priority order:

  1. mcts      — MCTS guided by ChessNet policy + value heads
                 (activated when torch_chess.pt contains a policy head)
  2. neural    — minimax depth-4 with ChessNet value head as eval function
                 (activated when torch_chess.pt exists but has no policy head)
  3. classical — minimax depth-4 with hand-crafted PST evaluation
                 (always available; no external binary required)
  4. stockfish — external Stockfish binary
                 (last resort only; kept for comparison purposes)
"""

import logging
import random
import sys
from pathlib import Path

import chess
from stockfish import Stockfish, StockfishException

from .evaluate import evaluate
from . import search as _search

logger = logging.getLogger(__name__)

# Absolute path to the saved weights file.
_WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "torch_chess.pt"

# backend/ directory — added to sys.path so model_training is importable at runtime.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)

_CP_SCALE        = 2000.0   # centipawns → [-1, 1] for MCTS value normalisation
_MCTS_SIMS       = 200      # simulations per move in MCTS mode


class TorchEngine:
    """
    Unified chess engine.  The ``best_move(fen)`` interface is stable across
    all modes so the rest of the application never needs to change.

    ``last_eval`` is set after every ``best_move`` call for classical/neural
    modes; it is ``None`` for MCTS (tree search score) and Stockfish.
    """

    last_eval: float | None = None

    def __init__(self, stockfish_path: str) -> None:
        self._stockfish_path = stockfish_path
        self._sf_params      = {"Skill Level": 10}
        self._sf_available   = False

        # --- Priority 1 & 2: neural weights (mcts or neural mode) ---
        if _WEIGHTS_PATH.exists():
            try:
                has_policy = self._load_nn()
                if has_policy:
                    from .mcts import BatchedMCTS
                    self._mcts = BatchedMCTS(self, num_simulations=_MCTS_SIMS)
                    self.mode  = "mcts"
                    logger.info(
                        "MCTS engine ready (%d sims, weights: %s)",
                        _MCTS_SIMS, _WEIGHTS_PATH,
                    )
                else:
                    self.mode = "neural"
                    logger.info(
                        "Neural engine ready (minimax depth 4, weights: %s)", _WEIGHTS_PATH
                    )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Neural weights found but failed to load (%s) — falling back", exc
                )

        # --- Priority 3: classical (always works) ---
        self.mode = "classical"
        logger.info("Classical engine ready (minimax depth 4, hand-crafted PST eval)")

        # Probe Stockfish so we know if it's available as a last resort.
        try:
            sf = Stockfish(path=stockfish_path, parameters=self._sf_params)
            sf.get_board_visual()
            self._sf_available = True
            logger.info(
                "Stockfish available at '%s' (held as last-resort fallback)", stockfish_path
            )
        except (StockfishException, FileNotFoundError, OSError) as exc:
            logger.info("Stockfish not available (%s)", exc)

    # ------------------------------------------------------------------
    # Neural network helpers
    # ------------------------------------------------------------------

    def _load_nn(self) -> bool:
        """Load ChessNet weights from disk.

        Returns True if the weights include a policy head (→ mcts mode),
        False if they are value-only (→ neural/minimax mode).
        """
        import torch  # noqa: PLC0415

        if _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)

        from model_training.architecture import ChessNet  # type: ignore[import]

        state_dict = torch.load(str(_WEIGHTS_PATH), map_location="cpu")
        has_policy = any(k.startswith("policy_head.") for k in state_dict)

        net = ChessNet()
        # strict=False when there is no policy head so legacy value-only
        # weights load without raising a key-mismatch error.
        net.load_state_dict(state_dict, strict=has_policy)
        net.eval()
        self._nn_model = net
        return has_policy

    def _nn_eval(self, board: chess.Board) -> float:
        """Run ChessNet value head on one position. Returns centipawns (White-positive).

        Used by the "neural" minimax mode as a drop-in replacement for the
        hand-crafted PST evaluator.
        """
        import torch  # noqa: PLC0415
        from model_training.dataset import fen_to_tensor, fen_to_scalars  # type: ignore[import]

        fen          = board.fen()
        board_tensor = fen_to_tensor(fen).unsqueeze(0)                        # (1, 21, 8, 8)
        scalar_tensor = torch.tensor(                                          # (1, 7)
            fen_to_scalars(fen), dtype=torch.float32
        ).unsqueeze(0)
        with torch.no_grad():
            value_t, _ = self._nn_model(board_tensor, scalar_tensor)
        return float(value_t.item())

    def _nn_evaluate(self, board: chess.Board) -> tuple[float, dict[chess.Move, float]]:
        """Run both heads of ChessNet on one position.

        Returns:
            value   — position score in [-1, 1] from the current player's perspective
            policy  — {move: prior_probability} for all legal moves (sums to 1)

        Used exclusively by the MCTS engine.
        """
        import torch  # noqa: PLC0415
        from model_training.dataset import fen_to_tensor, fen_to_scalars      # type: ignore[import]
        from model_training.architecture import decode_policy                  # type: ignore[import]

        fen          = board.fen()
        board_tensor = fen_to_tensor(fen).unsqueeze(0)                        # (1, 21, 8, 8)
        scalar_tensor = torch.tensor(                                          # (1, 7)
            fen_to_scalars(fen), dtype=torch.float32
        ).unsqueeze(0)
        with torch.no_grad():
            value_t, policy_t = self._nn_model(board_tensor, scalar_tensor)

        # Normalise centipawns to [-1, 1], then flip sign for Black's turn so
        # the value is always from the current player's perspective.
        cp    = float(value_t.item())
        value = max(-1.0, min(1.0, cp / _CP_SCALE))
        if board.turn == chess.BLACK:
            value = -value

        policy = decode_policy(policy_t[0], board)
        return value, policy

    def _nn_evaluate_batch(
        self,
        boards: list[chess.Board],
    ) -> tuple[list[float], list[dict[chess.Move, float]]]:
        """Evaluate *boards* in one batched forward pass.

        Stacks board and scalar tensors along the batch dimension, runs a
        single ``model(board_batch, scalar_batch)`` call, then slices the
        result back into per-board values and policy dicts.

        Returns:
            values   — float in [-1, 1], current-player perspective, one per board
            policies — {move: prior_probability} dict, one per board
        """
        import torch  # noqa: PLC0415
        from model_training.dataset import fen_to_tensor, fen_to_scalars      # type: ignore[import]
        from model_training.architecture import decode_policy                  # type: ignore[import]

        board_tensors = torch.stack(                                           # (N, 21, 8, 8)
            [fen_to_tensor(b.fen()) for b in boards]
        )
        scalar_tensors = torch.stack([                                         # (N, 7)
            torch.tensor(fen_to_scalars(b.fen()), dtype=torch.float32)
            for b in boards
        ])

        with torch.no_grad():
            values_t, policies_t = self._nn_model(board_tensors, scalar_tensors)

        values: list[float] = []
        for i, board in enumerate(boards):
            cp = float(values_t[i].item())
            v  = max(-1.0, min(1.0, cp / _CP_SCALE))
            if board.turn == chess.BLACK:
                v = -v
            values.append(v)

        policies = [decode_policy(policies_t[i], board) for i, board in enumerate(boards)]
        return values, policies

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def best_move(self, fen: str) -> str:
        """Return the best move in UCI notation for the given FEN."""
        board = chess.Board(fen)
        legal = list(board.legal_moves)
        if not legal:
            return ""

        # MCTS: policy + value guided tree search.
        if self.mode == "mcts":
            uci = self._mcts.search(fen)
            self.last_eval = None  # tree value score is not a centipawn estimate
            return uci

        # Classical or neural: minimax with PST or NN eval function.
        if self.mode in ("classical", "neural"):
            eval_fn = self._nn_eval if self.mode == "neural" else evaluate
            uci, score = _search.best_move(fen, depth=4, eval_fn=eval_fn)
            self.last_eval = score
            return uci

        # Stockfish last resort.
        if self._sf_available:
            try:
                sf = Stockfish(path=self._stockfish_path, parameters=self._sf_params)
                sf.set_fen_position(fen)
                move = sf.get_best_move_time(100)
                if move:
                    self.last_eval = None
                    return move
            except (StockfishException, Exception) as exc:  # noqa: BLE001
                logger.warning("Stockfish error during best_move (%s) — using random", exc)

        self.last_eval = None
        return random.choice(legal).uci()
