# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

---

## Current Goal (set April 15, 2026)

Make Pyro a **scary tactical chess engine with a Mittens-style 
personality** — not a silent strength-maxxing engine.

Target: **2000-2200 CCRL strength** combined with **vicious 
Tal-style tactical play** and a **theatrical, intimidating UX**. 
Reaching 3000 Elo is explicitly NOT the goal. A 2200-rated 
engine already crushes 95%+ of chess.com users; the differentiator 
is *how it plays* and *how it feels to play against*, not raw 
strength beyond that point.

Strategic implications:
- **NNUE v2 (Phase D) is DEFERRED indefinitely.** NNUE produces 
  precise positional play (Magnus-style) which is the OPPOSITE 
  of the desired Tal-style violence. The hand-crafted Tal eval 
  is philosophically aligned with the goal in a way NNUE isn't.
- **MCTS (Phase E) similarly deferred** — MCTS without a strong 
  neural value head is weaker than alpha-beta + PeSTO+Tal.
- **Phase G is the active development track.** See Phase G 
  section below.
- Some style choices may COST 20-50 Elo vs pure strength tuning. 
  That's an acceptable trade. Mittens itself was deliberately 
  throttled.

Realistic timeline at ~1hr sessions, 2-3 sessions/week: 
8-12 weeks to ship Phase G as a complete product.

---

## Current State (as of April 15, 2026)
**Phase A (Python classical engine) — COMPLETE ✅**
**Phase B (Rust engine + Tal bonuses) — COMPLETE ✅**
**Phase C (NNUE) — ABANDONED ❌**
**Phase C.2 (Rust engine polish) — COMPLETE ✅**
**Phase D (NNUE v2) — DEFERRED 🛑**
**Phase E (MCTS) — DEFERRED 🛑**
**Phase G (The Mittens Path) — ACTIVE 🔥**
**Phase G Baseline Measured: Pyro ~1746 at 10s+0.1s 📊**
**Game Analyzer — COMPLETE ✅**
**Frontend: difficulty levels + opening name — COMPLETE ✅**

### What's working right now:
- Rust engine live via UCI subprocess with full time management
- Tal-style bonuses in Rust evaluate()
- PeSTO PST tapered evaluation
- NMP + LMR + killers + quiescence
- Transposition table (Zobrist hashing, 1M entries)
- History heuristic (gravity formula, malus for searched quiets)
- Losing capture ordering (QxP searched after killers)
- Fool's Mate fix (quiescence checkmate before stand-pat)
- Mate distance preference (faster mates scored higher)
- Aspiration windows (±50cp, widen on fail-low/fail-high, full
  window at depth 1 and after mate scores)
- Check extension (+1 ply when in check, via depth shadowing)
- Futility pruning (depth 1-2, 100/300cp margins, skip quiet
  non-check non-promotion moves below alpha margin)
- UCI time management (go wtime/btime/winc/binc/movestogo and
  go movetime supported, Instant-based deadline threaded through
  search alongside node_limit, 50ms safety margin, 10ms floor,
  25% clock ceiling per move, soft check at top of each ID
  iteration, partial iterations discarded via iter_completed)
- Python backend passes white_ms/btime_ms through suggest_move
  chain (handler.py → suggest.py → model.py → rust_engine.py)
  so live games use time-based search. Analyzer and REST
  /api/suggest intentionally stay node-limited.
- NODE_LIMIT = 100000 (fallback only when no clock values given)
- Plays ruthless chess, very fast, few blunders
- Python backend falls back to tal_style_eval if Rust binary missing

### Recent work (session of April 14, 2026):
- Phase C.2 Items 1, 2, 3, 5 completed in one session.
- Item 1 (Aspiration Windows): ±50cp window centered on previous
  depth's score, widen-and-research on fail-low or fail-high,
  full window at depth 1 and after mate scores (|score| > 
  CHECKMATE-1000). Also fixed a pre-existing bug where partial
  iterations (node budget exhausted mid-search) could overwrite
  the last fully-completed depth's result in best_overall.
  Startpos reaches depth 9 at 100k nodes (was 6).
- Item 2 (Check Extension): +1 ply when side to move is in check,
  via `let depth = if in_check { depth + 1 } else { depth };`
  shadowing right after in_check is computed. Ply preserved.
  Interacts cleanly with existing NMP/LMR in_check gates.
  Startpos drops to depth 8 at 100k nodes (extension cost).
