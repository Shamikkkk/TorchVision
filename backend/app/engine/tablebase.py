"""
Syzygy tablebase prober for perfect endgame play.

Drop Syzygy .rtbw (and optionally .rtbz) files into backend/data/syzygy/
to enable this.  The engine will use the tablebase for any position with
6 or fewer pieces (and no castling rights, which tablebases don't support).

WDL (Win/Draw/Loss) is probed first to find the best outcome, then DTZ
(Distance To Zeroing) is used as a tiebreaker to convert as quickly as
possible.
"""

from __future__ import annotations

import logging
from pathlib import Path

import chess
import chess.syzygy

logger = logging.getLogger(__name__)

_TABLEBASE_PATH = Path(__file__).parent.parent.parent / "data" / "syzygy"


class TablebaseProber:
    def __init__(self) -> None:
        self._tb: chess.syzygy.Tablebase | None = None

        if not _TABLEBASE_PATH.exists():
            logger.info(
                "Tablebase: no files found at %s — skipping", _TABLEBASE_PATH
            )
            return

        rtbw_files = list(_TABLEBASE_PATH.glob("*.rtbw"))
        if not rtbw_files:
            logger.info(
                "Tablebase: no .rtbw files found at %s — skipping", _TABLEBASE_PATH
            )
            return

        try:
            self._tb = chess.syzygy.open_tablebase(str(_TABLEBASE_PATH))
            logger.info("Tablebase: loaded %d tablebase files ✅", len(rtbw_files))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tablebase: failed to load (%s)", exc)

    @property
    def available(self) -> bool:
        return self._tb is not None

    def best_move(self, board: chess.Board) -> chess.Move | None:
        """Return the tablebase-optimal move, or ``None`` if not applicable.

        Guards:
        - More than 6 pieces: outside tablebase range
        - Any castling rights: tablebases don't encode castling
        """
        if not self.available:
            return None
        if len(board.piece_map()) > 6:
            return None
        if board.castling_rights:
            return None

        best_move: chess.Move | None = None
        best_wdl: int = -3
        best_dtz: float = float("inf")

        for move in board.legal_moves:
            board.push(move)
            try:
                wdl = -self._tb.probe_wdl(board)   # type: ignore[union-attr]
                dtz = -self._tb.probe_dtz(board)    # type: ignore[union-attr]
                if wdl > best_wdl or (wdl == best_wdl and dtz < best_dtz):
                    best_wdl = wdl
                    best_dtz = dtz
                    best_move = move
            except Exception:  # noqa: BLE001
                pass
            finally:
                board.pop()

        return best_move


tablebase = TablebaseProber()
