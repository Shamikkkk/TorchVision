"""Append-only PGN store for completed local games.

One file per month: backend/data/local_games/YYYY-MM.pgn. Written on game
over for debugging and a future "review your games" feature. Persistence is
strictly fail-open — save_game never raises, so a disk problem can never
break the game-over flow.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import chess
import chess.pgn

logger = logging.getLogger(__name__)

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "local_games"

_RESULT_STR = {"w": "1-0", "b": "0-1"}


def save_game(
    board: chess.Board,
    *,
    human_color: str,
    status: str,
    winner: str | None = None,
    directory: Path | None = None,
) -> Path | None:
    """Append the finished game as PGN. Returns the file path, or None on
    failure (logged, never raised)."""
    try:
        target_dir = Path(directory) if directory is not None else STORE_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.datetime.now()
        game = chess.pgn.Game.from_board(board)
        game.headers["Event"] = "Torch local game"
        game.headers["Site"] = "Torch (local)"
        game.headers["Date"] = now.strftime("%Y.%m.%d")
        game.headers["Round"] = "-"
        game.headers["White"] = "You" if human_color == "w" else "Pyro"
        game.headers["Black"] = "Pyro" if human_color == "w" else "You"
        game.headers["Result"] = _RESULT_STR.get(winner, "1/2-1/2")
        game.headers["Termination"] = status

        path = target_dir / f"{now.strftime('%Y-%m')}.pgn"
        with open(path, "a", encoding="utf-8") as f:
            f.write(str(game) + "\n\n")
        logger.info("Saved finished game (%s, %s) to %s", status, game.headers["Result"], path)
        return path
    except Exception:
        logger.exception("Failed to persist finished game — game flow unaffected")
        return None