- Item 3 (Futility Pruning): At depths 1-2, skip quiet 
  non-promoting non-checking moves when static_eval + margin 
  <= alpha. Margins 100/300 cp. Gated on !in_check, depth <= 2,
  |alpha| < CHECKMATE-1000, |static_eval| < CHECKMATE-1000. 
  Gives-check detection via is_in_check on the new_board. 
  Quiet endgames jumped from depth ~8 to depth ~29 at 100k 
  nodes. Startpos switched from e2e4 to d2d4 at higher depths 
  as positional considerations start to dominate Tal bonuses.
- Item 5 (Time Management, Rust side): parse_go_deadline() in
  main.rs handles go movetime N and go wtime W btime B 
  [winc Wi] [binc Bi] [movestogo N]. Allocation formula:
  base = time/moves_to_go (default 30), allocated = base + inc,
  capped at time/4, minus 50ms safety, minimum 10ms. Deadline
  is Option<Instant> threaded through best_move_nodes, 
  ab_search, and quiescence. time_up() helper checked at the 
  same 5 sites as nodes.get() >= node_limit. Soft deadline 
  check at top of each ID iteration. All pre-existing paths 
  (go nodes, go depth) unchanged.
- Item 5 (Time Management, Python side): wtime_ms and btime_ms
  threaded as optional kwargs through rust_engine.py, model.py,
  suggest.py, and handler.py. suggest.py uses functools.partial
  for run_in_executor kwarg support. Three engine-move sites in
  handler.py (lines 89, 118, 165) pass clock values. Analyzer
  site (line 183) and REST /api/suggest fallback stay 
  node-limited. End-to-end verified: 5-min clock from Python
  test harness allocates 9.95s and reaches depth 12 from 
  startpos. 100ms emergency clock returns a legal move in 11ms.
- Item 4 (Syzygy in Rust) DEFERRED: Python backend already 
  probes tablebases at ≤6 pieces before calling the Rust 
  engine, so Rust-side Syzygy has near-zero impact on the 
  live product. Will revisit only if we need Pyro to be 
  self-contained for UCI tournaments or rating list submission.
- Item 6 (TAL_AGGRESSION tuning) TESTED: Built
  backend/scripts/tune_aggression.py — two-binary A/B match
  harness with python-chess game loop, random opening selection,
  color swaps, full draw detection, and clean subprocess
  shutdown. Ran TAL=1.5 vs TAL=2.0, 40 games at 50k nodes:
  result 53.8% vs 46.2%, directional preference for 1.5 but
  statistically weak (~1.3 sigma). Parameter appears
  insensitive at this strength. Kept default at 1.5.

### Observed strength estimate (measured April 16, 2026):

Gauntlet result at 10s+0.1s time control, 100 games per opponent:

| Opponent | W  | L  | D | Score % | Implied Pyro Elo |
|----------|----|----|---|---------|------------------|
| SF-1500  | 62 | 29 | 9 | 66.5    | ~1619            |
| SF-1700  | 53 | 44 | 3 | 54.5    | ~1731            |
| SF-1900  | 31 | 65 | 4 | 33.0    | ~1775            |
| SF-2100  | 17 | 77 | 6 | 20.0    | ~1859            |

Weighted average: ~1746 Elo (at 10s+0.1s).
CCRL Blitz equivalent (extrapolated): ~1550-1650.
CI ~±70 Elo per matchup.

**Notable: non-linear performance curve.** Pyro underperforms
vs weak opponents and overperforms vs strong ones — confirms
the Tal-style aggressive personality is functioning as intended.
Opponent-strength-dependent:
- vs weak (1500): 66.5% (should be 75%+ if truly 1700)
- vs strong (2100): 20% (a true-1700 engine would score ~10%)

Implication: Pyro is a "scary" engine, not a "technical" engine.
Do not optimize this curve away during Phase G work.

Baseline data archived at:
    backend/scripts/gauntlet/baseline_2026-04-16/

Every future Phase G change should be validated by re-running
the gauntlet and comparing against this baseline.

Target for Phase G complete: +250-400 Elo average (i.e., 
Pyro at ~2000-2150 CCRL Blitz equivalent).

### Why NNUE was abandoned:
- 768→256→1 architecture plateaus at ~86cp RMSE
- PeSTO has 0cp error (it IS the eval)
- Trained on: self-play (0-200), Lichess SF (0-200)
- 130 epochs, 5M positions — still losing all games
- Would need: deeper architecture OR Bullet trainer
  with 100M+ positions in C++/Rust to beat PST

## NNUE v2 Plan (DEFERRED — see Current Goal section)

NOTE (April 15, 2026): NNUE v2 is deferred indefinitely under 
the Phase G strategic shift. NNUE produces precise positional 
play which contradicts the goal of Tal-style tactical violence.
The full plan below is preserved as a reference in case the 
strategic direction changes — do not delete this section, but 
do not work on it either.

