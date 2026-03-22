import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from ..chess_utils.board import apply_move, game_state_dict, new_board
from ..engine.suggest import suggest_move
from .manager import manager

logger = logging.getLogger(__name__)

CLOCK_MS = 300_000  # 5 minutes per side


def _state(board, resigned=False, white_ms=CLOCK_MS, black_ms=CLOCK_MS, winner=None):  # type: ignore[no-untyped-def]
    d = {**game_state_dict(board, resigned=resigned), "white_ms": white_ms, "black_ms": black_ms}
    if winner is not None:
        d["status"] = "timeout"
        d["winner"] = winner
    return d


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
                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms, winner=winner))
                return

            await manager.send(websocket, {"type": "tick", "white_ms": white_ms, "black_ms": black_ms})

    await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms))

    try:
        while True:
            data: dict = await websocket.receive_json()  # type: ignore[type-arg]
            msg_type: str = data.get("type", "")

            if msg_type == "new_game":
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
                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms))
                continue

            if msg_type == "resign" and not board.is_game_over() and not resigned:
                game_over = True
                if tick_task and not tick_task.done():
                    tick_task.cancel()
                resigned = True
                await manager.send(websocket, _state(board, resigned=True, white_ms=white_ms, black_ms=black_ms))
                continue

            if msg_type == "move" and not board.is_game_over() and not resigned and not game_over:
                uci: str = data.get("uci", "")
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
                    await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms))
                    continue

                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms))

                engine_uci = await suggest_move(board.fen(), engine)
                _, board = apply_move(board, engine_uci)

                if board.is_game_over():
                    game_over = True
                    if tick_task and not tick_task.done():
                        tick_task.cancel()

                await manager.send(websocket, _state(board, white_ms=white_ms, black_ms=black_ms))

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
