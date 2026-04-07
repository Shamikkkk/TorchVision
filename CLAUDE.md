# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

---

## Session handoff (read this first)

Completed this session:
1. Phase B NNUE abandoned (see below)
2. Added Tal-style bonuses to Rust engine (`engine/src/search.rs`)
3. Wired Rust engine into Python backend via UCI subprocess
4. `backend/app/engine/rust_engine.py` — launches pyro.exe --no-nnue

First thing to do in new session:
1. Test backend: `cd backend && source venv/Scripts/activate && uvicorn app.main:app --port 8000`
2. Verify log shows: "Rust engine loaded" and "Pyro ready -- Rust Tal style"
3. Play a game via the frontend to verify Rust engine is responding

---

## Current Status

**Phase A (classical Python engine) — COMPLETE ✅**
**Phase B (Rust Tal engine + backend wiring) — COMPLETE ✅**
**Phase B NNUE — ABANDONED ❌** (768→256→1 plateaus at ~86cp RMSE, cannot beat PeSTO)
**Phase C (Tal bonuses in Rust) — COMPLETE ✅**
**Game Analyzer — COMPLETE ✅**

---

## Phase A — Classical Python Engine (COMPLETE)

eval_fn: `tal_style_eval` hardcoded in `model.py:best_move()` — permanent.
Startup: `"Pyro ready -- Tal style (depth 4 + NMP + LMR + AW)"`
Estimated ELO: ~1200-1400

Features:
- `tal_style_eval`: material + PST + Tal aggression (1.5x)
- King attack, pawn storm, open files, piece activity
- Castling bonus (+80cp), early queen penalty (-60cp)
- Pawn structure: doubled (-20cp), isolated (-15cp), connected passed (+30cp)
- Rook evaluation: open file (+25cp), semi-open (+15cp), connected (+20cp)
- Bishop pair bonus (+50cp)
- Endgame: king activity + passed pawn bonuses
- Killer moves, history heuristic
- Null move pruning (NMP, R=2)
- Late Move Reductions (LMR)
- Aspiration windows (AW, +/-50cp)
- Quiescence search (captures only, depth 4)
- Transposition table (1M entry cap)
- GM opening book (97k games, 31 grandmasters)
- Syzygy tablebases (290 files, <=6 pieces)
- Stockfish fallback (last resort)

### Engine move priority (runtime)

`PyroEngine.best_move()` in `backend/app/engine/model.py`:
0. **Syzygy tablebase** — <=6 pieces, no castling rights -> perfect play
1. **Opening book** — grandmaster PGN positions, first 15 moves, freq >= 3
2. **Rust engine** — `pyro.exe --no-nnue`, PeSTO + Tal, go nodes 5000
3. **Python minimax depth 4** — alpha-beta + NMP + LMR + AW + TT + `tal_style_eval`
4. **Stockfish** — external binary, last resort only

---

## Phase B — Rust Engine (COMPLETE)

### What's built (Rust engine `engine/`):
- Bitboard board representation (12 x u64)
- Full legal move generation (perft verified: 20/400/8902)
- Alpha-beta search with negamax
- PeSTO PST tapered evaluation + Tal-style bonuses (1.5x aggression)
- Tal bonuses: king attack, pawn storm, castling, early queen penalty,
  open file rooks, bishop pair, passed pawns (endgame)
- MVV-LVA move ordering
- Killer moves (2 slots per ply)
- Quiescence search
- Null move pruning (NMP, R=2)
- Late Move Reductions (LMR)
- UCI protocol (position/go/go depth/go nodes/uci/isready/quit)
- Node-limited search (`go nodes N`)
- `--no-nnue` CLI flag (legacy, forces PST eval without NNUE attempt)
- NNUE accumulator (768->256->1, CReLU) — built but abandoned

### Current engine state:
- Evaluation: PeSTO + Tal bonuses (always-on, no NNUE)
- Startup: `"Pyro ready -- Rust Tal style (depth 4 + NMP + LMR)"`
- Wired into Python backend via `backend/app/engine/rust_engine.py`
- Falls back to Python `tal_style_eval` if Rust binary not found

### Backend wiring:
- `backend/app/engine/rust_engine.py`: launches `pyro.exe --no-nnue` subprocess
- `RustEngine.best_move(fen)` → sends `position fen` + `go nodes 5000` via UCI
- `model.py` tries Rust engine first, falls back to Python minimax
- Move priority: Tablebase → Opening book → Rust engine → Python minimax → Stockfish

