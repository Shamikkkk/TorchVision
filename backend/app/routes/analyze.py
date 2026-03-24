"""Game analysis routes — fetches chess.com games and streams move-by-move analysis."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone

import chess
import chess.engine
import chess.pgn
import requests as _requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..chess_utils.board import has_mate_in_one, is_sacrifice, san_history, uci_to_san
from ..chess_utils.opening_book import is_book_move

logger = logging.getLogger(__name__)
router = APIRouter()


# ── chess.com helpers ────────────────────────────────────────────────────────

def _fetch_games_sync(username: str) -> list[dict]:  # type: ignore[type-arg]
    """Blocking — run via executor. Tries up to 3 months back."""
    now = datetime.now(timezone.utc)
    games: list[dict] = []  # type: ignore[type-arg]

    for delta in range(3):
        month = now.month - delta
        year = now.year
        while month <= 0:
            month += 12
            year -= 1

        url = f"https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}"
        try:
            resp = _requests.get(url, timeout=10, headers={"User-Agent": "TorchChess/1.0"})
        except Exception as exc:
            raise HTTPException(503, f"Network error reaching chess.com: {exc}") from exc

        if resp.status_code == 404:
            raise HTTPException(404, f"Player '{username}' not found on chess.com")
        if resp.status_code == 429:
            raise HTTPException(429, "chess.com rate limit — please try again in a few seconds")
        if resp.status_code != 200:
            raise HTTPException(502, f"chess.com API returned {resp.status_code}")

        for raw in reversed(resp.json().get("games", [])):
            games.append(_parse_raw_game(raw))
            if len(games) >= 10:
                return games

    return games


def _parse_raw_game(g: dict) -> dict:  # type: ignore[type-arg]
    white_d = g.get("white", {})
    black_d = g.get("black", {})
    white_result = white_d.get("result", "")

    if white_result == "win":
        result = "1-0"
    elif black_d.get("result") == "win":
        result = "0-1"
    else:
        result = "1/2-1/2"

    end_ts = g.get("end_time", 0)
    date_str = (
        datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if end_ts
        else "?"
    )
    url = g.get("url", "")
    game_id = url.rstrip("/").split("/")[-1] if url else str(end_ts)

    return {
        "id": game_id,
        "white": white_d.get("username", "?"),
        "black": black_d.get("username", "?"),
        "result": result,
        "date": date_str,
        "pgn": g.get("pgn", ""),
        "time_control": g.get("time_control", "?"),
    }


# ── Analysis helpers ─────────────────────────────────────────────────────────

def _score_to_cp(score: chess.engine.PovScore) -> float | None:
    try:
        cp = score.white().score(mate_score=10_000)
        return float(cp) if cp is not None else None
    except Exception:
        return None


def _classify(
    pre_board: chess.Board,
    move: chess.Move,
    best_uci: str,
    eval_before: float | None,
    eval_after: float | None,
    pre_history: list[str],
    move_san: str,
) -> tuple[str, str, int]:
    """Returns (classification, symbol, cp_loss)."""
    move_color = "w" if pre_board.turn == chess.WHITE else "b"

    if is_book_move(pre_history, move_san):
        return "book", "\U0001f4d6", 0

    if eval_before is not None and eval_after is not None:
        raw = (eval_before - eval_after) if move_color == "w" else (eval_after - eval_before)
        cp_loss = max(0, int(raw))
    else:
        cp_loss = 0

    is_best = (move.uci() == best_uci)
    post = pre_board.copy()
    post.push(move)
    missed_mate = has_mate_in_one(pre_board) and not post.is_checkmate()

    if missed_mate:
        return "miss", "missed #", cp_loss
    if is_best and is_sacrifice(pre_board, move) and cp_loss < 10:
        return "brilliant", "!!", 0
    if is_best:
        return "best", "!", 0
    if cp_loss <= 20:
        return "good", "", cp_loss
    if cp_loss <= 50:
        return "inaccuracy", "?!", cp_loss
    if cp_loss <= 150:
        return "mistake", "?", cp_loss
    return "blunder", "??", cp_loss


def _summary(moves: list[dict], player_color: str) -> dict:  # type: ignore[type-arg]
    player = [m for m in moves if m["is_player"]]
    cats = ("book", "brilliant", "best", "good", "inaccuracy", "mistake", "blunder", "miss")
    counts = {c: sum(1 for m in player if m["classification"] == c) for c in cats}

    scorable = [m for m in player if m["classification"] != "book"]
    if scorable:
        weighted = sum(min(m["cp_loss"], 300) for m in scorable)
        accuracy = max(0.0, min(100.0, 100.0 - weighted / len(scorable) / 3))
    else:
        accuracy = 100.0

    return {"player_color": player_color, **counts, "accuracy": round(accuracy, 1)}


async def _analysis_stream(pgn_str: str, username: str, sf_path: str):
    """Async generator that yields SSE-formatted lines."""
    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        yield f"data: {json.dumps({'type':'error','message':'Invalid PGN'})}\n\n"
        return

    white_player = game.headers.get("White", "").lower()
    player_color = "w" if username.lower() == white_player else "b"
    moves = list(game.mainline_moves())
    total = len(moves)

    if total == 0:
        yield f"data: {json.dumps({'type':'error','message':'No moves in PGN'})}\n\n"
        return

    try:
        transport, engine = await chess.engine.popen_uci(sf_path)
    except Exception as exc:
        yield f"data: {json.dumps({'type':'error','message':f'Stockfish unavailable: {exc}'})}\n\n"
        return

    board = game.board()
    results: list[dict] = []  # type: ignore[type-arg]

    try:
        for i, move in enumerate(moves):
            pre_board = board.copy()
            pre_fen = board.fen()
            pre_history = san_history(pre_board)
            move_san = board.san(move)

            # Analyse pre-move position — get best move + eval
            score_before: chess.engine.PovScore | None = None
            best_uci = move.uci()
            try:
                info = await engine.analyse(pre_board, chess.engine.Limit(time=0.3))
                score_before = info.get("score")
                pv = info.get("pv") or []
                if pv:
                    best_uci = pv[0].uci()
            except Exception:
                pass

            board.push(move)
            post_fen = board.fen()

            # Analyse post-move position — get eval_after
            score_after: chess.engine.PovScore | None = None
            if not board.is_game_over():
                try:
                    info_after = await engine.analyse(board, chess.engine.Limit(time=0.1))
                    score_after = info_after.get("score")
                except Exception:
                    pass

            eval_before = _score_to_cp(score_before) if score_before is not None else None
            eval_after = _score_to_cp(score_after) if score_after is not None else None

            best_san = uci_to_san(pre_board, best_uci)
            classification, symbol, cp_loss = _classify(
                pre_board, move, best_uci,
                eval_before, eval_after,
                pre_history, move_san,
            )

            move_color = "w" if pre_board.turn == chess.WHITE else "b"
            record: dict = {  # type: ignore[type-arg]
                "move_number": i // 2 + 1,
                "color": move_color,
                "san": move_san,
                "uci": move.uci(),
                "classification": classification,
                "symbol": symbol,
                "best_move": best_san,
                "cp_loss": cp_loss,
                "eval_before": eval_before,
                "eval_after": eval_after,
                "fen_before": pre_fen,
                "fen_after": post_fen,
                "is_player": move_color == player_color,
            }
            results.append(record)
            yield f"data: {json.dumps({'type':'move','data':record,'progress':[i+1,total]})}\n\n"

    finally:
        try:
            await engine.quit()
        except Exception:
            pass

    yield f"data: {json.dumps({'type':'summary','data':_summary(results, player_color)})}\n\n"
    yield 'data: {"type":"done"}\n\n'


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/games/{username}")
async def get_games(username: str) -> list[dict]:  # type: ignore[type-arg]
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_games_sync, username)


class StreamRequest(BaseModel):
    pgn: str
    username: str


@router.post("/game/stream")
async def stream_analysis(body: StreamRequest, request: Request) -> StreamingResponse:
    sf_path: str = request.app.state.engine._stockfish_path
    return StreamingResponse(
        _analysis_stream(body.pgn, body.username, sf_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
