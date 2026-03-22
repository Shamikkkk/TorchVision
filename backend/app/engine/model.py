"""
TorchEngine — chess engine with three modes in priority order:

  1. neural    — minimax search with PyTorch CNN evaluation
                 (activated when backend/models/torch_chess.pt exists)
  2. classical — minimax search with hand-crafted PST evaluation
                 (always available; no external binary required)
  3. stockfish — external Stockfish binary
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


class TorchEngine:
    """
    Unified chess engine.  The ``best_move(fen)`` interface is stable across
    all three modes so the rest of the application never needs to change.

    ``last_eval`` is set after every ``best_move`` call for the classical and
    neural modes; it is ``None`` for Stockfish (we don't have its raw score).
    """

    last_eval: float | None = None

    def __init__(self, stockfish_path: str) -> None:
        self._stockfish_path = stockfish_path
        self._sf_params = {"Skill Level": 10}
        self._sf_available = False

        # --- Priority 1: neural network ---
        if _WEIGHTS_PATH.exists():
            try:
                self._load_nn()
                self.mode = "neural"
                logger.info("Neural engine ready (weights: %s)", _WEIGHTS_PATH)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Neural weights found but failed to load (%s) — falling back", exc)

        # --- Priority 2: classical (always works) ---
        self.mode = "classical"
        logger.info("Classical engine ready (minimax depth 4, hand-crafted PST eval)")

        # Probe Stockfish so we know if it's available as a last resort.
        try:
            sf = Stockfish(path=stockfish_path, parameters=self._sf_params)
            sf.get_board_visual()
            self._sf_available = True
            logger.info("Stockfish available at '%s' (held as last-resort fallback)", stockfish_path)
        except (StockfishException, FileNotFoundError, OSError) as exc:
            logger.info("Stockfish not available (%s)", exc)

    # ------------------------------------------------------------------
    # Neural network helpers
    # ------------------------------------------------------------------

    def _load_nn(self) -> None:
        """Load ChessNet weights from disk.  Lazy-imports torch."""
        import torch  # noqa: PLC0415

        if _BACKEND_DIR not in sys.path:
            sys.path.insert(0, _BACKEND_DIR)

        from model_training.architecture import ChessNet  # type: ignore[import]

        net = ChessNet()
        net.load_state_dict(torch.load(str(_WEIGHTS_PATH), map_location="cpu"))
        net.eval()
        self._nn_model = net

    def _nn_eval(self, board: chess.Board) -> float:
        """Run the neural network on one position. Returns centipawns (White-positive)."""
        import torch  # noqa: PLC0415
        from model_training.dataset import fen_to_tensor, fen_to_scalars  # type: ignore[import]

        fen = board.fen()
        board_tensor = fen_to_tensor(fen).unsqueeze(0)           # (1, 12, 8, 8)
        scalar_tensor = torch.tensor(                             # (1, 7)
            fen_to_scalars(fen), dtype=torch.float32
        ).unsqueeze(0)
        with torch.no_grad():
            return float(self._nn_model(board_tensor, scalar_tensor).item())

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def best_move(self, fen: str) -> str:
        """Return the best move in UCI notation for the given FEN."""
        board = chess.Board(fen)
        legal = list(board.legal_moves)
        if not legal:
            return ""

        # Classical or neural: use our own minimax search.
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
