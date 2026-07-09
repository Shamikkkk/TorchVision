import asyncio
import logging
import random

import chess as _chess
from fastapi import WebSocket, WebSocketDisconnect

from ..chess_utils.board import (
    apply_move,
    game_state_dict,
    has_mate_in_one,
    is_sacrifice,
    new_board,
    result_of,
    san_history,
    uci_to_san,
)
from ..chess_utils.game_store import save_game
from ..chess_utils.opening_book import is_book_move
from ..engine.pyro_voice import PyroVoice, game_end_fields, voice_fields
from ..engine.suggest import suggest_move
from .manager import manager

logger = logging.getLogger(__name__)

CLOCK_MS = 300_000  # 5 minutes per side


def _state(
    board,  # type: ignore[no-untyped-def]
    *,
    resigned: bool = False,
    white_ms: int = CLOCK_MS,
    black_ms: int = CLOCK_MS,
    winner: str | None = None,
    human_color: str = "w",
) -> dict:  # type: ignore[type-arg]
    d = {
        **game_state_dict(board, resigned=resigned),
        "white_ms": white_ms,
        "black_ms": black_ms,
        "human_color": human_color,
    }
    if winner is not None:
        # Timeout: the clock decides the winner.
        d["status"] = "timeout"
        d["winner"] = winner
    else:
        # Checkmate/resignation: derive the winner so the frontend never has
        # to guess (winner-less decisive states used to render as ½–½).
        derived = result_of(board, d["status"], resigner=human_color if resigned else None)
        if derived is not None:
            d["winner"] = derived
    return d


_MOVETIME: dict[str, int | None] = {
    "beginner":     100,
    "intermediate": 500,
    "advanced":     2000,
    "expert":       5000,
    "master":       None,  # use full clock
}


def _difficulty_movetime(d: str) -> int | None:
    return _MOVETIME.get(d, None)


def _pyro_result(winner: str | None, human_color: str) -> str:
    """Pyro's result ('win'|'loss'|'draw') from the winner the state message
    carries — same derivation the frontend sees, so voice and UI can't
    disagree."""
    if winner is None:
        return "draw"
    return "loss" if winner == human_color else "win"


def _persist(board: _chess.Board, st: dict, human_color: str) -> None:  # type: ignore[type-arg]
    """Fail-open PGN persistence of a finished game."""
    save_game(board, human_color=human_color, status=st.get("status", "?"), winner=st.get("winner"))

