# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

---

## Current Status

**Phase 1 (UI polish) — complete.**
**Phase 2 (classical engine) — complete and working.**
**Phase A (classical engine tuning) — COMPLETE ✅ (~1200–1400 ELO estimated)**
**Phase 3 (neural network) — NNUE trained + scaled; disabled pending MCTS.**
**Game Analyzer — complete.**

### Completed features
- Move classification system: brilliant(!!) / best(!) / good / book(📖) / inaccuracy(?!) / mistake(?) / blunder(??) / miss — shown in EnginePanel and MoveList after every human move
- Randomized player color per game; board auto-flips; engine plays first when human is black
- Opening book detection via hardcoded `frozenset` of common SAN sequences (`chess_utils/opening_book.py`)
- **Game Analyzer tab** (`🔍 Analyze`):
  - `GET /api/analyze/games/{username}` — fetches last 10 chess.com games
  - `POST /api/analyze/game/stream` — SSE streaming Stockfish analysis (depth ~0.3s/move)
  - Components: `GameList`, `AnalysisBoard`, `MoveClassification`, `AccuracySummary`, `AnalyzerPanel`
  - Keyboard navigation (← / →), accuracy %, per-classification counts, colored board highlights
- **Tal-style evaluation** (`app/engine/evaluate.py`):
  - `tal_style_eval` = PST base + Tal bonuses × 1.5 aggression multiplier
  - Bonuses: king attack (per-piece × attacker count), open files toward enemy king, pawn storm, piece activity, enemy king safety
  - Opening bonuses: +80cp castling rights on home square, −60cp early queen development (before move 10)
  - `tal_style_eval` is the default eval function in `search.py`
- **Grandmaster opening book** (`app/engine/opening_book.py`):
  - Parses Tal, Kasparov, Fischer, Carlsen PGNs at startup
  - Records first 15 half-moves per game; weighted random selection (min freq 3)
  - FEN key strips move counters so transpositions match
- **Syzygy tablebase** (`app/engine/tablebase.py`):
  - 290 files, 3-4-5 piece, ~1 GB — stored in `backend/data/syzygy/`
  - `TablebaseProber`: probes WDL then DTZ; skips if >6 pieces or castling rights present
  - Download script: `backend/data/syzygy/download_syzygy.py`
- **Transposition table** (`app/engine/search.py`):
  - Module-level `_tt` dict (1M entry cap); keyed on `board.fen()`
  - Lookup before search, store after; cleared at start of each `best_move()` call
- **Tal fine-tuning** (`model_training/finetune_tal.py`):
  - Parses `data/Tal.pgn`, labels positions with `tal_style_eval`
  - Weighted sampling: sacrifice × 3, king attack × 2, normal × 1
  - Fine-tunes existing `torch_chess.pt` with lr=1e-4, 20 epochs; backs up prior weights
