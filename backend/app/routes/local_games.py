"""Read-only access to locally persisted games (backend/data/local_games)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..chess_utils.game_store import STORE_DIR

router = APIRouter()

_NAME_RE = re.compile(r"^\d{4}-\d{2}\.pgn$")


@router.get("/local-games")
async def list_local_games() -> list[dict]:  # type: ignore[type-arg]
    """Month files with game counts, oldest first."""
    if not STORE_DIR.exists():
        return []
    out = []
    for path in sorted(STORE_DIR.glob("*.pgn")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            games = text.count("[Event ")
        except OSError:
            games = -1
        out.append({"file": path.name, "bytes": path.stat().st_size, "games": games})
    return out


@router.get("/local-games/{name}")
async def get_local_games_file(name: str) -> PlainTextResponse:
    """Raw PGN of one month file (name: YYYY-MM.pgn)."""
    if not _NAME_RE.match(name):
        raise HTTPException(400, "invalid file name (expected YYYY-MM.pgn)")
    path = STORE_DIR / name
    if not path.is_file():
        raise HTTPException(404, f"{name} not found")
    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))