async def ws_game_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    board = new_board()
    engine = websocket.app.state.engine
    resigned = False
    white_ms: int = CLOCK_MS
    black_ms: int = CLOCK_MS
    clock_started = False
    game_over = False
    tick_task: asyncio.Task | None = None  # type: ignore[type-arg]
    human_color: str = random.choice(["w", "b"])
    current_difficulty: str = "master"
    voice = PyroVoice()
    voice_enabled = True

    async def run_clock() -> None:
        nonlocal white_ms, black_ms, game_over

        while not game_over:
            await asyncio.sleep(1.0)
            if game_over:
                break

            if board.turn:  # chess.WHITE == True
                white_ms = max(0, white_ms - 1000)
                timed_out, winner = white_ms == 0, "b"
            else:
                black_ms = max(0, black_ms - 1000)
                timed_out, winner = black_ms == 0, "w"

            if timed_out:
                game_over = True
                st = _state(board, white_ms=white_ms, black_ms=black_ms, winner=winner, human_color=human_color)
                st.update(game_end_fields(voice, _pyro_result(st.get("winner"), human_color), enabled=voice_enabled))
                await manager.send(websocket, st)
                _persist(board, st, human_color)
                return

            await manager.send(websocket, {"type": "tick", "white_ms": white_ms, "black_ms": black_ms})

    async def engine_opening_move() -> None:
        """Engine plays the first move of a game (human is black)."""
        nonlocal board
        _mt = _difficulty_movetime(current_difficulty)
        if _mt is not None:
            engine_uci = await suggest_move(board.fen(), engine, movetime_ms=_mt)
        else:
            engine_uci = await suggest_move(board.fen(), engine, wtime_ms=white_ms, btime_ms=black_ms)
        pre_board = board
        _, board = apply_move(board, engine_uci)
        st = _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color)
        st.update(voice_fields(
            voice, pre_board, engine_uci, engine.last_eval,
            ply=len(board.move_stack), enabled=voice_enabled, game_start=True,
        ))
        await manager.send(websocket, st)

    # Send initial state
    await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color))

    # If human is black, engine plays the first move immediately
    if human_color == "b":
        await engine_opening_move()

    try:
        while True:
            logger.debug("Waiting for next message...")
            try:
                data: dict = await websocket.receive_json()  # type: ignore[type-arg]
            except Exception:
                logger.exception("Exception while receiving WebSocket message — closing connection")
                raise
            msg_type: str = data.get("type", "")

            if msg_type == "voice":
                voice_enabled = bool(data.get("enabled", True))
                continue

            if msg_type == "new_game":
                current_difficulty = data.get("difficulty") or "master"
                if "voice_enabled" in data:
                    voice_enabled = bool(data.get("voice_enabled"))
                game_over = True
                if tick_task and not tick_task.done():
                    tick_task.cancel()
                board = new_board()
                resigned = False
                game_over = False
                white_ms = CLOCK_MS
                black_ms = CLOCK_MS
                clock_started = False
                tick_task = None
                voice.reset()
                human_color = random.choice(["w", "b"])
                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color))
                # Engine plays first if human is black
                if human_color == "b":
                    await engine_opening_move()
                continue

            if msg_type == "resign" and not board.is_game_over() and not resigned:
                game_over = True
                if tick_task and not tick_task.done():
                    tick_task.cancel()
                resigned = True
                st = _state(board, resigned=True, white_ms=white_ms, black_ms=black_ms, human_color=human_color)
                st.update(game_end_fields(voice, _pyro_result(st.get("winner"), human_color), enabled=voice_enabled))
                await manager.send(websocket, st)
                _persist(board, st, human_color)
                continue

            if msg_type == "move" and not board.is_game_over() and not resigned and not game_over:
                uci: str = data.get("uci", "")
                logger.debug("Human move received: %s", uci)

                # Capture pre-move state for best_was analysis
                pre_move_board = board.copy()
                pre_move_fen = board.fen()
                pre_move_history = san_history(pre_move_board)
                human_san = uci_to_san(pre_move_board, uci)

                ok, board = apply_move(board, uci)
                if not ok:
                    await manager.send(websocket, {"type": "error", "message": f"Illegal move: {uci}"})
                    continue

                if not clock_started:
                    clock_started = True
                    tick_task = asyncio.create_task(run_clock())

                if board.is_game_over():
                    game_over = True
                    if tick_task and not tick_task.done():
                        tick_task.cancel()
                    st = _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color)
                    st.update(game_end_fields(voice, _pyro_result(st.get("winner"), human_color), enabled=voice_enabled))
                    await manager.send(websocket, st)
                    _persist(board, st, human_color)
                    continue

                # Send state immediately so the frontend sees the human's move
                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color))

                # --- Engine reply + move classification ---
                # Wrapped in its own try/except so an engine crash does not close
                # the WebSocket — we log the error and keep the loop alive.
                try:
                    logger.debug("Engine thinking (fen=%s)", board.fen())
                    _mt = _difficulty_movetime(current_difficulty)
                    if _mt is not None:
                        engine_uci = await suggest_move(board.fen(), engine, movetime_ms=_mt)
                    else:
                        engine_uci = await suggest_move(board.fen(), engine, wtime_ms=white_ms, btime_ms=black_ms)
                    eval_after: float | None = engine.last_eval
                    tb_wdl: int | None = getattr(engine, "last_tb_wdl", None)
                    logger.debug("Engine chose %s (eval=%s)", engine_uci, eval_after)

                    if not engine_uci:
                        logger.error("Engine returned empty move for fen=%s — skipping reply", board.fen())
                        continue

                    # --- Move classification ---
                    if is_book_move(pre_move_history, human_san):
                        classification = "book"
                        symbol = "\U0001f4d6"  # 📖
                        best_san = human_san
                        cp_loss = 0
                        is_best = True
                    else:
                        # Analyse pre-move position
                        missed_mate = has_mate_in_one(pre_move_board)
                        best_uci = await suggest_move(pre_move_fen, engine)
                        eval_before: float | None = engine.last_eval
                        best_san = uci_to_san(pre_move_board, best_uci)
                        is_best = (uci == best_uci)

                        # cp_loss is always positive and from human's perspective
                        if eval_before is not None and eval_after is not None:
                            if human_color == "w":
                                cp_loss = max(0, int(eval_before - eval_after))
                            else:
                                cp_loss = max(0, int(eval_after - eval_before))
                        else:
                            cp_loss = 0

                        human_move_obj = _chess.Move.from_uci(uci)
                        if missed_mate:
                            classification = "miss"
                            symbol = "missed #"
                        elif is_best and is_sacrifice(pre_move_board, human_move_obj) and cp_loss < 10:
                            classification = "brilliant"
                            symbol = "!!"
                        elif is_best:
                            classification = "best"
                            symbol = "!"
                        elif cp_loss <= 20:
                            classification = "good"
                            symbol = ""
                        elif cp_loss <= 50:
                            classification = "inaccuracy"
                            symbol = "?!"
                        elif cp_loss <= 150:
                            classification = "mistake"
                            symbol = "?"
                        else:
                            classification = "blunder"
                            symbol = "??"

                    await manager.send(websocket, {
                        "type": "best_was",
                        "classification": classification,
                        "human_move": human_san,
                        "best_move": best_san,
                        "cp_loss": cp_loss,
                        "is_best": is_best,
                        "symbol": symbol,
                    })

                    pre_engine_board = board
                    ok_engine, board = apply_move(board, engine_uci)
                    if not ok_engine:
                        logger.error(
                            "Engine returned illegal move %r (fen=%s) — skipping engine reply",
                            engine_uci, pre_move_fen,
                        )
                        continue

                    if board.is_game_over():
                        game_over = True
                        if tick_task and not tick_task.done():
                            tick_task.cancel()

                    # --- G13 voice + G15 heat (fail-open, R3) ---
                    st = _state(board, white_ms=white_ms, black_ms=black_ms, human_color=human_color)
                    if board.is_game_over():
                        st.update(game_end_fields(
                            voice, _pyro_result(st.get("winner"), human_color), enabled=voice_enabled,
                        ))
                    else:
                        st.update(voice_fields(
                            voice, pre_engine_board, engine_uci, eval_after,
                            ply=len(board.move_stack), enabled=voice_enabled, tb_wdl=tb_wdl,
                        ))
                    await manager.send(websocket, st)
                    if board.is_game_over():
                        _persist(board, st, human_color)

                except Exception:
                    logger.exception(
                        "Engine error after human move %s (fen=%s) — loop continues",
                        uci, pre_move_fen,
                    )

    except WebSocketDisconnect:
        game_over = True
        if tick_task and not tick_task.done():
            tick_task.cancel()
        manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception:
        game_over = True
        if tick_task and not tick_task.done():
            tick_task.cancel()
        manager.disconnect(websocket)
        logger.exception("Unhandled exception in ws_game_endpoint")
