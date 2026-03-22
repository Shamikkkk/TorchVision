import asyncio

from .model import TorchEngine


async def suggest_move(fen: str, engine: TorchEngine) -> str:
    """Run engine inference off the event loop to avoid blocking FastAPI."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, engine.best_move, fen)
