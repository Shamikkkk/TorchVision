"""
Thin wrapper around the runtime engine for use inside the data pipeline.

Run from backend/:
    python -c "from model_training.engine_classical import best_move_with_eval; print(best_move_with_eval('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1', depth=2))"
"""

import sys
from pathlib import Path

# Ensure backend/ is on the path so `app` is importable.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.engine.search import best_move as _search  # noqa: E402
from app.engine.evaluate import evaluate             # noqa: E402


def best_move_with_eval(fen: str, depth: int = 2) -> tuple[str, float]:
    """
    Return ``(uci_move, centipawn_score)`` using classical minimax.

    depth=2 is used during parsing for speed (≈ 1000 positions/sec).
    depth=4 gives stronger labels but is ~25× slower.
    """
    return _search(fen, depth=depth, eval_fn=evaluate)