- **Premoves** (`frontend/src/components/Board.tsx`):
  - State: `premove {from, to}` + `premoveSq` (piece selected during engine's turn)
  - Red-orange highlight (`rgba(220,50,50,0.65)`) on queued premove squares
  - Executes on `[fen, isHumanTurn]` effect — validates legality first, silently clears if illegal
  - Right-click anywhere clears the premove; new game / game over clears automatically
  - Auto-promotes to queen; smoothness issues to revisit
- **Quiescence search** (`app/engine/search.py`): prevents horizon blunders, extends search through captures only, depth-capped at 4 plies
- **Repetition detection** (`app/engine/search.py`): `board.is_repetition(2)` returns draw score before searching
- **NNUE scaling fixed** (`app/engine/nnue.py`): `_CP_SCALE=1500`, sign flipped, now matches `tal_style_eval` range — disabled pending MCTS
- **Stockfish eval bar** (`app/routes/engine.py` + `useGameSocket.ts`): fully wired, SF depth-15, centipawns White-positive
- **Move ordering** (`app/engine/search.py`): captures searched before quiet moves
- **Data pipeline** (`backend/scripts/`):
  - `download_historical_pgns.py` — downloads GM PGN collections from pgnmentor.com
  - `download_chesscom.py` — fetches Chess.com games, labels with SF depth-8, outputs CSV
  - `build_training_data.py` — combines all PGNs in `data/` into `positions_combined.csv`; deduplicates against existing CSVs; resume support via `.processed_pgns.txt`
  - 97,252 GM games downloaded: Tal, Kasparov, Fischer, Carlsen, Karpov, Petrosian, Spassky, Smyslov, Korchnoi, Capablanca, Morphy, Anderssen, Spielmann, Alekhine, Najdorf, Bronstein, Geller, Larsen, Ljubojevic, Shirov, Topalov, Morozevich, Grischuk, Aronian, Nakamura, VachierLagrave, Jobava, Rapport, Firouzja, Gukesh, Praggnanandhaa
  - Target: ~1,000,000 combined positions in `data/positions_combined.csv`

### NNUE status (trained; scaling fixed; disabled)
- `models/nnue_deep_backup.pt` — 497,998 positions, Stockfish depth-12 labels, best val loss = 0.0305
- **Currently disabled** in search: `eval_fn = tal_style_eval` hardcoded in `backend/app/engine/model.py`
- **Scaling FIXED**: `_CP_SCALE=1500`, sign corrected — output now matches `tal_style_eval` range
- **Reason still disabled**: Python minimax too slow at depth 6; MCTS must replace minimax first
- **Next**: enable after MCTS is implemented

### Current stable state
- `eval_fn`: `tal_style_eval` (classical, no blunders)
- NNUE: disabled — needs billions of positions to be reliable (we have 634k, need 1B+)
- ChessNet: disabled — policy head untrained
- Engine plays real chess, no queen blunders

### Why NNUE failed (research findings)
- Need BILLIONS of positions before NNUE is reliable
- We had 634k — 1,580× too little data
- Simple (piece, square) features needed first
- Test with actual ELO games, not just val_loss

### Real roadmap to a strong engine

#### Phase A — COMPLETE ✅
All improvements implemented:
- `tal_style_eval` with Tal aggression bonuses (king attack, pawn storm, piece activity, king safety)
- Pawn structure: doubled pawns (−20cp), isolated pawns (−15cp), connected passed pawns (+30cp)
- Rook evaluation: open file (+25cp), semi-open file (+15cp), connected rooks (+20cp)
- Bishop pair bonus (+50cp)
- Endgame king activity (KING_EG_PST) + passed pawn bonuses (rank-scaled)
- Killer moves heuristic (2 slots per depth)
- History heuristic (depth² reward, sorted quiet moves)
- Null move pruning (NMP, R=2) — effectively adds 1–2 plies of search depth
- Late Move Reductions (LMR) — reduced search for quiet moves beyond move 4, re-search if interesting
- Aspiration windows (AW, ±50cp, up to 3 widenings per depth)
- Quiescence search (captures only, 4-ply cap)
- Transposition table (1M entry cap, keyed on FEN)
- Syzygy tablebases (3-4-5 piece, ~1 GB, perfect endgame play)
- GM opening book (97k games: Tal, Kasparov, Fischer, Carlsen + 27 others)

Estimated ELO: ~1200–1400

#### Phase B — Proper NNUE (longer term)
1. Generate 10M+ positions via self-play (not Stockfish labels)
2. Use simple HalfKA features (piece+square, no king buckets)
3. Train small network (256→32→32→1)
4. Validate with SPRT tests (actual game matches), not val_loss
5. Only enable when it beats `tal_style_eval` in 100 test games

#### Phase C — MCTS (after Phase B)
1. Train policy head with UCI moves
2. Enable MCTS with 200 simulations
3. Target: ~1800+ ELO

### Engine move priority (runtime)
`PyroEngine.best_move()` in `backend/app/engine/model.py`:
0. **Syzygy tablebase** — ≤6 pieces, no castling rights → perfect play
1. **Opening book** — grandmaster PGN positions, first 15 moves, freq ≥ 3
2. **Minimax depth 4** — alpha-beta + NMP + LMR + AW + TT + `tal_style_eval` (current default)
3. **Stockfish** — external binary, last resort only

### Engine startup mode (weights)
`PyroEngine.__init__` selects eval mode:
1. **mcts** — if `backend/models/torch_chess.pt` exists **and has a policy head**
2. **neural** — if `torch_chess.pt` exists with value head only
3. **classical** — `tal_style_eval` PST (current default, always available)
4. **stockfish** — last resort

### Training the neural network
Two paths to produce `backend/models/torch_chess.pt`:

**Option A — Supervised (faster start, ~2 hrs on CPU):**

Recommended: use `stream_parse` to go straight from network to CSV with nothing written to disk:
```bash
# One-shot: HTTP stream → zstd decompressor → PGN parser → CSV (no PGN on disk)
python -m model_training.stream_parse \
    --year 2024 --month 1 \
    --out data/positions.csv \
    --limit 500000

# Then train:
python -m model_training.train --csv data/positions.csv
```

Alternatively download first then parse:
```bash
# 1. Download compressed archive (~1–3 GB, .zst kept on disk)
python -m model_training.download --year 2024 --month 1 --out data/

# 2. Parse .zst directly (stream-decompressed, no full PGN written to disk)
python -m model_training.parse \
    --pgn data/lichess_db_standard_rated_2024-01.pgn.zst \
    --out data/positions.csv

# 3. Train
python -m model_training.train --csv data/positions.csv

# Quick smoke test (1000 positions from a local .pgn or .pgn.zst):
python -m model_training.parse --pgn data/lichess.pgn --out data/positions.csv --limit 1000
```

**Option B — Self-play (no external data needed, slower to converge):**
```bash
python -m model_training.selfplay                        # 50 iterations default
python -m model_training.selfplay --iterations 100 --simulations 200
python -m model_training.selfplay --resume               # continue from checkpoint
```
Checkpoints saved to `data/selfplay_checkpoints/`; best weights overwrite `models/torch_chess.pt` each iteration.

**Recommended:** run supervised training first (Option A) to get a reasonable starting point, then fine-tune with self-play (Option B `--resume`).

**Option C — Tal fine-tuning (Tal-style personality; run after A or B):**
```bash
# data/Tal.pgn already exists in the repo
python -m model_training.finetune_tal --pgn data/Tal.pgn
```
Backs up existing weights to `models/tal_finetuned_backup.pt` before overwriting.

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
- Engine: **classical minimax** (depth 4, PST eval) — default until `torch_chess.pt` is trained

### Known issue — killing uvicorn on Windows
**Do not use `taskkill` from within Claude Code's bash tool** — it cannot kill processes started in your own terminal session. Always use `Ctrl+C` in the terminal where uvicorn is running.

If port 8000 is stuck after a crash, run this in PowerShell (not from Claude):
```powershell
netstat -ano | findstr :8000        # find the PID
taskkill /PID <pid> /F              # kill it
```

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
│   │   ├── components/
│   │   │   ├── analyzer/  # AnalyzerPanel, AnalysisBoard, GameList, MoveClassification, AccuracySummary
│   │   │   └── ...        # Board, Clock, EvalBar, MoveList, EnginePanel, GameOverModal, etc.
│   │   ├── hooks/         # useGameSocket, useAnalyzer
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
│   │   ├── routes/            # REST endpoints (/api/suggest, /api/analyze/*)
│   │   ├── engine/
│   │   │   ├── model.py         # PyroEngine — mode selection, best_move() interface
│   │   │   ├── evaluate.py      # Hand-crafted eval: material + PST + Tal bonuses + opening penalties
│   │   │   ├── search.py        # Minimax + alpha-beta + transposition table (eval_fn is a parameter)
│   │   │   ├── opening_book.py  # Grandmaster PGN book — weighted random move selection
│   │   │   ├── tablebase.py     # Syzygy tablebase prober (WDL+DTZ, ≤6 pieces)
│   │   │   ├── nnue.py          # NNUE eval wrapper (768→256→32→32→1)
│   │   │   └── suggest.py       # Async wrapper (run_in_executor)
│   │   └── chess_utils/
│   │       ├── board.py         # Helpers: uci_to_san, is_sacrifice, has_mate_in_one, san_history
│   │       └── opening_book.py  # Hardcoded BOOK_LINES frozenset + is_book_move()
│   ├── model_training/        # Standalone data pipeline + training scripts
│   │   ├── engine_classical.py  # Wraps search.py for use as a labeller
│   │   ├── download.py          # Download Lichess .pgn.zst (compressed only, no decompress)
│   │   ├── parse.py             # .pgn or .pgn.zst → (FEN, eval_cp) CSV (streams .zst)
│   │   ├── stream_parse.py      # HTTP stream → zstd → PGN → CSV (nothing written to disk)
│   │   ├── dataset.py           # PyTorch Dataset + FEN→tensor encoding
│   │   ├── architecture.py      # ChessNet: stem + 4 ResBlocks + MLP head (~1.3M params)
│   │   ├── train.py             # Training loop, saves torch_chess.pt
│   │   └── finetune_tal.py      # Fine-tune on Tal's games with Tal-style weighting
│   ├── models/            # torch_chess.pt, nnue.pt saved here after training
│   ├── data/
│   │   ├── syzygy/        # Syzygy 3-4-5 piece tablebase files (.rtbw/.rtbz) — ~1 GB
│   │   │   └── download_syzygy.py  # Script to download tablebase files
│   │   ├── Tal.pgn / Kasparov.pgn / Fischer.pgn / Carlsen.pgn  # Grandmaster PGNs
│   │   └── positions_sf_deep.csv   # 497,998 positions labeled by Stockfish depth=12
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
