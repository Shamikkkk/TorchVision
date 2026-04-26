# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

For development history, completed phases, and deferred plans see [HISTORY.md](HISTORY.md).

---

## Current Goal (set April 15, 2026)

Make Pyro a **scary tactical chess engine with a Mittens-style 
personality** — not a silent strength-maxxing engine.

Target: **3000+ CCRL strength** with Pyro's personality intact.
Phase G (personality + search improvements) is COMPLETE at ~1835 Elo.
Phase D (NNUE) is now the active development track — the path 
from 1835 to 3000+ requires neural network evaluation that hand-
crafted eval cannot match. Personality (Tal aggression, taunts, 
UI) survives NNUE via training data bias + post-NNUE Tal modifier.

Strategic implications:
- **Phase G (The Mittens Path) is COMPLETE.** Engine at ~1835 Elo
  with full personality, Obsidian Ember UI, and zero crashes.
- **Phase D (NNUE v2) is now ACTIVE.** The path to 3000+ requires
  NNUE. Hand-crafted eval has a ceiling around 2200-2400.
- **Personality survives NNUE** via: training data biased toward 
  tactical positions, post-NNUE Tal bonus modifier, 31-GM tactical
  opening book, and the full UX/taunts/visual layer.
- **Phase E (MCTS) remains DEFERRED** until NNUE is working.
- **Deployment runs in parallel** with NNUE data generation.

---

## Current State (as of April 26, 2026)
**Phase A (Python classical engine) — COMPLETE ✅**
**Phase B (Rust engine + Tal bonuses) — COMPLETE ✅**
**Phase C (NNUE) — ABANDONED ❌**
**Phase C.2 (Rust engine polish) — COMPLETE ✅**
**Phase D (NNUE v2) — ACTIVE 🔥**
**Phase E (MCTS) — DEFERRED 🛑**
**Phase G (The Mittens Path) — COMPLETE ✅**
**Phase G — COMPLETE ✅ at ~1835 Elo (measured Apr 26)**
All strength items done: G1-G5, G7-G8v2, countermove, NMP-depth, LMP, IID.
SPSA 200 iterations: defaults confirmed near-optimal (no changes needed).
UI overhaul complete (all 5 phases, Obsidian Ember). Deployment configs ready.
Phase D (NNUE) is now the active track — see Phase D section below.
**Game Analyzer — COMPLETE ✅**
**Frontend: difficulty levels + opening name — COMPLETE ✅**

### What's working right now:
- Rust engine live via UCI subprocess with full time management
- TAL_AGGRESSION = 2.5 (cranked April 18 for personality)
- Tal-style bonuses in Rust evaluate()
- PeSTO PST tapered evaluation
- NMP + LMR + killers + quiescence
- Transposition table (Zobrist hashing, 1M entries)
- History heuristic (gravity formula, malus for searched quiets)
- SEE (Static Exchange Evaluation) — captures scored by full
  exchange simulation; SEE-negative captures deprioritized below
  killers in move ordering and pruned entirely in quiescence search.
  Gains +1 search depth at same node budget (depth 9 → 10 at 100k).
- Fool's Mate fix (quiescence checkmate before stand-pat)
- Check extension ply cap — hard cap at ply >= 2*MAX_DEPTH prevents
  stack overflow from perpetual-check infinite recursion. Extension
  guard also stops new extensions after ply >= MAX_DEPTH.
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
- Frontend: 🔥 Pyro persona on engine's player row, tagline,
  orange flame header, "You vs 🔥 Pyro" subtitle
- Difficulty levels renamed: Sleeping / Playful / Awake / Hunting / Feral
- PVS (Principal Variation Search) — move 0 gets full window,
  subsequent moves get null window with re-search on fail-high
- Singular extensions — TT move extended +1 ply when no
  alternative reaches within 50cp at half depth (depth >= 6)
- Opening book cache — 31 GM PGN files parsed once, cached as
  pickle, subsequent startups instant
- Game-over modal — dramatic dark overlay with Pyro's taunt,
  fade-in animation, fire-themed rematch button
- Countermove heuristic — tracks refuting move per [side][prev_to_sq],
  priority 4500 in move ordering (between killers and history)
- Depth-dependent NMP — R = base_r + depth/6 (R=3 at depth 6-11)
- Late Move Pruning (LMP) — skip quiet non-killer non-checking moves
  beyond 3+depth² at depth ≤ 3
- Internal Iterative Deepening (IID) — depth-2 shallow search when
  no TT move at depth ≥ 4, seeds move ordering
