"""
PyroEngine — chess engine with four modes in priority order:

  1. tablebase — syzygy tablebase lookup (not yet implemented)
  2. neural    — minimax depth-4 with ChessNet value head (when torch_chess.pt exists)
  3. classical — minimax depth-4 with Tal-style PST evaluation (always available)
  4. stockfish — external Stockfish binary (last resort only)

Eval function for minimax (modes 2 & 3): tal_style_eval (fast, pure Python)
NNUE (768→256→32→32→1) is used only for single-position UI assist via
/api/suggest — too slow for the search tree until Phase 5 batch eval.

NOTE: MCTS is disabled until the policy head is properly trained via self-play.
"""

import logging
import random
import sys
from pathlib import Path

import chess
from stockfish import Stockfish, StockfishException

from .evaluate import tal_style_eval
from .nnue import nnue as _nnue
from .opening_book import book as _opening_book
from .tablebase import tablebase as _tablebase
from . import search as _search

logger = logging.getLogger(__name__)

# Absolute path to the saved weights file.
_WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "torch_chess.pt"

# backend/ directory — added to sys.path so model_training is importable at runtime.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent)

_CP_SCALE        = 2000.0   # centipawns → [-1, 1] for MCTS value normalisation
_MINIMAX_DEPTH   = 4


class PyroEngine:
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

        # --- Priority 2: neural weights (minimax with NNUE eval) ---
        # MCTS is disabled regardless of whether a policy head exists —
        # it produces poor moves until the policy is trained via self-play.
        if _WEIGHTS_PATH.exists():
            try:
                self._load_nn()
                self.mode = "neural"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Neural weights found but failed to load (%s) — falling back", exc
                )

        # --- Priority 3: classical (always works) ---
        if not hasattr(self, "mode"):
            self.mode = "classical"

        if self.mode == "neural":
            logger.info("Pyro ready — ChessNet 🧠 (minimax depth %d, book loaded)", _MINIMAX_DEPTH)
        else:
            logger.info("Pyro ready — Tal style 🔥 (minimax depth %d, book loaded)", _MINIMAX_DEPTH)

        if _tablebase.available:
            logger.info("Tablebase: loaded ✅")
        else:
            logger.info("Tablebase: not loaded (place Syzygy .rtbw files in data/syzygy/)")

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

    def _load_nn(self) -> None:
        """Load ChessNet weights from disk into ``self._nn_model``."""
        import torch  # noqa: PLC0415

        if _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)

        from model_training.architecture import ChessNet  # type: ignore[import]

        state_dict = torch.load(str(_WEIGHTS_PATH), map_location="cpu")
        has_policy = any(k.startswith("policy_head.") for k in state_dict)

        net = ChessNet()
        # strict=False so value-only weights load without a key-mismatch error.
        net.load_state_dict(state_dict, strict=has_policy)
        net.eval()
        self._nn_model = net

    def _nn_eval(self, board: chess.Board) -> float:
        """Run ChessNet value head on one position. Returns centipawns (White-positive).

        The model was trained with targets normalised by /600, so the raw output
        is in ~[-1, 1].  Multiply by 600 to recover centipawns before returning.

        Used by the "neural" minimax mode as a drop-in replacement for the
        hand-crafted PST evaluator.
        """
        import torch  # noqa: PLC0415
        from model_training.dataset import fen_to_tensor, fen_to_scalars  # type: ignore[import]

        fen           = board.fen()
        board_tensor  = fen_to_tensor(fen).unsqueeze(0)                       # (1, 21, 8, 8)
        scalar_tensor = torch.tensor(                                          # (1, 7)
            fen_to_scalars(fen), dtype=torch.float32
        ).unsqueeze(0)
        with torch.no_grad():
            value_t, _ = self._nn_model(board_tensor, scalar_tensor)
        return float(value_t.item()) * 600.0   # normalised → centipawns, White-positive

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

        # Priority 0: Tablebase (perfect endgame play)
        if len(board.piece_map()) <= 6:
            tb_move = _tablebase.best_move(board)
            if tb_move:
                self.last_eval = 0.0
                logger.debug("Tablebase move: %s", tb_move.uci())
                return tb_move.uci()

        # Priority 1: opening book
        book_move = _opening_book.get_move(board)
        if book_move:
            self.last_eval = 0.0
            logger.debug("Book move: %s", book_move)
            return book_move

        if self.mode == "neural":
            eval_fn = self._nn_eval
        else:
            eval_fn = tal_style_eval

        if self.mode in ("classical", "neural"):
            uci, score = _search.best_move(fen, depth=_MINIMAX_DEPTH, eval_fn=eval_fn)
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
