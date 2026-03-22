from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..engine.suggest import suggest_move

router = APIRouter()


class SuggestRequest(BaseModel):
    fen: str


class SuggestResponse(BaseModel):
    move: str
    eval: float | None = None


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(body: SuggestRequest, request: Request) -> SuggestResponse:
    engine = request.app.state.engine
    move = await suggest_move(body.fen, engine)
    # Classical and neural modes populate last_eval during best_move();
    # Stockfish mode leaves it None.
    return SuggestResponse(move=move, eval=engine.last_eval)