- 10 UCI-tunable parameters via AtomicI32 statics (TAL_AGGRESSION,
  futility margins, aspiration delta, NMP reduction, LMR move index,
  singular ext margin, queen attack weight, castling bonus, early
  queen penalty)
- SPSA tuning driver (backend/scripts/spsa_tune.py) — automated
  parameter optimization via cutechess-cli perturbation matches
- Incremental NNUE accumulator — threaded through entire search
  stack (ab_search + quiescence). acc_update() mirrors make_move
  for all move types (quiet, capture, en passant, promotion,
  castling). Zero from_board() rebuilds during search — only at
  root. Ready for trained weights.

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

Implication: Pyro is a "scary" engine, not a "technical" engine.
Do not optimize this curve away during Phase G work.

Baseline data archived at: backend/scripts/gauntlet/baseline_2026-04-16/

Post-PVS gauntlet (April 19, 2026, G8 reverted):
vs SF-1700: 53.5% (51W/44L/5D) — flat vs baseline
vs SF-1900: 38.0% (37W/61L/2D) — up from 33.0% (+35 Elo)
Implied Pyro Elo: ~1770 (was ~1746, +24 Elo gain).
G8 killer-instinct caused -95 Elo regression and was reverted.

Post-SEE gauntlet (April 25, 2026, ply-cap fix applied):
vs SF-1700: 63.0% (61W/35L/4D) — +92 Elo, LOS 99.6%
vs SF-1900: 39.0% (37W/59L/4D) — up from 33.0%
Implied Pyro Elo: ~1808

Post-G8v2+CM gauntlet (April 26, 2026):
vs SF-1700: 67.0% (65W/31L/4D) — +123 Elo, LOS 100%
vs SF-1900: 42.5% (41W/56L/3D) — -53 Elo
Implied Pyro Elo: ~1835 (best ever, +89 over baseline)
Zero disconnects. Non-linear curve narrowing (gap 44→24 Elo).

Target for Phase G complete: +250-400 Elo average (i.e., 
Pyro at ~2000-2150 CCRL Blitz equivalent).

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
- **PeSTO** tapered PST evaluation + **Tal bonuses** (2.5x aggression)
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
  eval once the budget trips. Cleanest fix: "only commit an 
  iteration to best_overall if iter_completed is true" — 
  already implemented. Edge cases with very constrained time 
  may still exhibit this.

## Start of next session checklist:
1. git pull
2. cargo build --release (in engine/)
3. Start backend: uvicorn app.main:app --port 8000
4. Start frontend: npm run dev
5. Confirm "Rust engine loaded" in uvicorn log
6. Play a test game — Pyro should show 🔥 persona, mood
   selector, and opening name. At Feral difficulty, engine
   thinks ~10s per move on a 5-min clock.
7. Phase G COMPLETE at ~1835 Elo. UI overhaul done.
   Phase D (NNUE v2) is now active. Next steps:
   - Deploy current engine (Docker + Vercel/Railway)
   - Set up Bullet trainer
   - Generate 100M positions at depth 8
   - Train first NNUE, validate with SPRT
8. For historical context on completed work, see HISTORY.md.

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
    Baseline: ~1746 Elo at 10+0.1 TC.
    Full result at backend/scripts/gauntlet/baseline_2026-04-16/RESULT.md.
    Use this baseline to validate every future Phase G change.

G2. Lazy SMP multithreading (2 sessions, +50-150 Elo)
    Session 1 of 2 ✅ COMPLETE (April 16, 2026)

    Session 1: TTable now thread-safe (Vec<TTSlot> with paired AtomicU64s,
    XOR-checksum torn-entry detection, &self methods), node counter is
    AtomicU64, stop flag (AtomicBool) plumbed through ab_search/quiescence.
    Engine still single-threaded, plays identically to before.
    Session 2: wrap TTable in Arc, spawn N worker threads, add UCI Threads
    option, re-run gauntlet for validation.

    Expected impact: +50-150 Elo on 4-8 core hardware.
    Validation plan: 100-game gauntlet vs SF-1700 and SF-1900 with Threads=4.

G3. Principal Variation Search ✅ COMPLETE
    - Refactor ab_search: first move searched with full window, subsequent
      moves with null window, re-search only on fail-high
    - Synergizes with aspiration windows already in place

G4. SEE (Static Exchange Evaluation) ✅ COMPLETE (April 25, 2026)
    Full exchange simulation (see() + least_valuable_attacker() + 
    attackers_to()). Wired into score_move (losing capture ordering)
    and quiescence (SEE-negative prune). +1 depth at same node budget.
    Disconnects in initial gauntlet were caused by check extension
    stack overflow (ply cap fix), not SEE itself.

