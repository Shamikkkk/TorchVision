"""
Opening book built from grandmaster PGN collections.

Parses the first 15 moves of each game from all 31 GM PGN files.
Tactical/aggressive players are double-weighted so their sharp opening
lines survive the frequency filter and bias Pyro toward violent play.
The book is loaded once at module import so lookup is a pure dict hit.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import chess
import chess.pgn

logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# backend/data/ relative to this file (app/engine/ → app/ → backend/)
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_PGN_FILES = [
    "Alekhine.pgn", "Anderssen.pgn", "Aronian.pgn", "Bronstein.pgn",
    "Capablanca.pgn", "Carlsen.pgn", "Firouzja.pgn", "Fischer.pgn",
    "Geller.pgn", "Grischuk.pgn", "Gukesh.pgn", "Jobava.pgn",
    "Karpov.pgn", "Kasparov.pgn", "Korchnoi.pgn", "Larsen.pgn",
    "Ljubojevic.pgn", "Morozevich.pgn", "Morphy.pgn", "Najdorf.pgn",
    "Nakamura.pgn", "Petrosian.pgn", "Praggnanandhaa.pgn",
    "Rapport.pgn", "Shirov.pgn", "Smyslov.pgn", "Spassky.pgn",
    "Spielmann.pgn", "Tal.pgn", "Topalov.pgn", "VachierLagrave.pgn",
]

# Tactical/aggressive players get double-weighted — their openings appear
# twice in the frequency map, biasing Pyro toward sharp lines.
_TACTICAL_PLAYERS = [
    "Tal.pgn", "Shirov.pgn", "Morphy.pgn", "Bronstein.pgn",
    "Spielmann.pgn", "Morozevich.pgn", "Rapport.pgn", "Aronian.pgn",
    "Firouzja.pgn", "Kasparov.pgn", "Anderssen.pgn", "Jobava.pgn",
    "Topalov.pgn",
]

_PGN_FILES_WEIGHTED = _PGN_FILES + _TACTICAL_PLAYERS

_OPENING_DEPTH   = 15   # record only the first N half-moves of each game
_MIN_FREQUENCY   = 3    # moves seen fewer than this many times are ignored


class OpeningBook:
    def __init__(self) -> None:
        # {position_key: {uci_move: frequency}}
        self._book: dict[str, dict[str, int]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fen_key(board: chess.Board) -> str:
        """Position key: pieces + active color + castling rights + en-passant.

        Drops the half-move clock and full-move number so transpositions
        that reach the same position via different move-counts still match.
        """
        parts = board.fen().split()
        return " ".join(parts[:4])

    def _load(self) -> None:
        positions = 0
        total_moves = 0
        unique_files: set[str] = set()
        for pgn_name in _PGN_FILES_WEIGHTED:
            pgn_path = _DATA_DIR / pgn_name
            if not pgn_path.exists():
                logger.debug("Opening book: skipping missing file %s", pgn_name)
                continue
            games = 0
            with open(pgn_path, encoding="utf-8", errors="ignore") as f:
                while True:
                    game = chess.pgn.read_game(f)
                    if game is None:
                        break
                    board = game.board()
                    for i, move in enumerate(game.mainline_moves()):
                        if i >= _OPENING_DEPTH:
                            break
                        key = self._fen_key(board)
                        uci = move.uci()
                        if key not in self._book:
                            self._book[key] = {}
                            positions += 1
                        self._book[key][uci] = self._book[key].get(uci, 0) + 1
                        board.push(move)
                        total_moves += 1
                    games += 1
            unique_files.add(pgn_name)
            logger.debug("Opening book: loaded %d games from %s", games, pgn_name)

        logger.info(
            "Opening book ready — %d positions, %d moves from %d PGN files (%d tactical double-weighted)",
            positions, total_moves, len(unique_files), len(_TACTICAL_PLAYERS),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_move(self, board: chess.Board) -> str | None:
        """Return a weighted-random book move or ``None`` if out of book.

        Moves seen fewer than ``_MIN_FREQUENCY`` times are excluded to
        avoid rare/dubious lines.  The chosen move is always verified
        against the board's legal moves before being returned.
        """
        key = self._fen_key(board)
        if key not in self._book:
            return None

        candidates = {
            m: f for m, f in self._book[key].items() if f >= _MIN_FREQUENCY
        }
        if not candidates:
            return None

        # Weighted random selection
        total = sum(candidates.values())
        r = random.randint(0, total - 1)
        for uci, freq in candidates.items():
            r -= freq
            if r < 0:
                try:
                    move = chess.Move.from_uci(uci)
                    if move in board.legal_moves:
                        return uci
                except ValueError:
                    pass
        return None


book = OpeningBook()
