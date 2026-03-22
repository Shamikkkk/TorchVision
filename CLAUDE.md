# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

---

## Current Status

**Phase 1 (UI polish) — complete.**
**Phase 2 (classical engine) — complete and working.**
**Phase 3 (neural network) — architecture and training pipeline ready; weights not yet trained.**

### Running the app
Both servers must be started manually before running Claude Code. Open two terminals:

```bash
# Terminal 1 — backend (from backend/)
source venv/Scripts/activate        # Git Bash on Windows
uvicorn app.main:app --port 8000 --host 0.0.0.0

# Terminal 2 — frontend (from frontend/)
npm run dev                          # Vite picks 5173
```

- Backend: `http://localhost:8000` — healthcheck: `GET /healthz`
- Frontend: `http://localhost:5173`
- Engine: **classical minimax** (depth 4, PST eval) — Stockfish held as last-resort fallback

### Engine mode priority
`TorchEngine` in `backend/app/engine/model.py` selects mode at startup:
1. **neural** — if `backend/models/torch_chess.pt` exists (not yet trained)
2. **classical** — minimax depth 4 with hand-crafted PST evaluation (current default)
3. **stockfish** — external binary, last resort only

### Known issue — killing uvicorn on Windows
**Do not use `taskkill` from within Claude Code's bash tool** — it cannot kill processes started in your own terminal session. Always use `Ctrl+C` in the terminal where uvicorn is running.

If port 8000 is stuck after a crash, run this in PowerShell (not from Claude):
```powershell
netstat -ano | findstr :8000        # find the PID
taskkill /PID <pid> /F              # kill it
```

### Next steps — train the neural network
Run from `backend/` with venv active:
```bash
# 1. Download a Lichess games database (~15 GB, streams/decompresses on the fly)
python -m model_training.download --year 2024 --month 1 --out data/

# 2. Label 500k opening positions with the classical engine (depth 2, ~30 min)
python -m model_training.parse --pgn data/lichess_db_standard_rated_2024-01.pgn --out data/positions.csv

# 3. Train ChessNet (~1–2 hrs on CPU; saves to backend/models/torch_chess.pt)
python -m model_training.train --csv data/positions.csv

# Quick smoke test with only 1000 positions:
python -m model_training.parse --pgn data/lichess.pgn --out data/positions.csv --limit 1000
```
Once `torch_chess.pt` exists, restarting uvicorn automatically switches the engine to `mode = "neural"`.

---

## Stack

### Frontend
- **React 18** + **TypeScript** + **Vite**
- **Tailwind CSS** for styling
- **react-chessboard** for the board UI
- **chess.js** for client-side move validation and FEN/PGN handling

### Backend
- **FastAPI** (Python)
- **python-chess** for server-side move validation, legal move generation, and PGN export
- **Custom minimax engine** (`app/engine/search.py` + `app/engine/evaluate.py`) — depth 4, alpha-beta pruning, PST evaluation
- **Uvicorn** as the ASGI server
- **Stockfish 18** available as last-resort fallback if classical engine fails

### Communication
- **WebSocket** — live game loop (moves, game state, clocks)
- **REST (HTTP)** — engine suggestions + eval score (`/api/suggest` returns `{move, eval}`)

---

## Project Structure

```
torch/
├── frontend/          # Vite + React app
│   ├── src/
│   │   ├── components/    # Board, Clock, EvalBar, MoveList, GameOverModal, etc.
│   │   ├── hooks/         # useGameSocket (single source of truth for game state)
│   │   ├── lib/           # sounds.ts, wsClient.ts, chess.ts
│   │   └── types/         # game.ts
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── tsconfig.json
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, CORS, router registration
│   │   ├── ws/                # WebSocket game loop + 5-minute chess clock
│   │   ├── routes/            # REST endpoints (/api/suggest returns eval)
│   │   ├── engine/
│   │   │   ├── model.py       # TorchEngine — mode selection, best_move() interface
│   │   │   ├── evaluate.py    # Hand-crafted eval: material + PST tables
│   │   │   ├── search.py      # Minimax + alpha-beta (eval_fn is a parameter)
│   │   │   └── suggest.py     # Async wrapper (run_in_executor)
│   │   └── chess_utils/       # python-chess helpers
│   ├── model_training/        # Standalone data pipeline + training scripts
│   │   ├── engine_classical.py  # Wraps search.py for use as a labeller
│   │   ├── download.py          # Stream-download Lichess PGN (zstd)
│   │   ├── parse.py             # PGN → (FEN, eval_cp) CSV
│   │   ├── dataset.py           # PyTorch Dataset + FEN→tensor encoding
│   │   ├── architecture.py      # ChessNet: stem + 4 ResBlocks + MLP head (~1.3M params)
│   │   └── train.py             # Training loop, saves torch_chess.pt
│   ├── models/            # torch_chess.pt saved here after training
│   ├── requirements.txt
│   └── pyproject.toml
└── CLAUDE.md
```

---

## Commands

### Windows — run these in Git Bash or PowerShell

#### Frontend
```bash
cd frontend
npm install          # install dependencies
npm run dev          # dev server on http://localhost:5173
npm run build        # production build → dist/
npm run lint         # ESLint check
npm run type-check   # tsc --noEmit
```