G5. Singular extensions ✅ COMPLETE
    - When a TT move is much better than alternatives at reduced depth,
      extend its search by 1 ply
    - Particularly powerful for forcing tactical sequences

**Bug fix: Check extension stack overflow (April 25, 2026)**
    Unbounded check extension caused infinite recursion in perpetual-
    check positions → stack overflow → process crash. Fixed with two
    guards: hard ply cap (ply >= 2*MAX_DEPTH → drop to qsearch) and
    extension guard (no new extensions after ply >= MAX_DEPTH). This
    bug existed since Phase C.2 and was the real cause of all gauntlet
    disconnects (25-42% crash rate), not SEE.

**Countermove heuristic ✅ COMPLETE (April 26, 2026)**
    Tracks refuting move per [side][prev_move_to_sq]. Priority 4500.

**Depth-dependent NMP ✅ COMPLETE (April 26, 2026)**
    R = base_r + depth/6. R=3 at depth 6-11, R=4 at depth 12+.

**Late Move Pruning (LMP) ✅ COMPLETE (April 26, 2026)**
    Skip quiet non-killer non-checking moves beyond 3+depth² at depth ≤ 3.

**Internal Iterative Deepening (IID) ✅ COMPLETE (April 26, 2026)**
    Depth-2 shallow search when no TT move at depth ≥ 4.

G6. SPSA tuning ✅ COMPLETE (April 26, 2026)
    Session 1: 10 params made UCI-tunable via AtomicI32 statics.
    Session 2: SPSA driver script written (spsa_tune.py).
    200 iterations completed: all parameters converged within ±0.5
    of hand-tuned defaults. Conclusion: defaults are near-optimal.
    No changes applied. Results in backend/scripts/spsa_results.json.

### Track 2: Style improvements (intentional Tal-bias)

Some of these REDUCE pure-Elo strength but increase the 
"scary tactical" feel. That's the trade.

G7. Crank TAL_AGGRESSION to 2.5 ✅ COMPLETE (April 18, 2026)
    Source changed in engine/src/search.rs. Rebuild after current gauntlet finishes.

G8. King-exposure bonus — v1 ❌ REVERTED, v2 ✅ COMPLETE (Apr 26)
    v2: capped additive (max 50cp, AND-gated shield + attackers)

G9. Sacrifice-seeking in search (1 session)
    - Add "speculation bonus" to move ordering that slightly prefers SEE-negative captures
    - Gate on: opponent king exposed, attacking material present near opponent king

G10. Aggressive opening book ✅ COMPLETE (31 GMs, tactical double-weighted)
    - Whitelist: King's Gambit, Smith-Morra, Latvian Gambit, Albin Counter-Gambit,
      Vienna Game, Evans Gambit, Danish Gambit, Scotch Gambit, Halloween Gambit
    - Filter existing openings.ts OR build a new sharp-only book

G11. Anti-quiet penalty (1 session)
    - Small eval penalty for closed pawn structures and low piece mobility
    - Cost: 20-50 Elo. Worth it for style.

### Track 3: UX / Personality (where Mittens magic actually lives)

G12. Persona ✅ COMPLETE (April 18, 2026)
    - 🔥 PYRO label + tagline "burns brightest when you're losing" on engine's player row
    - Orange flame header: 🔥 PYRO CHESS
    - "You vs 🔥 Pyro" subtitle
    - Engine clock labeled "Pyro"

G13. Taunting messages (1-2 sessions)
    - After certain game events, Pyro speaks via a chat bubble or message panel
    - Triggers: brilliant move (eval swing >200cp), human blunder (cp_loss >200),
      approaching mate, game start, game over
    - Implementation: backend detects events, sends {"type": "pyro_says", "text": "..."}
      via WebSocket, frontend displays in side panel
    - Vocabulary scales with difficulty level

G14. Theatrical timing (1 session)
    - PAUSE before brilliant moves even if search finished instantly
    - Play FAST when refuting a blunder
    - Backend computes "drama score" per move, applies artificial delay

G15. Visual cues during attacks (1-2 sessions)
    - When king-attack score is high: dim board edges or pulse them red
    - Eval bar gets flame icon when Pyro is winning by >200cp
    - Pure CSS / Tailwind frontend work

G16. Difficulty rebrand ✅ COMPLETE (April 18, 2026)
    - Sleeping / Playful / Awake / Hunting / Feral
    - Label updated in frontend/src/components/Controls.tsx
    - Section header renamed to "Pyro's Mood"