### NNUE — ABANDONED
- 768→256→1 architecture plateaus at ~86cp RMSE after 130 epochs on 5M Stockfish positions
- Cannot beat PeSTO (0cp error) — lost 0-200 in every validation attempt
- All attempts: PST self-play, Stockfish CSV, logit-space loss, direct cp MSE — all 0%
- Scripts remain in `backend/scripts/` for future reference
- Would need deeper architecture (768→512→32→32→1) or Bullet trainer with 100M+ positions

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

### Rust Engine
- **Bitboards** — 12 x u64 piece representation
- **Alpha-beta** + NMP + LMR + killers + qsearch
- **PeSTO** tapered PST evaluation + **Tal bonuses** (1.5x aggression)
- **UCI protocol** — stdin/stdout, wired into Python backend
- **NNUE** 768->256->1, CReLU (abandoned, code remains)

### Communication
- **WebSocket** — live game loop (moves, game state, clocks)
- **REST (HTTP)** — engine suggestions + eval score (`/api/suggest` returns `{move, eval}`)

---

## File Locations

```
torch/
├── frontend/              # Vite + React app
│   ├── src/
│   │   ├── components/
│   │   │   ├── analyzer/  # AnalyzerPanel, AnalysisBoard, GameList, MoveClassification, AccuracySummary
│   │   │   └── ...        # Board, Clock, EvalBar, MoveList, EnginePanel, GameOverModal, etc.
│   │   ├── hooks/         # useGameSocket, useAnalyzer
│   │   ├── lib/           # sounds.ts, wsClient.ts, chess.ts
│   │   └── types/         # game.ts
│   └── ...
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, CORS, router registration
│   │   ├── ws/                # WebSocket game loop + 5-minute chess clock
│   │   ├── routes/            # REST endpoints (/api/suggest, /api/analyze/*)
│   │   ├── engine/
│   │   │   ├── model.py         # PyroEngine — mode selection, best_move() interface
│   │   │   ├── evaluate.py      # Hand-crafted eval: material + PST + Tal bonuses
│   │   │   ├── search.py        # Minimax + alpha-beta + TT (eval_fn is a parameter)
│   │   │   ├── opening_book.py  # Grandmaster PGN book — weighted random move selection
│   │   │   ├── tablebase.py     # Syzygy tablebase prober (WDL+DTZ, <=6 pieces)
│   │   │   ├── rust_engine.py    # UCI subprocess wrapper for Rust Pyro engine
│   │   │   ├── nnue.py          # Python NNUE eval wrapper (768->256->32->32->1)
│   │   │   └── suggest.py       # Async wrapper (run_in_executor)
│   │   └── chess_utils/
│   │       ├── board.py         # Helpers: uci_to_san, is_sacrifice, etc.
│   │       └── opening_book.py  # Hardcoded BOOK_LINES frozenset + is_book_move()
│   ├── scripts/
│   │   ├── generate_selfplay_rust.py  # Self-play data gen via Rust UCI engine
│   │   ├── train_nnue_rust.py         # NNUE trainer (768->256->1, logit-space loss)
│   │   ├── validate_nnue_rust.py      # NNUE vs PST match validator
│   │   └── init_nnue_weights.py       # Material-initialized weight generator
│   ├── model_training/        # Standalone data pipeline + training scripts
│   ├── models/                # nnue_rust.pt saved here after training
│   ├── data/
│   │   ├── syzygy/            # Syzygy tablebase files (.rtbw/.rtbz) ~1 GB
│   │   ├── selfplay_rust.plain  # Self-play training data (nnue-pytorch format)
│   │   ├── Tal.pgn / Kasparov.pgn / Fischer.pgn / Carlsen.pgn
│   │   └── positions_sf_deep.csv
│   └── requirements.txt
├── engine/                    # Rust chess engine (Pyro)
│   ├── Cargo.toml
│   ├── pyro.nnue              # NNUE weights (394KB)
│   └── src/
│       ├── main.rs            # UCI loop, Engine struct, --no-nnue flag
│       ├── board.rs           # Bitboard board, FEN parsing, make_null_move
│       ├── movegen.rs         # Legal move gen, make_move, perft
│       ├── search.rs          # PeSTO eval, alpha-beta + NMP + LMR + killers + qsearch
│       └── nnue.rs            # NNUE 768->256->1, accumulator, binary I/O
└── CLAUDE.md
```