#### Backend
```bash
cd backend
python -m venv venv
source venv/Scripts/activate    # Git Bash on Windows
# or: venv\Scripts\Activate.ps1   (PowerShell)

pip install -r requirements.txt
# Note: PyTorch needs a special install command (see requirements.txt comment):
#   pip install torch --index-url https://download.pytorch.org/whl/cpu

uvicorn app.main:app --port 8000 --host 0.0.0.0   # dev server
```

#### Running both together (dev)
Use two terminals — one for `npm run dev`, one for `uvicorn`.
No process manager is needed in development.

---

## Architecture Decisions

### WebSocket for the game loop
The WebSocket connection owns all in-game state: moves, turn, clocks, game-over signals. The client sends a move message; the server validates it with python-chess, updates state, and broadcasts the new FEN + metadata back. Do not use polling or REST for live game events.

### REST for engine suggestions
Engine move suggestions (`/api/suggest`) are stateless one-shot calls — send a FEN, receive a move + evaluation. The eval score from the classical/neural engine is stored in `engine.last_eval` and returned in the response. This keeps the WebSocket handler simple.

### chess.js on the frontend is for UX only
chess.js validates moves client-side to give instant feedback (highlight legal squares, reject illegal drags) before the move is sent over WebSocket. The server's python-chess result is authoritative. Never trust client-side validation as the source of truth.

### eval_fn is a parameter in search.py
`search.best_move(fen, depth, eval_fn)` accepts any `board → centipawns` callable. Phase 2 passes `evaluate` (hand-crafted PST); Phase 3 will pass the loaded neural network. The minimax code never changes between phases.

### PyTorch model is loaded once at startup
Load model weights in a FastAPI `lifespan` context manager, store on `app.state`. Do not reload the model per request.

### FEN is the canonical game state format
Pass FEN strings between client and server. Do not invent a custom board representation. PGN is used only for export/import, not for live state.

---

## Conventions

### TypeScript / React
- Strict TypeScript (`"strict": true` in tsconfig).
- One component per file; filename matches the exported component name.
- Custom hooks live in `src/hooks/`, prefixed with `use`.
- WebSocket logic lives in a single hook (`useGameSocket`) — components do not open sockets directly.
- Tailwind only for styling; no CSS modules, no inline `style={{}}` props except for truly dynamic values (e.g., board size in pixels).
- chess.js board state is kept in a `useState` hook; derive display data from it, do not duplicate state.

### Python / FastAPI
- Type-annotate all function signatures with Pydantic models for request/response bodies.
- WebSocket handlers go in `app/ws/`; REST route handlers go in `app/routes/`.
- Engine inference is always called from `app/engine/` — route handlers must not import torch directly.
- Use `python-chess`'s `Board` object as the single source of truth server-side; never manipulate FEN strings by hand.
- Log at INFO level for game events, DEBUG for engine internals.
- `model_training/` scripts are run from `backend/` so that both `app` and `model_training` are on `sys.path`.

### Git
- Branch naming: `feat/<name>`, `fix/<name>`, `chore/<name>`.
- Commits are imperative mood, present tense: "Add WebSocket move handler".

---

## Do-Nots

- **Do not** use `create-react-app`. This project uses Vite.
- **Do not** manage game state in a global store (Redux, Zustand) unless the need is clearly justified — local React state + context is sufficient.
- **Do not** send move objects over WebSocket; send FEN strings and the move in UCI notation (`e2e4`).
- **Do not** run `uvicorn` with `--workers > 1` during development — the in-memory game state is not process-safe.
- **Do not** import `chess.js` in backend code or `python-chess` in frontend code.
- **Do not** use `any` in TypeScript without a comment explaining why.
- **Do not** hardcode the backend URL — use a Vite env variable (`VITE_API_URL`, `VITE_WS_URL`).
- **Do not** block the FastAPI event loop with synchronous engine inference — `suggest.py` wraps `best_move` via `run_in_executor`.
- **Do not** use `pip install` without an active virtualenv. Always activate `venv` first (not `.venv` — the folder is named `venv`).
- **Do not** try to kill uvicorn using `taskkill` from Claude Code's bash tool — it only works from the terminal that started the process. Use `Ctrl+C` instead.

---

## Environment Variables

### Frontend (`frontend/.env.local`)
```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

### Backend (`backend/.env`)
```
STOCKFISH_PATH=C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe
LOG_LEVEL=DEBUG
```

Load backend env with `python-dotenv` or FastAPI's `pydantic-settings`.

---

## Windows-Specific Notes

- Use **Git Bash** or **PowerShell** — avoid CMD for dev commands.
- Virtualenv activation in Git Bash: `source venv/Scripts/activate` (folder is `venv`, not `.venv`; note `Scripts` not `bin`).
- If `uvicorn --reload` misses file changes, set `WATCHFILES_FORCE_POLLING=true` in the backend `.env`.
- Node path issues: make sure `node` and `npm` are on your system PATH (install via `winget install OpenJS.NodeJS.LTS` or the official installer).
- PyTorch CPU install: `pip install torch --index-url https://download.pytorch.org/whl/cpu` (avoids the 2 GB CUDA download).
- PyTorch CUDA builds require the matching CUDA toolkit version — check `torch.cuda.is_available()` after install.
- **Killing uvicorn**: Claude Code's bash tool cannot kill processes started in your own terminal. Always `Ctrl+C` in the uvicorn terminal. For stuck ports, use PowerShell: `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F`.