G17. Game-over screens ✅ COMPLETE
    - Player loss: dramatic dim transition, slow text reveal of victory message
    - Player win: grudging acknowledgment, Pyro avatar dims
    - Draw: Pyro is annoyed ("Acceptable. Barely.")

### Phase G — remaining priorities:

Phase G is COMPLETE. All items either done or consciously deferred:
- G9 (sacrifice-seeking): DEFERRED — personality already strong enough
- G11 (anti-quiet): DEFERRED — would cost Elo for marginal style gain
- G14 (theatrical timing): SKIPPED by user preference
- Deployment: configs ready (Netlify + Railway), deploy when ready

Active development has moved to Phase D (NNUE).

---

## Phase D — NNUE v2 (ACTIVE)

### Goal: Pyro at 3000+ CCRL with personality intact

Hand-crafted eval (PeSTO + Tal bonuses) has a ceiling around 
2200-2400 Elo. To reach 3000+, NNUE is required — it replaces
the eval function with a neural network that learns positional 
understanding beyond what humans can hand-code.

### Why v1 failed (do not repeat):
- Architecture too shallow: 768→256→1 (missing hidden layers)
- Data too little: 5M positions (need 100M+ minimum)
- Data too circular: trained on PST self-play (can't improve)
- Wrong trainer: homebrew PyTorch (use Bullet instead)
- Wrong validation: measured val_loss (use SPRT game results)
- Wrong scale factor: 400cp (use 600cp to match convention)

### Phase D1: First working NNUE (target: 2200 Elo)
**Timeline: 2-3 weeks**

Architecture: (768→256)×2→1
- 768 inputs: piece × square × color
- 256 neurons × 2 perspectives (STM + NSTM) = 512 concatenated  
- 1 output: centipawns (or WDL probability)
- Activation: CReLU
- NO king buckets — simple (piece, square) features only
- This is the standard starter NNUE architecture

Trainer: **Bullet** (https://github.com/jw1912/bullet)
- Rust-based, purpose-built for NNUE training
- Best-in-class performance, used by most top engines
- Handles data loading, quantization, training loop
- Replaces our homebrew train_nnue_rust.py

Data generation: 100M positions minimum
- Modify generate_selfplay_rust.py for depth-8 search
- Bullet-compatible output format (.bin or .binpack)
- Quiet position filter (skip positions where best move is a capture)
- Save: FEN + depth-8 eval + game result (W/D/L)
- Estimated time: 3-4 days at 4 threads

Training procedure:
- Loss: MSE(sigmoid(output/400), target)
  where target = lambda * sigmoid(eval/400) + (1-lambda) * wdl
  lambda = 0.5 (blend eval with game result)
- Learning rate: start 0.001, decay on plateau (newbob)
- Epochs: 30-50 on 100M positions
- Estimated time: 8-12 hours CPU, 1-2 hours GPU

Validation: SPRT (200 games)
- NNUE vs PeSTO+Tal baseline
- PASS: score >= 52% (statistically significant)
- FAIL: iterate on data quality, not architecture
- NEVER judge by val_loss alone

Rust engine changes (engine/src/nnue.rs):
- Clean up existing 768→256→1 inference code
- Quantized i16 weights for accumulator, i8 for output layer
- Incremental accumulator updates (add/remove feature on make_move)
- SIMD vectorization (AVX2) for inner products

Success criteria: NNUE beats PeSTO in SPRT → pipeline works.
Expected Elo: ~2000-2200

### Phase D1 progress (as of April 27, 2026):
- [x] Data generator fixed (depth 6, --no-nnue, quiet filter,
      pipe format, --target flag, progress reporting)
- [x] 20M position generation launched (4 processes, ETA ~Apr 30)
- [x] Incremental accumulator (acc_update, threaded through
      full search stack, 0 from_board rebuilds during search)
- [x] SCALE updated 400→600 in nnue.rs
- [x] Trainer fixed (WDL sigmoid loss, pipe format parser,
      cosine LR, gradient clip, CUDA verified on RTX 3050)
- [ ] Train on 20M positions (~1-2 hours on GPU)
- [ ] Export to pyro.nnue
- [ ] SPRT validation: 200 games NNUE vs PeSTO baseline

Next session: wait for data gen to complete, then train + validate.

### Phase D2: Scale up (target: 2600-2800 Elo)
**Timeline: 3-4 weeks**

Architecture: (768×8kb→512)×2→1
- 8 king buckets (king position bins the input features)
- 512-neuron accumulator (double the D1 size)
- Horizontal mirroring (reduce feature space by half)
- SCReLU activation (Squared Clipped ReLU — better gradient flow)

Data: 500M-1B positions
- Each iteration generates 100M NEW positions using current best NNUE
- Retrain on accumulated data
- 3-5 iterations of generate → train → validate
- Each iteration should gain 50-100 Elo

SIMD optimization:
- AVX2 vectorized accumulator updates
- i16 weights for accumulator layer
- i8 weights for output layers
- Quantization-aware training in Bullet

Advanced search tuning:
- NNUE eval is smoother than HCE → more aggressive pruning
- Re-tune futility margins, LMR thresholds, NMP reduction
- NNUE makes the engine "see" positional features that HCE missed
  → search prunes bad lines earlier → effectively deeper search

Expected Elo: ~2600-2800

### Phase D3: Competitive strength (target: 3000+ Elo)
**Timeline: 4-6 weeks**

Architecture: (768×16hm→1024)×2→1 or larger
- 16 king buckets with horizontal mirroring
- 1024-neuron accumulator
- Output buckets (different weights based on piece count)
- WDL output head (win/draw/loss probabilities, not just centipawns)

Data: 1B+ positions
- Supplemented with rescored Leela data (publicly available)
- Aggressive deduplication to prevent overfitting

Training refinements:
- Multi-stage training: large LR on big data, fine-tune with small LR
- Curriculum learning: start with simple positions, add complex ones
- Distillation: optionally train on Stockfish evals for initial net

Personality preservation:
- Training data bias: weight tactical positions 2x (King's Gambit,
  sacrifices, king hunts, open positions)
- Post-NNUE Tal modifier: final_eval = nnue_eval + tal_bonus * 0.3
  (small additive push toward aggression)
- Opening book: 31-GM tactical book unchanged
- All UX/personality features unchanged

Expected Elo: 3000-3200

### Phase D4: Polish and iterate (target: 3200+ Elo)
**Timeline: ongoing**

- Larger networks if compute allows
- More training data iterations
- Search-eval co-optimization
- Potentially MCTS hybrid for endgame (Phase E)

### Compute requirements:

| Phase | Positions | Gen time (4 threads) | Train (CPU) | Train (GPU) |
|-------|-----------|---------------------|-------------|-------------|
| D1    | 100M      | 3-4 days            | 8-12 hours  | 1-2 hours   |
| D2    | 500M-1B   | 2-3 weeks           | 2-3 days    | 6-12 hours  |
| D3    | 1B+       | 4-6 weeks           | impractical | 1-2 days    |

GPU strongly recommended for D2+. Bullet supports CUDA.
RTX 3060 or better cuts training time by 10-20x.

### Implementation files:

Data generation:
  backend/scripts/generate_selfplay_rust.py
  - Add --depth 8 flag
  - Add --format bullet flag (Bullet-compatible .bin output)
  - Add quiet position filter
  - Target: 100M positions for D1

Training:
  Use Bullet directly (clone as submodule or external tool)
  - Configure network architecture in Bullet's TOML/config
  - Point at generated .bin data
  - Output: quantized .nnue weight file

Rust inference:
  engine/src/nnue.rs
  - Already has 768→256→1 structure (from v1, needs cleanup)
  - Add incremental accumulator updates
  - Add AVX2 SIMD for dot products
  - Add binary weight loading (Bullet's output format)
  - Wire into evaluate(): if NNUE loaded, use nnue_eval + tal_modifier

Validation:
  backend/scripts/validate_nnue_rust.py
  - Already exists, needs minor updates
  - 200 games, NNUE vs PeSTO baseline
  - Report win/draw/loss and SPRT result

---

## Phase F — Product Polish (whenever)

### Difficulty levels:
- Beginner/Sleeping (nodes=500, depth 2): ~600 ELO
- Intermediate/Playful (nodes=5000, depth 4): ~1000 ELO  
- Advanced/Awake (nodes=50000, depth 6): ~1400 ELO
- Expert/Hunting (nodes=100000, depth 7): ~1600 ELO
- Master/Feral (current full strength): ~1800+ ELO

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
Phase G complete:   ~1835 ELO (measured Apr 26, personality engine)
Phase D1 target:    ~2000-2200 ELO (+ first working NNUE)
Phase D2 target:    ~2600-2800 ELO (+ scaled NNUE, king buckets)
Phase D3 target:    ~3000-3200 ELO (+ large NNUE, WDL, 1B+ data)
Phase D4 target:    ~3200+ ELO (+ iteration, larger nets)
Phase E (DEFERRED): ~3400+ ELO (+ MCTS hybrid)
