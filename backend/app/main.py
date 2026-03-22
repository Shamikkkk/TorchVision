import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .engine.model import TorchEngine
from .routes import engine as engine_routes
from .ws.handler import ws_game_endpoint

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = TorchEngine(settings.stockfish_path)
    app.state.engine = engine
    logger.info("Engine ready (mode: %s)", engine.mode)
    print("Registered routes:")
    for route in app.routes:
        print(" ", getattr(route, "path", route))
    yield
    logger.info("Shutting down")


app = FastAPI(title="Torch Chess", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

@app.get("/healthz")
async def health():
    return {"status": "ok"}


app.include_router(engine_routes.router, prefix="/api")
app.add_api_websocket_route("/ws/game", ws_game_endpoint)