---

## Commands

### Rust engine
```bash
cd engine
cargo build --release
# Binary: engine/target/release/pyro.exe
# Weights: engine/pyro.nnue (auto-loaded at startup)

# Run with NNUE:
echo -e "uci\nisready\nposition startpos\ngo depth 6\nquit" | ./target/release/pyro.exe

# Run with PST only:
echo -e "uci\nisready\nposition startpos\ngo depth 6\nquit" | ./target/release/pyro.exe --no-nnue
```

### Self-play data generation
```bash
cd backend
source venv/Scripts/activate
python -m scripts.generate_selfplay_rust --games 100000 --output data/selfplay_rust.plain
python -m scripts.generate_selfplay_rust --games 50000 --resume  # append to existing
```

### NNUE training
```bash
cd backend
source venv/Scripts/activate
python -m scripts.train_nnue_rust --plain data/selfplay_rust.plain --epochs 30
python -m scripts.train_nnue_rust --plain data/selfplay_rust.plain --epochs 30 --no-export  # skip pyro.nnue
```

### NNUE validation
```bash
cd backend
source venv/Scripts/activate
python -m scripts.validate_nnue_rust --games 200
```

### Frontend
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production build
npm run lint
npm run type-check
```

### Backend
```bash
cd backend
source venv/Scripts/activate
uvicorn app.main:app --port 8000 --host 0.0.0.0
```

---

## Architecture Decisions

### WebSocket for the game loop
The WebSocket connection owns all in-game state: moves, turn, clocks, game-over signals. The client sends a move message; the server validates it with python-chess, updates state, and broadcasts the new FEN + metadata back.

### REST for engine suggestions
Engine move suggestions (`/api/suggest`) are stateless one-shot calls — send a FEN, receive a move + evaluation.

### chess.js on the frontend is for UX only
chess.js validates moves client-side for instant feedback. The server's python-chess result is authoritative.

### eval_fn is a parameter in search.py
`search.best_move(fen, depth, eval_fn)` accepts any `board -> centipawns` callable.

### FEN is the canonical game state format
Pass FEN strings between client and server. PGN is used only for export/import, not for live state.

---

## Conventions

### TypeScript / React
- Strict TypeScript (`"strict": true`).
- One component per file; filename matches the exported component name.
- Custom hooks in `src/hooks/`, prefixed with `use`.
- WebSocket logic in `useGameSocket` — components do not open sockets directly.
- Tailwind only for styling; no CSS modules.

### Python / FastAPI
- Type-annotate all function signatures with Pydantic models for request/response bodies.
- WebSocket handlers in `app/ws/`; REST route handlers in `app/routes/`.
- Engine inference always called from `app/engine/` — route handlers must not import torch.
- Use `python-chess`'s `Board` object as the single source of truth server-side.
- `model_training/` and `scripts/` are run from `backend/`.

### Git
- Branch naming: `feat/<name>`, `fix/<name>`, `chore/<name>`.
- Commits: imperative mood, present tense.

---

## Do-Nots

- **Do not** use `create-react-app`. This project uses Vite.
- **Do not** manage game state in a global store (Redux, Zustand).
- **Do not** send move objects over WebSocket; send FEN strings and UCI notation.
- **Do not** run `uvicorn` with `--workers > 1` — in-memory game state is not process-safe.
- **Do not** import `chess.js` in backend or `python-chess` in frontend.
- **Do not** use `any` in TypeScript without a comment.
- **Do not** hardcode the backend URL — use Vite env variables.
- **Do not** block the FastAPI event loop — `suggest.py` wraps `best_move` via `run_in_executor`.
- **Do not** use `pip install` without an active virtualenv (`venv`, not `.venv`).
- **Do not** try to kill uvicorn using `taskkill` from Claude Code — use `Ctrl+C` in the terminal.

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

---

## Windows-Specific Notes

- Use **Git Bash** or **PowerShell** — avoid CMD.
- Virtualenv activation: `source venv/Scripts/activate` (Git Bash).
- If `uvicorn --reload` misses changes, set `WATCHFILES_FORCE_POLLING=true`.
- PyTorch CPU: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.
- **Killing uvicorn**: Claude Code cannot kill processes from other terminals. Use `Ctrl+C` in the uvicorn terminal.
