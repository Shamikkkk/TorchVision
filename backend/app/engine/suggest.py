import asyncio
import functools

from .model import PyroEngine


async def suggest_move(
    fen: str,
    engine: PyroEngine,
    wtime_ms: int | None = None,
    btime_ms: int | None = None,
) -> str:
    """Run engine inference off the event loop to avoid blocking FastAPI.

    wtime_ms / btime_ms: when both are provided, forwarded to the Rust engine
    so it can use time-based search (go wtime/btime).  Omit both to keep the
    existing node-limited behaviour.
    """
    loop = asyncio.get_event_loop()
    fn = functools.partial(
        engine.best_move,
        fen,
        wtime_ms=wtime_ms,
        btime_ms=btime_ms,
    )
    return await loop.run_in_executor(None, fn)
