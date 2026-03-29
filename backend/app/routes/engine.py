from __future__ import annotations

import chess
import chess.engine
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class SuggestRequest(BaseModel):
    fen: str


class SuggestResponse(BaseModel):
    move: str
    eval: float | None = None


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(body: SuggestRequest, request: Request) -> SuggestResponse:
    """Return the best move and centipawn eval for a FEN using Stockfish depth 15.

    Falls back to Pyro's minimax if Stockfish is unavailable.
    """
    sf_path: str = request.app.state.engine._stockfish_path
    board = chess.Board(body.fen)

    try:
        transport, sf = await chess.engine.popen_uci(sf_path)
        try:
            info = await sf.analyse(board, chess.engine.Limit(depth=15))
        finally:
            await sf.quit()
    except Exception:
        # Stockfish unavailable — fall back to Pyro
        pyro = request.app.state.engine
        from ..engine.suggest import suggest_move  # noqa: PLC0415
        move = await suggest_move(body.fen, pyro)
        return SuggestResponse(move=move, eval=pyro.last_eval)

    pv = info.get("pv") or []
    best_move = pv[0].uci() if pv else ""

    eval_cp: float | None = None
    score = info.get("score")
    if score is not None:
        cp = score.white().score(mate_score=10_000)
        eval_cp = float(cp) if cp is not None else None

    return SuggestResponse(move=best_move, eval=eval_cp)
