import asyncio
import functools

from .model import PyroEngine


async def suggest_move(
    fen: str,
    engine: PyroEngine,
    wtime_ms: int | None = None,
    btime_ms: int | None = None,
    movetime_ms: int | None = None,
) -> str:
    """Run engine inference off the event loop to avoid blocking FastAPI.

    Priority: movetime_ms > wtime_ms/btime_ms > node limit.
    """
    loop = asyncio.get_event_loop()
    fn = functools.partial(
        engine.best_move,
        fen,
        wtime_ms=wtime_ms,
        btime_ms=btime_ms,
        movetime_ms=movetime_ms,
    )
    return await loop.run_in_executor(None, fn)