### Key research findings:

1. From original Stockfish NNUE docs (nodchip, 2020):
   - Correct architecture: 768 → 256x2 → 32 → 32 → 1
   - We had: 768 → 256x2 → 1 (missing two hidden layers!)
   - Training uses gensfen depth 8, 10M+ positions
   - Lambda=0.5 (50% eval + 50% game result interpolation)
   - Iterative: train → gensfen with new net → retrain
   - halfkp needs 300M positions; k-p (piece,square) needs less

2. From Chess Stack Exchange research (confirmed independently):
   - "Before having at least billions of positions, use simple
     (piece, square) features — no king buckets"
   - "Instead of focusing on training loss, use SPRT tests
     (matches to measure ELO difference) against previous nets"
   - "Many strong engines do not have 32 king buckets"
   - Our 5M positions = 60x too little even for simple features

3. Why our attempts failed:
   - Architecture too shallow (missing 32→32 layers)
   - Data too little (5M vs 10M+ needed minimum)
   - Loss metric wrong (val_loss doesn't predict ELO)
   - Should validate with SPRT games not MSE

### Correct architecture for v2:
   Input:   768 features (piece × square × color)
            NO king buckets — simple (piece, square) only
            Confirmed correct for our data scale
   Layer 1: 256 neurons × 2 perspectives (STM + NSTM)
            = 512 concatenated, same as current
   Layer 2: 32 neurons (CReLU activation)  ← MISSING
   Layer 3: 32 neurons (CReLU activation)  ← MISSING
   Output:  1 scalar (centipawns)
   
   This is the ORIGINAL Stockfish NNUE architecture
   before they added king buckets and larger layers.

### Correct training procedure for v2:

Step 1 — Generate training data properly:
   - Use Rust engine with depth 8 (not nodes 5000)
   - Generate 10M+ positions minimum
   - Use Stockfish gensfen-style: random positions +
     quiet search to avoid tactical noise
   - Save FEN + depth-8 eval + game result
   - Target: 50M positions for good results

Step 2 — Training with correct loss:
   - Loss: MSE(sigmoid(output/600), target)
     where target = lambda * sigmoid(eval/600) + 
                    (1-lambda) * game_result
     lambda = 0.5 (from nodchip's original)
   - Scale: 600cp (not 400) matches Stockfish convention
   - Clamp eval to [-2000, 2000]cp before normalization

Step 3 — Validate with SPRT not val_loss:
   - After each training run, play 200 games
     NNUE v2 vs previous best NNUE
   - PASS: score >= 52% (statistically significant)
   - FAIL: stop, analyze, adjust
   - NEVER enable a network that hasn't passed SPRT

Step 4 — Iterative improvement:
   - Once NNUE v2 beats baseline PST in SPRT:
     generate new training data WITH the new NNUE
     retrain on new data → better network
   - Repeat 3-5 iterations
   - Each iteration should gain 50-100 ELO

### Implementation changes needed for v2:

In backend/scripts/train_nnue_rust.py:
- Add two hidden layers (32→32) to RustNNUE model
- Change loss to: MSE(sigmoid(output/600), target)
  where target = 0.5*sigmoid(eval/600) + 0.5*result
- Learning rate schedule: start 0.001, decay by 0.5
  when val_loss plateaus (like nodchip's newbob_decay)

In engine/src/nnue.rs:
- Add two more layers to Network struct:
  l2_weights: [i16; 32 * 32]
  l2_bias:    [i16; 32]
  l3_weights: [i16; 1 * 32]  
  l3_bias:    i16
- Update forward() to pass through l2 and l3
- Update binary format for new weight file size

In backend/scripts/generate_selfplay_rust.py:
- Add --depth flag (use depth 8 not nodes 5000)
- Add quiet position filter (skip tactical positions)
- Generate 50M positions for v2 training

### What NOT to do (lessons learned):
- Do NOT use halfkp/halfka features (need billions)
- Do NOT measure success by val_loss alone
- Do NOT train on PST self-play (circular, can't improve)
- Do NOT use only 5M positions
- Do NOT train more epochs hoping loss converges
  (architecture capacity is the bottleneck, not epochs)

### Prerequisites before starting NNUE v2:
1. Complete items 1-8 from roadmap (Rust engine improvements)
2. Have 50M+ quality positions generated
3. Rust engine must be strong enough to generate
   useful training data (Tal bonuses help here)
4. Budget ~1 week of compute time for 5+ iterations

### Expected outcome if done correctly:
- RMSE should drop below 40cp (vs 86cp currently)  
- SPRT validation: NNUE beats PST in 200 games
- Estimated ELO gain: +200-400 over PST baseline
- Timeline: 3-5 sessions of serious work

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

---

## Next Session Roadmap (in priority order):

### Quick wins (1-2 sessions):
1. Aspiration windows in Rust engine
   - Currently missing from Rust search
   - Port from Python search.py
   - Narrow alpha-beta window around expected score
   - Reduces nodes searched significantly

2. Tune TAL_AGGRESSION constant
   - Currently TAL_AGGRESSION = 1.5
   - Try 1.2, 1.8, 2.0 and validate which plays best
   - Play 50 games at each setting vs baseline

3. Wire Syzygy tablebases into Rust engine
   - Currently only Python engine uses tablebases
   - Rust engine should probe Syzygy for <=6 pieces
   - Use syzygy crate or implement probe logic

### Medium term (2-3 sessions):
4. Iterative deepening with time management
   - Currently uses fixed node budget (100k nodes)
   - Add proper time control: "go wtime btime"
   - Search deeper when time allows
   - This alone could add 100-200 ELO

5. Check extension
   - When in check, extend search by 1 ply
   - Prevents missing tactical sequences involving checks

6. Futility pruning
   - Skip moves that can't improve alpha at low depths
   - Faster search, more depth at same node budget

### Longer term:
7. NNUE v2 (if returning to neural approach):
   - Need: 768→256x2→32→32→1 architecture
   - Need: depth-8 gensfen-style data generation
   - Need: 50M+ positions
   - Only attempt after items 1-6 are done

8. MCTS (Phase D):
   - Target: 1800+ ELO
   - Only after NNUE v2 succeeds

### Known issues:
- Rust engine NNUE loads but doesn't help (86cp RMSE)
  → Could disable NNUE loading to save startup time
- Premove smoothness (minor UI issue)
- engine/target/ is tracked in git, causing every build to 
  dirty the working tree. Should be in .gitignore. Small 
  chore commit to fix: add target/ and .claude/ to 
  .gitignore, then git rm --cached the already-tracked 
  files. Not urgent.
- hist_score at search.rs:914 is a dead variable (pre-existing
  warning, not introduced this session). Leftover from an 
  earlier draft of the move loop. Harmless.
- On partial iterations where node budget is exhausted 
  mid-search, the last root move searched may receive a 
  near-static-eval result because ab_search returns static 
  eval once the budget trips. This is a pre-existing issue 
  that Item 5 (time management) partially addresses but 
  doesn't fully fix — the cleanest fix is "only commit an 
  iteration to best_overall if iter_completed is true", 
  which we implemented. Edge cases with very constrained 
  time may still exhibit this.

## Start of next session checklist:
1. git pull (get latest)
2. cargo build --release (in engine/)
3. Start backend: uvicorn app.main:app --port 8000
4. Start frontend: npm run dev
5. Confirm: "Rust engine loaded" in uvicorn log
6. Play a game to verify engine works — at move 1 with a 
   5-minute clock, the engine should think for ~10 seconds, 
   not respond instantly. If it responds instantly, time
   management is not reaching the Rust engine — debug 
   suggest_move → rust_engine.py chain.
7. Phase C.2 is complete. Phase D (NNUE v2) and Phase E (MCTS) 
   are DEFERRED. The active track is Phase G — The Mittens Path. 
   See Phase G section in this file for the full plan.

8. The CURRENT GOAL is a scary tactical engine at 2000-2200 CCRL 
   with a Mittens-style personality, NOT 3000 Elo. Treat any 
   impulse to "just go for raw strength" as a temptation to 
   dismiss — the user explicitly chose Phase G over Path A.

9. Next session work: start with G1 (cutechess gauntlet) — this 
   is the prerequisite for measuring everything else in Phase G. 
   Without a real Elo number, none of the strength improvements 
   in G2-G6 are validatable. The G7 + G10 quick wins (crank 
   TAL_AGGRESSION + aggressive opening book) can fit alongside 
   G1 in the same session if time permits.

---

## Phase C.2 — Rust Engine Polish (MOSTLY COMPLETE)

### Goal: reach 1600+ ELO equivalent

### Status: Items 1, 2, 3, 5 complete. Item 4 deferred. 
### Item 6 pending (empirical tuning).

### Item 1: Aspiration Windows ✅ COMPLETE
In engine/src/search.rs, in best_move_nodes():
- After first depth-1 search gives score S,
  search subsequent depths with narrow window:
  alpha = S - ASPIRATION_DELTA (default 50cp)
  beta  = S + ASPIRATION_DELTA
- If search fails low (score <= alpha):
  re-search with alpha = -INF
- If search fails high (score >= beta):
  re-search with beta = +INF
- Reduces nodes searched significantly on stable positions
- Reference: Python search.py already has this

### Item 2: Check Extension ✅ COMPLETE
In engine/src/search.rs, in ab_search():
- When the side to move is IN CHECK:
  extend search by 1 ply (depth += 1)
- Only extend once per line (track with flag)
- Prevents missing tactical sequences involving checks
- Implementation:
  let extension = if in_check { 1 } else { 0 };
  recurse with depth - 1 + extension

### Item 3: Futility Pruning ✅ COMPLETE
In engine/src/search.rs, in ab_search():
- At depth 1 and depth 2, if static eval + margin
  is still below alpha, skip quiet moves entirely
- Margins: depth 1 = 100cp, depth 2 = 300cp
- Never prune when in check
- Never prune when eval indicates zugzwang risk
- Implementation:
  if depth <= 2 && !in_check {
    let margin = depth as i32 * 150;
    if static_eval + margin <= alpha {
      skip quiet moves (search only captures)
    }
  }

### Item 4: Syzygy Tablebases in Rust Engine ⏭️ DEFERRED
- Use the shakmaty-syzygy crate (Rust)
- Probe for positions with <=6 pieces
- Return WDL result immediately (like Python tablebase)
- Tablebase files location:
  backend/data/syzygy/ (~1GB, 290 files)
- Add --syzygy-path flag to UCI engine
- Python backend should pass path at startup

NOTE (April 14, 2026): Deferred because the Python backend 
already probes Syzygy tables at ≤6 pieces before calling the 
Rust engine (see backend/app/engine/model.py:229 and 
tablebase.py). Rust-side Syzygy would only matter if Pyro is 
ever submitted to a UCI rating list or tournament where it 
runs standalone without the Python backend above it. Crate 
choice if revived: pyrrhic-rs (not shakmaty-syzygy) — takes
raw bitboards via an EngineAdapter trait, so no FEN 
serialization or parallel board representation needed.

### Item 5: Time Management ✅ COMPLETE
Replace fixed node budget with proper time control:
- Parse "go wtime <ms> btime <ms>" UCI command
- Allocate time: use_time = total_time / 30
  (simple: assume ~30 moves remaining)
- Search until time expires (use std::time::Instant)
- Fall back to node limit if no time given
- This alone could add 100-200 ELO

### Item 6: TAL_AGGRESSION Tuning ✅ TESTED (result: keep 1.5)
Currently TAL_AGGRESSION = 1.5 in search.rs.

A/B tested on April 15, 2026 via backend/scripts/tune_aggression.py:
- 40 games at 50k nodes/move, seed=42
- TAL=1.5 vs TAL=2.0, alternating colors, randomized openings
- Result: 53.8% vs 46.2% (W18/D7/L15 from TAL=1.5 perspective)
- Approximate +26 Elo for 1.5, 95% CI roughly ±65 Elo
- Verdict: directional preference for 1.5, not statistically
  conclusive at 40 games. Parameter appears relatively
  INSENSITIVE at this strength — doubling the aggression from
  1.5 to 2.0 produced at most a small Elo difference.
- Conclusion: keep TAL_AGGRESSION = 1.5 as default. Further
  tuning of this single parameter is low-ROI. Re-test only if
  engine strength increases substantially (NNUE v2 or deeper
  search) such that eval-function parameters become sensitive
  again.

---

## Phase D — NNUE v2 (DEFERRED — when returning to neural)

### Prerequisites:
- Phase C.2 items 1-6 complete
- Rust engine strong enough to generate quality data
- Budget: ~1 week of compute time

### Architecture (from nodchip's original Stockfish NNUE):
Input:   768 features (piece × square × color)
         NO king buckets — simple (piece, square) only
Layer 1: 256 neurons × 2 perspectives (STM + NSTM)
         = 512 concatenated
Layer 2: 32 neurons (CReLU)   ← MISSING in v1
Layer 3: 32 neurons (CReLU)   ← MISSING in v1
Output:  1 scalar (centipawns)

### Training procedure:
Step 1 — Data generation (50M+ positions):
- Add --depth 8 flag to generate_selfplay_rust.py
- Use quiet position filter (skip tactical noise)
- Generate 50M positions minimum
- Format: FEN + depth-8 eval + game result

Step 2 — Training with correct loss:
Loss = MSE(sigmoid(output/600), target)
where target = 0.5*sigmoid(eval/600) + 0.5*result
(lambda=0.5 from nodchip's original)
Scale: 600cp (not 400) — matches Stockfish convention

Step 3 — Validate with SPRT (not val_loss):
- Play 200 games: new NNUE vs previous best
- PASS if score >= 52%
- FAIL: stop, analyze, adjust
- NEVER judge by val_loss alone

Step 4 — Iterative improvement:
- Once NNUE beats PST in SPRT:
  generate new data WITH the new NNUE
  retrain → better network
- Repeat 3-5 iterations
- Expected gain: +200-400 ELO over PST

### Implementation files to change:
backend/scripts/train_nnue_rust.py:
- Add two hidden layers (32→32) to RustNNUE model
- Change loss to nodchip's lambda formula
- Add newbob_decay learning rate schedule

engine/src/nnue.rs:
- Add l2_weights: [i16; 32 * 32]
- Add l2_bias:    [i16; 32]
- Add l3_weights: [i16; 1 * 32]
- Add l3_bias:    i16
- Update forward() to pass through l2 and l3
- Update binary format for new weight sizes

backend/scripts/generate_selfplay_rust.py:
- Add --depth flag (depth 8 not nodes 5000)
- Add quiet position filter
- Target: 50M positions

### Why v1 failed (do not repeat):
- Architecture too shallow (missing 32→32 layers)
- Data too little (5M vs 50M+ needed)
- Wrong loss metric (val_loss ≠ ELO)
- Trained on PST self-play (circular, can't improve)
- Used only 130 epochs, wrong scale (400 not 600)

---

## Phase E — MCTS (DEFERRED — only relevant if Phase D is revived)

### Goal: 1800+ ELO

### Prerequisites:
- NNUE v2 working and beating PST in SPRT
- Value head producing calibrated win probabilities
- Policy head producing move probabilities

### Architecture:
- Value head: NNUE output → win probability
- Policy head: 768-dim input → 1968-dim move vector
  (all possible from-to square pairs)
- MCTS: 200+ simulations per move
  UCB1 formula: Q(s,a) + C * P(s,a) / (1 + N(s,a))

### Implementation plan:
1. Add policy head to NNUE architecture
2. Generate policy targets from engine's best moves
3. Train jointly: value loss + policy loss
4. Implement MCTS in Rust:
   engine/src/mcts.rs
   - Tree node: visits, value, policy prior, children
   - Selection: UCB1
   - Expansion: generate moves + policy priors
   - Simulation: NNUE value head (no random rollout)
   - Backprop: update Q values up the tree
5. UCI integration: replace ab_search with mcts_search
   when --mcts flag is passed

---

## Phase G — The Mittens Path (ACTIVE)

Goal: Build a scary tactical chess engine with personality. 
Three parallel tracks: strength, style, UX. Mittens itself 
(Stockfish under the hood + sandbagging + taunts + creepy avatar) 
is the spiritual reference, but Pyro will be honestly aggressive 
rather than sandbagging — the style IS the strength.

### Track 1: Strength improvements (target +250-500 Elo)

These get Pyro from ~1750 to ~2000-2300 CCRL without touching 
NNUE. Ordered by ROI per hour:

G1. Cutechess gauntlet harness ✅ COMPLETE (April 16, 2026)
    - Install cutechess-cli (or build from source)
    - Wrap Pyro + 2-3 reference engines (TSCP ~1700, 
      Fairy-Max ~2000, Sungorus ~2200)
    - Script: 200 games per opponent at 10s+0.1s time control
    - Output: Pyro's actual CCRL-equivalent rating
    - WITHOUT THIS: every change below is unmeasurable.
      Skip at your peril.

    STATUS: Baseline measured April 16, 2026.
    Pyro scored 53.5% aggregate across 400 games vs SF-1500/1700/1900/2100.
    Implied Pyro Elo at 10+0.1 TC: ~1746.
    Full result at backend/scripts/gauntlet/baseline_2026-04-16/RESULT.md.
    Use this baseline to validate every future Phase G change.

G2. Lazy SMP multithreading (1-2 sessions, +50-150 Elo)
    - Currently single-threaded — major Elo left on the table
    - Standard approach: N threads share the TT, each runs an 
      independent search at slightly different depths
    - Implementation: spawn threads in best_move_nodes, each 
      calls ab_search with a shared Arc<TTable>
    - Most modern engines do this. Free Elo from existing 
      hardware.

G3. Principal Variation Search (PVS) (1 session, +30-60 Elo)
    - Refactor of ab_search: first move searched with full 
      window, subsequent moves with null window, re-search 
      only on fail-high
    - Synergizes with aspiration windows already in place

G4. Better move ordering (1-2 sessions, +50-100 Elo)
    - SEE (Static Exchange Evaluation) for capture ordering — 
      replace MVV-LVA's naive sorting with actual exchange math
    - Counter-move heuristic: if opponent played X, the move 
      that often refutes X gets ordered higher
    - Continuation history: history scores per (prev_move, 
      curr_move) pair instead of just curr_move

G5. Singular extensions (1 session, +30-60 Elo)
    - When a TT move is much better than alternatives at 
      reduced depth, extend its search by 1 ply
    - Particularly powerful for forcing tactical sequences — 
      synergizes with the Tal aggression bias

G6. SPSA tuning of all eval parameters (1 session setup + 
    overnight runs, +50-100 Elo)
    - Currently every magic number in tal_bonuses (king attack 
      weight, pawn storm, early queen penalty, etc.) is guessed
    - SPSA: Simultaneous Perturbation Stochastic Approximation, 
      standard for engine eval tuning
    - Use cutechess gauntlet from G1 as the fitness function
    - Tune toward AGGRESSION (weight king attack heavily) — 
      this is where strength and style merge

### Track 2: Style improvements (intentional Tal-bias)

Some of these REDUCE pure-Elo strength but increase the 
"scary tactical" feel. That's the trade.

G7. Crank TAL_AGGRESSION to 2.5+ (5 minutes)
    - Previous A/B test (40 games at 1.5 vs 2.0) was 
      inconclusive (~26 Elo for 1.5, CI ±65)
    - For a personality engine, gameplay style trumps marginal 
      Elo. Bump to 2.5 and let style win.
    - May slightly weaken the engine. Acceptable.

G8. Killer-instinct bonus (1 session)
    - When opponent's king is exposed (few defenders, open 
      files within 2 squares, missing castling rights), 
      MULTIPLY king-attack scores by 1.5-2x
    - Currently Tal bonuses fire constantly — we want them 
      to SPIKE when blood is in the water
    - Implementation in evaluate.rs: detect "king exposure" 
      metric, scale king_attack term

G9. Sacrifice-seeking in search (1 session)
    - Add a "speculation bonus" to move ordering that 
      slightly prefers SEE-negative captures (sacrifices)
    - Currently SEE-negative captures get pruned or deferred 
      — they should be EXPLORED in attacking positions
    - Gate on: opponent king exposed, attacking material 
      present near opponent king
    - This is the difference between a positional engine 
      and a Tal-style killer

G10. Aggressive opening book (1 session)
    - Replace the current Lichess opening data with a curated 
      "scary openings only" book
    - Whitelist: King's Gambit (C30-C39), Smith-Morra Gambit 
      (B21), Latvian Gambit (C40), Albin Counter-Gambit 
      (D08-D09), Vienna Game (C25-C29), Evans Gambit (C51-C52), 
      Danish Gambit (C21), Scotch Gambit, Halloween Gambit
    - Pyro announces its intent on move 1
    - Implementation: filter the existing openings.ts entries 
      OR build a new sharp-only book

G11. Anti-quiet penalty (1 session)
    - Add small eval penalty for closed pawn structures and 
      low piece mobility
    - Pushes Pyro to OPEN positions even when not strictly 
      best
    - Cost: 20-50 Elo. Worth it for style.

### Track 3: UX / Personality (where Mittens magic actually lives)

These don't affect engine strength at all but transform the 
experience of playing against Pyro.

G12. Persona (1 session)
    - Avatar: a flame icon, or a small flame animation (SVG 
      or CSS), placed where chess.com bots have their portrait
    - Tagline displayed near the avatar: 
      "Pyro — burns brightest when you're losing"
    - Color scheme leans into orange/red accents instead of 
      current purple

G13. Taunting messages (1-2 sessions)
    - After certain game events, Pyro speaks via a small 
      chat bubble or message panel
    - Triggers and example lines:
      * After Pyro plays a brilliant move (eval swing > 200cp): 
        "Did you see that coming?"
      * After human blunder (cp_loss > 200): 
        "I was hoping you'd play that."
      * Approaching mate (mate score detected): 
        "Three moves." (or "Two." "One.")
      * Game start: "Try not to disappoint me."
      * Pyro losing material (eval drops > 300cp): 
        *silence* — never acknowledge weakness
      * Game over (Pyro wins): 
        "Better luck next time. (No, really.)"
      * Game over (Pyro loses): 
        "You earned that one. Once."
    - Implementation: backend detects events, sends 
      {"type": "pyro_says", "text": "..."} via WebSocket, 
      frontend displays in a side panel or modal
    - Vocabulary scales with difficulty level (Beginner = 
      gentler, Master = ruthless)

G14. Theatrical timing (1 session)
    - When Pyro finds a brilliant move (mate score, large 
      eval swing, sacrifice), PAUSE before playing even if 
      search finished instantly
    - When refuting a blunder, play FAST to telegraph 
      confidence
    - Implementation: backend computes "drama score" per 
      move, applies artificial delay before sending the move 
      to the frontend

G15. Visual cues during attacks (1-2 sessions)
    - When Pyro's king-attack score is high, dim the board 
      edges or pulse them red
    - Eval bar gets a flame icon when Pyro is winning by > 200cp
    - Optionally: highlight Pyro's attacking pieces with a 
      subtle red glow
    - Pure CSS / Tailwind work in the frontend

G16. Difficulty rebrand (5 minutes)
    - Current: Beginner / Intermediate / Advanced / Expert / Master
    - New names: Sleeping / Playful / Awake / Hunting / Feral
    - Each level gets different avatar mood (sleeping = closed 
      flame icon, feral = wild flame)
    - Same time budgets, just different framing
    - Each level uses different taunt vocabulary

G17. Game-over screens (1 session)
    - On player loss: dramatic dim transition, slow text reveal 
      of Pyro's victory message
    - On player win: grudging acknowledgment with subtle UI 
      downgrade (Pyro avatar dims)
    - On draw: Pyro is annoyed ("Acceptable. Barely.")

### Recommended session ordering

Sessions 1-2 (foundation):
- G1: Cutechess gauntlet (mandatory baseline measurement)
- G7: Crank TAL_AGGRESSION to 2.5 + G10: aggressive opening book
  (immediate style shift, low-effort wins)

Sessions 3-5 (strength + style alternating):
- G2: Lazy SMP (biggest single-session strength win)
- G8: Killer-instinct bonus
- G12 + G16: Persona + difficulty rebrand
- G3: PVS

Sessions 6-8 (depth + theater):
- G4: SEE + counter-move + continuation history
- G13: Taunting messages
- G14: Theatrical timing
- G9: Sacrifice-seeking

Sessions 9-12 (polish + tune):
- G15: Visual cues during attacks
- G17: Game-over screens
- G6: SPSA tuning (run overnight, multiple iterations)
- G5: Singular extensions
- G11: Anti-quiet penalty (only if everything else feels 
  not-aggressive-enough)

Final session: ship it. Deploy, write a README, tweet about it 
(if so inclined), call Phase G complete.

Estimated total: 12-15 sessions of ~1 hour each, 
~3-4 months at 2-3 sessions/week.

### Success criteria for Phase G

- Cutechess gauntlet shows Pyro at 2000+ CCRL
- Playing against Master-difficulty Pyro feels SCARY 
  (specifically: tactical surprises, sacrifices, fast mating 
  attacks)
- Pyro has a recognizable visual identity and voice
- At least 3 friends/test users can describe Pyro's 
  "personality" in their own words after one game

---

## Phase F — Product Polish (whenever)

### Difficulty levels:
- Beginner (nodes=500, depth 2): ~600 ELO
- Intermediate (nodes=5000, depth 4): ~1000 ELO  
- Advanced (nodes=50000, depth 6): ~1400 ELO
- Expert (nodes=100000, depth 7): ~1600 ELO
- Master (current full strength): ~1800+ ELO

### Opening explorer UI:
- ECO code detection (A00-E99)
- Show opening name during game
- Transposition detection
- Line explorer (click to see variations)

### Personality modes (Mittens-inspired):
- Tal Mode: TAL_AGGRESSION=2.5, sacrifices material
- Petrosian Mode: avoids trades, suffocates slowly
- Fischer Mode: precise technique, converts advantages
- Beginner Trap: appears weak, punishes mistakes

### Deployment:
- Docker container (FastAPI + Rust binary)
- Frontend on Vercel/Netlify
- Backend on Railway/Fly.io
- Rate limiting per IP
- Game history persistence (PostgreSQL)

---

## Engine Strength Estimates (ELO equivalents):

Phase A complete:   ~1200-1400 ELO (Python Tal)
Phase B complete:   ~1400-1600 ELO (Rust PST+Tal+TT)
Phase C.2 complete: ~1700-1850 ELO (+ aspiration/pruning/time mgmt)
Phase G strength:   ~2000-2300 ELO (+ SMP, PVS, SEE, tuned eval)
Phase D (DEFERRED): ~2200-2600 ELO (+ NNUE v2 if ever revived)
Phase E (DEFERRED): ~2400-2800 ELO (+ MCTS if ever revived)

Note: 3000+ Elo is NOT a current goal. See "Current Goal" section 
at top of file.
