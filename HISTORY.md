# Pyro Chess Engine — Development History

This file contains completed phase details, session notes, and deferred plans. For current state and active roadmap, see CLAUDE.md.

---

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

---

### Why NNUE was abandoned:
- 768→256→1 architecture plateaus at ~86cp RMSE
- PeSTO has 0cp error (it IS the eval)
- Trained on: self-play (0-200), Lichess SF (0-200)
- 130 epochs, 5M positions — still losing all games
- Would need: deeper architecture OR Bullet trainer
  with 100M+ positions in C++/Rust to beat PST

---

## NNUE v2 Plan (DEFERRED — see Current Goal section in CLAUDE.md)

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
1. Complete Phase G items (Rust engine improvements)
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

## Phase C.2 — Rust Engine Polish (COMPLETE)

### Goal: reach 1600+ ELO equivalent

### Status: Items 1, 2, 3, 5 complete. Item 4 deferred. Item 6 tested (keep 1.5).

### Item 1: Aspiration Windows ✅ COMPLETE
In engine/src/search.rs, in best_move_nodes():
- After first depth-1 search gives score S,
  search subsequent depths with narrow window:
  alpha = S - ASPIRATION_DELTA (default 50cp)
  beta  = S + ASPIRATION_DELTA
- If search fails low (score <= alpha): re-search with alpha = -INF
- If search fails high (score >= beta): re-search with beta = +INF
- Reduces nodes searched significantly on stable positions

### Item 2: Check Extension ✅ COMPLETE
In engine/src/search.rs, in ab_search():
- When the side to move is IN CHECK: extend search by 1 ply (depth += 1)
- Implementation: `let depth = if in_check { depth + 1 } else { depth };`

### Item 3: Futility Pruning ✅ COMPLETE
In engine/src/search.rs, in ab_search():
- At depth 1 and depth 2, skip quiet moves when static_eval + margin <= alpha
- Margins: depth 1 = 100cp, depth 2 = 300cp
- Never prune when in check

### Item 4: Syzygy Tablebases in Rust Engine ⏭️ DEFERRED
NOTE: Deferred because the Python backend already probes Syzygy tables at ≤6 pieces
before calling the Rust engine (see backend/app/engine/model.py:229 and tablebase.py).
Rust-side Syzygy would only matter if Pyro is submitted to a UCI rating list or 
tournament. Crate choice if revived: pyrrhic-rs (not shakmaty-syzygy).

### Item 5: Time Management ✅ COMPLETE
- Parse "go wtime <ms> btime <ms>" UCI command
- Allocation: base = time/30, allocated = base + inc, capped at time/4, min 10ms
- Deadline (Option<Instant>) threaded through best_move_nodes, ab_search, quiescence
- Python side: wtime_ms/btime_ms threaded through rust_engine.py → model.py → suggest.py → handler.py

### Item 6: TAL_AGGRESSION Tuning ✅ TESTED (result: bumped to 2.5 for style, April 18)
A/B tested April 15, 2026: TAL=1.5 vs TAL=2.0, 40 games at 50k nodes.
Result: 53.8% vs 46.2% — statistically weak (~1.3 sigma), parameter insensitive.
Decision: bumped to 2.5 on April 18 for personality reasons (style > marginal Elo).

---

## Phase D — NNUE v2 (DEFERRED — when returning to neural)

### Prerequisites:
- Phase G items complete
- Rust engine strong enough to generate quality data
- Budget: ~1 week of compute time

### Architecture (from nodchip's original Stockfish NNUE):
Input:   768 features (piece × square × color)
         NO king buckets — simple (piece, square) only
Layer 1: 256 neurons × 2 perspectives (STM + NSTM) = 512 concatenated
Layer 2: 32 neurons (CReLU)   ← MISSING in v1
Layer 3: 32 neurons (CReLU)   ← MISSING in v1
Output:  1 scalar (centipawns)

### Training procedure:
Step 1 — Data generation (50M+ positions):
- Add --depth 8 flag to generate_selfplay_rust.py
- Use quiet position filter (skip tactical noise)
- Format: FEN + depth-8 eval + game result

Step 2 — Training with correct loss:
Loss = MSE(sigmoid(output/600), target)
where target = 0.5*sigmoid(eval/600) + 0.5*result
Scale: 600cp (not 400) — matches Stockfish convention

Step 3 — Validate with SPRT (not val_loss):
- Play 200 games: new NNUE vs previous best
- PASS if score >= 52%; FAIL: stop, analyze, adjust

Step 4 — Iterative improvement:
- Once NNUE beats PST in SPRT: retrain on self-generated data
- Repeat 3-5 iterations; expected gain +200-400 ELO over PST

### Implementation files to change:
backend/scripts/train_nnue_rust.py — add 32→32 layers, nodchip lambda loss, newbob_decay LR
engine/src/nnue.rs — add l2/l3 weights and biases, update forward() and binary format
backend/scripts/generate_selfplay_rust.py — add --depth flag, quiet position filter

### Why v1 failed (do not repeat):
- Architecture too shallow (missing 32→32 layers)
- Data too little (5M vs 50M+ needed)
- Wrong loss metric (val_loss ≠ ELO)
- Trained on PST self-play (circular, can't improve)

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
- MCTS: 200+ simulations per move, UCB1 formula

### Implementation plan:
1. Add policy head to NNUE architecture
2. Generate policy targets from engine's best moves
3. Train jointly: value loss + policy loss
4. Implement MCTS in Rust (engine/src/mcts.rs)
5. UCI integration: replace ab_search with mcts_search when --mcts flag is passed

---

## Old Next Session Roadmap (superseded by Phase G)

These items were the pre-Phase G roadmap. All are either complete, deferred, or 
superseded by the Phase G plan. Preserved here for reference.

### Quick wins (1-2 sessions):
1. Aspiration windows in Rust engine — DONE (Phase C.2 Item 1)
2. Tune TAL_AGGRESSION constant — DONE (bumped to 2.5, April 18)
3. Wire Syzygy tablebases into Rust engine — DEFERRED (Python backend handles it)

### Medium term (2-3 sessions):
4. Iterative deepening with time management — DONE (Phase C.2 Item 5)
5. Check extension — DONE (Phase C.2 Item 2)
6. Futility pruning — DONE (Phase C.2 Item 3)

### Longer term:
7. NNUE v2 — DEFERRED (see Phase D above)
8. MCTS — DEFERRED (see Phase E above)

---

## Archived from CLAUDE.md (June 16, 2026 — lean-split)

On June 16, 2026 CLAUDE.md was slimmed to live operating context only. The
complete prior CLAUDE.md (commit b8e25f0..c26d387) is preserved verbatim below
— it contains the full NNUE EXPERIMENT PROTOCOL (live state, ledger, Gates A-F,
DIAG 1-4, DIAGNOSTIC E/F, GATE C/D, Spearman, SPRT EXPE, Experiment B, FIX
APPLIED, CRITICAL CORRECTION), Current State (April 26), the Apr 16/19/25/26
gauntlet tables, the Phase D/D1/D1.5/D2/D3/D4 roadmap, Phase F notes, the
April-era Engine Strength Estimates ladder, the detailed G1-G17 Phase G logs,
and the June 5-7 G2/baseline forensic narrative. APPEND-ONLY going forward.

<!-- BEGIN verbatim archive of CLAUDE.md @ c26d387 -->

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI-assisted chess application ("Torch") with a React frontend and a FastAPI backend running a hand-built minimax engine with a neural network upgrade path.

For development history, completed phases, and deferred plans see [HISTORY.md](HISTORY.md).

---

## Current Goal (reset June 5, 2026)

Pyro plays **beautiful, sensible, dynamic, powerful chess** on the
PeSTO+Tal hand-crafted-eval base (~1820 Elo Threads=4, verified June 2026 —
see VERIFIED BASELINE below), finished with Syzygy-perfect endgames.
NOT a max-Elo strength race.

**DESIGN PRINCIPLE** (every future change is measured against this):
Pyro plays beautiful chess by **calculating deeply and accurately**,
then — among moves the search rates as near-equal — preferring the
more dynamic, aggressive one. Aesthetics are a tiebreak, never an
override. Pyro never plays a move the search shows is materially or
tactically worse in order to look flashy. Sound sacrifices EMERGE
from deeper search; they are never forced by a thumb on the
move-ordering scale. (G9, June 4, proved the forcing approach fails:
-362 Elo. Do not repeat ordering-bonus sacs.)

**NNUE-as-eval is SHELVED** (not deleted). expE was the first
trusted net and lost to PeSTO by ~700 Elo (SPRT 1.7%); on GPU-less
hardware a competitive net is out of reach. The pipeline is preserved
for the day the CUDA/cudarc mismatch is fixed and the RTX 3050 is
unlocked. Until then, the live engine runs PeSTO+Tal (--no-nnue).

**PATH TO THE GOAL** (sequenced, one variable each, gauntlet-validated):
1. **POWERFUL** — Lazy SMP (G2 Session 2): 12 cores, deeper search.
   STATUS: ✅ VALIDATED (June 2026 baseline run). Threads=4 is +80-118 Elo over
   Threads=1 on the SF-ladder (61.0% vs SF-1700 / 44.5% vs SF-1900 at T4, vs
   44.3% / 33.8% at T1). The June-5 self-play "neutral" (49%) was wrong — A/B
   self-play understates SMP because both sides gain the ply. (See VERIFIED
   BASELINE + G2 section below.)
2. **DYNAMIC** — capped dynamic-eval tiebreak (G9-done-right, in EVAL
   not ordering): small capped term rewards initiative toward the enemy
   king; UCI param DYNAMIC_BONUS default 0 = no-op.
   STATUS: 🛑 Blocked until Step 1 is validated.
3. **BEAUTIFUL** — emerges from 1+2 over the existing Syzygy base.
4. **PERSONALITY** — G13 taunts, G15 visual attack cues (pure frontend).

**BASELINE STATE (superseded June 16, 2026 — see VERIFIED BASELINE below):**
search.rs baseline is b134da9 (G8v2+CM+SEE+SE, no IID/LMP/depNMP). The "1835
mystery" is now RESOLVED, not retired: the old 1835 was a Threads=4 measurement
(~1820 reproduced here at T4). June-5's "cannot reproduce" compared a fresh
single-thread rebuild (~1721) against a 4-thread historical number — a
thread-count mismatch, not Stockfish luck. The figure was real but
thread-count-unlabeled. IMPLICATION: the IID/LMP/dep-NMP deletion was likely
chasing a thread-count artifact, not a real regression — flag for the re-add fork.

**G9 CLOSED**: ordering-bonus sacrifice-seeking REJECTED — wrong
instrument (biases what gets searched, not what calculation confirms).
Code stays dormant at SPEC_BONUS=0 (byte-identical to baseline).
Do not retry tightened.

---

## VERIFIED BASELINE (June 2026) — measure everything against this

- **Anchor:** commit `b8e25f0b` · binary md5 `587567f2bbd5ce54e40481b7cc9ccea6`
  · `--no-nnue` · TC 10+0.1 · concurrency=1 · no opening book · 600 games · 0 disconnects.
- **Threads=1 (engineering baseline — the reference for "did a code change help"):**
  44.3% vs SF-1700 (−40 ± 47), 33.8% vs SF-1900 (−117 ± 49) → implied **~1721 Elo**.
- **Threads=4 (production — what ships; rust_engine.py sends `setoption Threads 4`):**
  61.0% vs SF-1700 (+78 ± 64), 44.5% vs SF-1900 (−38 ± 68) → implied **~1820 Elo**.
- **SMP VERDICT: POSITIVE, +80-118 Elo on the SF-ladder.** vs SF-1700 the T4/T1
  CIs do not overlap (significant); vs SF-1900 same direction (suggestive).
  This OVERTURNS the June-5 "neutral" self-play result — A/B self-play understates
  SMP because both sides gain the ply. **G2 ✅ VALIDATED.**
- **1835 mystery RESOLVED:** old 1835 ≈ this T4 ~1820. It was a Threads=4 number
  all along; the June-5 reproduction failure was a single-thread-vs-4-thread
  comparison. Real, but thread-count-unlabeled. (See BASELINE STATE note above for
  the IID/LMP/dep-NMP re-add implication.)
- **Style anchor (for DYNAMIC_BONUS clause 1):**
  T1 — aggression 77.2% / kz_sac 31.0% / sacs_per_game 1.30 / kz_sacs_per_game 0.35.
  T4 — aggression 71.0% / kz_sac 38.0% / sacs_per_game 1.20 / kz_sacs_per_game 0.42.
- **Prediction held?** RUN 1 mostly held (SF-1900 33.8% in 30-35% range, implied
  ~1721 at top of 1690-1720 guess; SF-1700 slightly under the ~50% guess).
  RUN 2 FAILED (predicted T4 within ±25 Elo of T1; actual +80-118) — SMP is positive.
- **Rules:** every future change measured vs THIS baseline (T1 for "did it help",
  T4 for "what ships"), ≥100 games minimum, one variable at a time, prediction first.
- Raw data: `backend/scripts/gauntlet/results/baseline_2026-06/` (PGNs, logs, NOTES.md).

---

## NNUE EXPERIMENT PROTOCOL (read first, every NNUE turn)

This section is the shared source of truth between planning (chat) and execution
(Claude Code). Read it at the START of every NNUE turn. Update it at the END of
every NNUE turn. The user pastes this section to chat-Claude; no NNUE training,
conversion, or SPRT proceeds until planning and execution agree on it.

### Rules of engagement
1. ONE VARIABLE per experiment. Before running, "Variable changed" below must
   name exactly one change vs the previous run. If you cannot name exactly one,
   STOP and ask. (This rule exists because 512+wdl were changed together twice.)
2. DEPLOYMENT GATE. The engine loads pyro.nnue from the EXECUTABLE's directory
   (engine/target/release/pyro.nnue), NOT engine/pyro.nnue. SPRT is FORBIDDEN
   unless md5(engine/pyro.nnue) == md5(engine/target/release/pyro.nnue). Record
   both md5s in Deployment State before any SPRT. validate_nnue_rust.py must
   hard-refuse to run if they differ.
3. PREDICTION FIRST. Write a falsifiable prediction before running. After the
   run, record whether it held.
4. NO ARCHITECTURE JUMPS ON CONTAMINATED EVIDENCE. Do not change neuron count
   or architecture to "fix" a result until that result comes from a
   deployment-verified, COMPLETED SPRT (>=100 games, not bailed early).
5. DIAGNOSE BEFORE RETRAIN. Run cheap read-only diagnostics before spending
   30-65 min of compute. Information is cheaper than experiments.
6. RESET CHECKPOINT. When asked for a "reset checkpoint", output Live State +
   Deployment State + Ledger + Open Questions as a plain-text snapshot and
   change nothing.

### Live experiment state
- Experiment ID: Experiment E — TRAINING IN PROGRESS (started June 1)
- Hypothesis: loss/inference scale mismatch is root cause of all SPRT failures.
  Switching to stock Bullet convention (output.sigmoid() loss + ×SCALE at inference)
  frees l1w from binary saturation.
- Variable changed: loss `sigmoid(output/400)` → `output.sigmoid()`;
  inference `output/(QA*QB)` → `output*400/(QA*QB)`. SCALE=400 in both files.
  (One logical change, two files that must agree. No l0w clip. No other change.)
- Held constant: 256 neurons, SF18 data, SB30, WDL=0, CReLU, default AdamW clips
- Prediction (falsifiable, per rule 3):
    (A) Gate A: l1w no longer ~100% saturated; mean_abs well below 1.98, real spread
    (B) Gate C: queen-missing eval in roughly -600..-900cp (not +23, not -84)
    (C) Gate D: sibling ranking ≥4/10 (up from 2/10)
    (D) SPRT meaningfully above 0.7% — first real chance of a positive pulse
- Status: **SPRT COMPLETED (June 2). expE-30 vs PeSTO 10+0.1:
  0W-58L-2D = 1.7%, Elo -708, LOS 0.0%, H0 accepted at 60 games. First
  trusted SPRT in project history (Gate A continuous + DIAG 3 material-correct
  + deployment verified). Net learns absolute material from in-distribution
  data but within-position ranking is too noisy to play winning chess at this
  architecture. Pattern fits Spearman+0.155 (real but below the 0.3
  "tracks SF18" threshold). 256-neuron / 20M-position / CReLU / WDL=0 ceiling
  confirmed. Next planning decision: data scale, WDL blending, architecture,
  or Tal-bias path.**

Gate A result (pyro-expE-30 vs d1v3-clean baseline):
  | Metric           | d1v3-clean (old) | pyro-expE-30 (new) |
  |------------------|------------------|--------------------|
  | l1w mean_abs     | 1.9800 (binary)  | **0.0405**         |
  | l1w std          | 1.9800           | 0.0638             |
  | l1w min/max      | ±1.98            | -0.2957 / +0.2851  |
  | l1w >=0.95×clip  | 100.0%           | **0.0%**           |
  | l1b raw          | +1.98 (at clip)  | +0.0579 (2.9%)     |
  | l0w mean_abs     | 0.6608           | 0.0698             |
  PASS: l1w no longer binary. Continuous spread confirmed. Loss change took effect.

Gate C result (June 2, 2026) — pyro-expE-30:
  | Position              | Float  | Quant | Eng d1 | FQ-gap |
  |-----------------------|--------|-------|--------|--------|
  | Startpos (W2M)        |   +3.7 |    +8 |    +62 |    4.3 |
  | Startpos (B2M) 1.e4   |  +26.9 |   +28 |    +67 |    1.1 |
  | W queen missing       |  +24.1 |   +28 |    +85 |    3.9 |
  | B queen missing       |  +24.1 |   +28 |    +85 |    3.9 |
  | W rook missing        |  -30.3 |   -27 |    +35 |    3.3 |
  | Open-centre Sicilian  |   +4.3 |    +3 |    +39 |    1.3 |
  | Endgame K+R vs K      | +152.1 |  +149 |   +304 |    3.1 |
  | W up Q+R vs bare K    |  +18.6 |   +10 |   +851 |    8.6 |
  FAIL: W/B queen missing = +24cp (expected <-200cp). SPRT forbidden.
  NOTE: expE is WORSE than d1v3-clean (-84cp) despite fixing l1w saturation.

### Deployment state (anti-stale-weights guard)
- engine/pyro.nnue md5:                        23bfcd331411b8b9c6a05191d42caef5
- engine/target/release/pyro.nnue md5:         23bfcd331411b8b9c6a05191d42caef5
- MATCH (yes/no — SPRT forbidden if no):       YES
- Net currently deployed (best guess):         pyro-expE-30 (256-neuron, stock loss, WDL=0, SB30, SCALE=400)
- Last verified:                               2026-06-02

### Honest ledger (APPEND-ONLY — never edit or delete past rows)
| date | exp | one variable | max eval | nodes/s NNUE | nodes/s PeSTO | SPRT | trustworthy? | notes |
|------|-----|--------------|----------|--------------|---------------|------|--------------|-------|
| ~May 5  | d1v2          | PeSTO data, STM-fix | 966cp | ? | ? | 34%  | CONTAMINATED | stale-weights bug active since ~May 7 |
| ~May 6  | d1v3          | SF18 data           | 966cp | ? | ? | ~32% | CONTAMINATED | " |
| ~May    | d2v1          | 512 + wdl0.75       | ?     | ? | ? | 0.8% | CONTAMINATED | " |
| ~May    | d2-evalonly   | wdl0 @256           | 572cp | ? | ? | none | n/a          | eval-only, never SPRT'd |
| May 30  | clip10        | l1w clip ±10 @256   | 1281cp| ? | ? | ~0.7% contaminated then ~1W-13L | CONTAMINATED | first SPRT stale; 2nd bailed at 14 games |
| May 31  | clip10-clean  | l1w clip ±10 @256   | 1281cp| ? | ? | 0.7% (0W-67L-1D) H0@68games | CLEAN | first clean SPRT; −852 Elo; LOS 0.0%; l1w saturation diagnosed |
| May 30  | 512clip10 (B) | 512 neurons         | ?     | ? | ? | not run | pending | training COMPLETE (May 31); not yet converted; awaiting planning sign-off |
| May 31  | (engine fix)  | robustness fix only | n/a   | n/a | n/a | n/a | n/a | 96/96 green; go wtime legal at 10s+80ms clock; (none) bug fixed |
| May 31  | d1v3-clean    | default clip ±1.98 (vs clip10) | 1281cp | depth12/5s | depth13/5s | 0.7% (0W-74L-1D) H0@75games | CLEAN | −869 Elo; LOS 0.0%; identical to clip10-clean. Clip is NOT the differentiator. |
| May 31  | expD          | l0w clip ±0.06 (vs d1v3-clean ±1.98) | ~24cp | depth12/5s | depth13/5s | NOT RUN | CLEAN | neurons 205/256 active (↑ from 50); queen +23cp WRONG SIGN; sibling 2/10; ±0.06 too tight (max queen eval physics bound ~24cp). Hypothesis valid; clip value wrong. |
| Jun 2   | expE          | stock loss output.sigmoid() + ×SCALE at inference (vs old sigmoid(output/400)) | ~24cp OOD, -750cp ID | depth12/5s | depth13/5s | **1.7% (0W-58L-2D) H0@60games, -708 Elo, LOS 0.0%** | CLEAN | First trusted SPRT in project history. Gate A PASS, DIAG 3 PASS (material correct in-dist), Spearman+0.155 vs SF18. Net is continuous + material-correct in-distribution but within-position ranking too noisy. Lost every decisive game. Equal losses as W (29) and B (29). 256/20M architectural ceiling confirmed. |

### Ruled out (with evidence + caveat)
- WDL labels as bias source: eval-only (wdl0) showed same weight pattern.
  CAVEAT: the engine-side "+492cp" symptom was a STALE FILE, so this needs a
  clean re-test before treating as settled.
- SCALE/sigmoid squashing: only 1.4% of targets saturate at SCALE=400.
  Solid (computed from data file, not engine). Do NOT retrain with SCALE=800.
- clip10 (l1w clip ±10) is CONFIRMED HARMFUL. SOLID (clean SPRT + diagnostics).
  Raw l1w range expanded to ±9.8 (vs ±1.98 default). 89.65% of out_weights
  saturated at ±127 quantized. Accumulator: 128/256 neurons dead (<=0),
  78/256 maxed at QA=255; only 50/256 active. Queen eval: +129cp instead
  of +900cp — material discrimination severely compressed. Fit diagnostic:
  Pearson 0.97 on training data (network LEARNED the distribution) but
  eval landscape is jagged — consecutive positions swing ±80cp — so search
  is guided by noise. Default AdamW clip ±1.98 is a useful constraint.
  DO NOT retrain with clip10.
- l1w clip value (±1.98 vs ±10) is NOT the differentiating variable.
  SOLID (d1v3-clean SPRT: -869 Elo, same as clip10-clean -852 Elo).
  Both default-clip and clip10 nets score ~0.7% vs PeSTO. Root cause is
  NOT l1w clip — it is l0w (ft_weight) saturation (see Open Questions).
- l0w clip ±0.06 is TOO TIGHT for material discrimination. SOLID (Experiment D mechanism check).
  Physics bound: max queen eval = 2 × 15 × 205 × avg_out_weight / (QA×QB) ≈ 24cp. Network
  physically cannot represent -900cp queen value with ±0.06 l0w clip regardless of training.
  Neurons improved to 205/256 active (confirming saturation hypothesis) but material signal
  destroyed. DO NOT retrain at ±0.06. Next candidate: intermediate clip ~±0.3–0.5 raw
  (→ ±76–127 quantized). l0w saturation as root cause of SPRT failures remains VALID.

### Open questions / untested failure modes (check BEFORE any SPRT verdict)

**bestmove (none) on go nodes N / go movetime N — DIAGNOSED (May 30, 2026)**
- ROOT CAUSE: In `best_move_nodes` (search.rs), the budget/time check at the
  root move loop (line 1559) fires BEFORE the first move's score is committed
  to `best`. Guard condition is `(nodes >= limit || time_up) && best.is_none()`.
  When the first `ab_search` call exhausts the budget (nodes=1 → returns static
  eval immediately; or movetime 1ms deadline expires mid-search), `best` is still
  `None`, so `completed=false; break` fires with `iter_best=None`. The fallback
  at line 1616 only helps if `iter_best` has a value — it doesn't — so
  `best_overall` stays `None` → `bestmove (none)`.
  For `go movetime N` where N ≤ 50: `parse_go_deadline` computes
  `N.saturating_sub(50).max(1)` = 1ms for any N ≤ 50. That 1ms expires during
  the first root move's `ab_search`, hitting the same code path.
- go wtime/btime (SPRT-relevant path): **NOT AFFECTED at any tested clock**.
  Normal TC: `go wtime 10000 btime 10000 winc 100 binc 100` → `bestmove d2d4`.
  Classical TC: `go wtime 300000 btime 300000 movestogo 40` → `bestmove d2d4`.
  Low clock: `go wtime 200 btime 200 winc 100 binc 100` → `bestmove d2d4`.
  Extreme time trouble: `go wtime 80 btime 80 winc 0 binc 0` → `bestmove d2d4`.
  The 10ms floor in `parse_go_deadline` (`.max(10)`) protects the wtime/btime
  path even at extremely low clocks — enough time for depth 1 to always complete.
- SPRT validity verdict: `go wtime/btime` returns a legal move at 10s clock AND
  at 200ms clock AND at 80ms clock (extreme time trouble). The (none) bug does
  NOT fire on the SPRT path. Stale-weights remains a confirmed contaminant; it
  is NOT established as the sole cause of past SPRT losses — we still have zero
  clean completed SPRTs. The (none) bug was NOT a factor in prior SPRTs.
- FIX APPLIED (May 31, 2026) — see subsection below. Robustness 96/96 green.

**one_legal_move returns (none) at all depths — NOT A BUG (May 30, 2026)**
- ANALYSIS: `k7/8/K7/8/8/8/8/1R6 b - - 0 1` is STALEMATE, not a forced-move
  position. Black king at a8 has three adjacent squares: a7 (attacked by white
  king at a6), b7 (attacked by rook b1 + white king), b8 (attacked by rook b1).
  All squares attacked; king not in check. Zero legal moves → stalemate.
  The test comment "Ka8 is the only legal move" was WRONG.
  The engine correctly returns `None` at `generate_moves` → `moves.is_empty()`
  (search.rs:1485-1487). DISTINCT from the nodes/movetime bug and not a defect.
- FIX NEEDED: Replace the stalemate position in `engine_robustness_check.py`
  with an actual single-legal-move position. Not urgent (doesn't affect SPRT).

**NNUE eval speed — MEASURED (May 31, 2026)**
- NNUE: depth 12 (3/3 trials) at movetime 5000ms on startpos.
- PeSTO: depth 13 (3/3 trials) at movetime 5000ms on startpos.
- NNUE is 1 ply shallower. Real confound but not catastrophic.
  Engine does not output nps; depth reached is the only available metric.
  This 1-ply penalty applies to ALL future NNUE SPRTs — factor it in when
  interpreting results.

**l0w (ft_weight) saturation — ROOT CAUSE of all ~0% SPRTs (May 31, 2026)**
- FINDING: ft_weights (l0w) are ~16× too large. Default AdamW clip ±1.98 raw
  = ±504 quantized (QA=255). With ~32 pieces per position each contributing
  ±504 per neuron, the accumulator ranges from ≈-668 to ≈+780. CReLU clips
  to [0, QA=255], so ~80% of neurons are permanently clamped to 0 or 255.
  Only 50-53/256 neurons are active. This is true for BOTH default-clip AND
  clip10 nets — the l0w clip was not changed in either experiment.
- CONSEQUENCE: Network uses ~50 heavily-weighted neurons instead of all 256.
  Evaluation landscape is coarse and volatile (±75cp per move vs ±10-20cp
  for PeSTO). Queen eval: ~-85 to -97cp instead of -900cp.
- EXPERIMENT D RESULT (May 31, 2026): ±0.06 clip confirmed hypothesis direction
  but clip value too tight. Active neurons: 205/256 (↑ from 50 — saturation
  hypothesis CONFIRMED). But max queen eval physics bound ≈ 24cp: queen is 1
  feature per perspective → max contribution = 2 × 15 × n_active × avg_out_w /
  (QA×QB) ≈ 24cp. Wrong sign too (+23cp, should be <-500cp). SPRT NOT RUN.
- NEXT STEP: Intermediate l0w clip. Candidate: ±0.3–0.5 raw (→ ±76–127
  quantized). At ±0.3: max queen eval ≈ 2 × 76 × 200 × avg_out_w / 16320 ≈
  higher but accumulator range wider too. Needs planning sign-off.
  Key constraint: l0w clip must be large enough for material discrimination
  but small enough to prevent CReLU saturation. Optimal is somewhere between
  ±0.06 (too tight) and ±1.98 (too loose).

**DIAGNOSTIC E (May 31, 2026) — float vs quantized vs engine, jaggedness, sibling ranking**

Net under test: pyro-d2-evalonly-30 (md5 e706ea..., HIDDEN=256, QA=255, QB=64, default clip).
All checks read-only (no training, no SPRT).

CHECK 1 — Float (raw.bin) vs Quantized-Sim vs Engine depth-1

| Position              | Float  | Quant | Eng d1 | FQ-gap |
|-----------------------|--------|-------|--------|--------|
| Startpos (W2M)        |  +19.6 |   +19 |    +71 |  0.6cp |
| Startpos (B2M) 1.e4   |   -3.9 |    -4 |    +61 |  0.1cp |
| W queen missing       |  -83.7 |   -84 |     +5 |  0.3cp |
| B queen missing       | +121.9 |  +122 |   +165 |  0.1cp |
| W rook missing        |  -35.5 |   -36 |    +19 |  0.5cp |
| Open-centre Sicilian  |  +99.8 |  +100 |   +262 |  0.2cp |

Float vs Quant: mean gap=0.4cp, max=1.2cp. Signs correct: 8/8.
Engine depth-1 != static eval (it searches one ply); not a mismatch.
Queen eval -84cp (should be ~-900cp) is a NET QUALITY issue, not a pipeline bug.
Inference verdict: **CORRECT**

CHECK 2 — Eval jaggedness (20 consecutive same-game plies)
Mean |delta| SF18 = 374.8cp. Mean |delta| NNUE = 390.1cp. Ratio = 1.04x.
Jaggedness verdict: **SMOOTH** (threshold 3.0x).
CAVEAT: This metric measures same-game trajectory (alternating STM — perspective flip
accounts for the large per-ply deltas). It does NOT test within-position move
discrimination. The 1.04x ratio means NNUE tracks SF18's game trajectory faithfully
but is neutral on the l0w saturation hypothesis.

CHECK 3 — Sibling ranking: NNUE top quiet move vs PeSTO top quiet move (10 positions)
Agreement: 0/10 = 0%. Positions had 18-39 quiet moves each. All different positions.
Sibling ranking verdict: **SCRAMBLED**
NNUE cannot rank moves within a position. All sibling evals are compressed into a
tiny range by l0w saturation → ranking is noise. This is the DIRECT cause of SPRT
failure. Baseline for Experiment D: success = agreement rate >= 40%.

Combined verdict: pipeline CORRECT, game-level eval SMOOTH, move ranking SCRAMBLED.
l0w saturation (50/256 neurons active) confirmed as root cause of SCRAMBLED ranking.
Experiment D (tight l0w clip ±0.06) remains the correct next step.

**Experiment D mechanism check (May 31, 2026) — PARTIAL FAIL, SPRT NOT RUN**

Net under test: pyro-expD-30 (md5 1b0557a..., HIDDEN=256, QA=255, QB=64, l0w clip ±0.06).
SB30 training loss: 0.023755 (vs d1v3-clean 0.01607 — higher loss as expected from constraint).

| Metric               | Baseline (d1v3-clean) | Experiment D | Verdict     |
|----------------------|-----------------------|--------------|-------------|
| Active neurons       | 50/256                | 205/256      | MOVED ✓     |
| Dead neurons         | 145/256               | 9/256        | MOVED ✓     |
| Maxed neurons        | 58/256                | 42/256       | MOVED ✓     |
| Queen-missing eval   | -84cp                 | +23cp        | WRONG SIGN ✗|
| Sibling ranking      | 0/10                  | 2/10         | BELOW 3/10 ✗|
| Engine binary sign   | ok                    | ok           | OK ✓        |
| out_bias             | -2,932                | +32,314      | ANOMALOUS   |

Mechanism verdict: PARTIAL FAIL. Neurons moved (hypothesis direction confirmed). Material
discrimination broken: wrong sign on queen eval (+23cp instead of < -500cp). Sibling ranking
2/10 (threshold 3/10). Out_bias extremely positive (+32,314) — network compensating for
clipped l0w by shifting bias, distorting absolute eval scale.

Root analysis: ±0.06 l0w → ±15 quantized. Queen contributes 1 feature per perspective.
Max queen eval = 2 × 15 × 205 × avg_out_weight / (QA×QB=16320). With typical avg_out_w ≈ 20,
max ≈ 24cp. This is a hard physics limit — the queen cannot be represented at ±0.06, ever.
The ±0.06 value chose one pathology (saturation) and introduced another (material blindness).

SPRT forbidden per protocol. Next: planning sign-off on intermediate clip ~±0.3–0.5.

**DIAGNOSTIC F (June 1, 2026) — loss-scale audit, target distribution, baseline weight saturation**

CHECK 1 — pyro.rs vs simple.rs (stock Bullet example) FULL DIFF

Every difference between our config and the stock example:

| Item                  | simple.rs (stock)                             | pyro.rs (ours)                                      | Direction of diff |
|-----------------------|-----------------------------------------------|-----------------------------------------------------|-------------------|
| Activation            | `.screlu()` — squared clipped ReLU            | `.crelu()` — plain clipped ReLU                     | ours differs      |
| **Loss function**     | `output.sigmoid()` — raw output thru sigmoid  | `(output*(1/400)).sigmoid()` — **divide by SCALE first** | **KEY DIFF** |
| WDL                   | 0.75 (game-result blended)                    | 0.0 (eval-only)                                     | ours differs      |
| LR schedule           | StepLR (start=0.001, gamma=0.1, step=18)      | CosineDecayLR (1e-3→1e-5 over 30 SB)               | ours differs      |
| HIDDEN_SIZE           | 128                                           | 256                                                 | larger (fine)     |
| Training volume       | 40 SB × 6104 = ~100M positions                | 30 SB × 1221 = ~20M positions                      | ours 5× less      |
| Data filter           | ply>=16, no-check, |score|<=10000, quiet move | **none — all positions included**                   | ours unfiltered   |
| l0w extra clip        | none — default AdamW ±1.98 only               | expD: explicit ±0.06 (d1v3-clean: none)             | ours adds clip    |
| out_bias / l1w clips  | none beyond default AdamW ±1.98               | none beyond default AdamW ±1.98                     | same              |
| use_devices           | not set (GPU auto-detect)                     | `.use_devices(vec![()])` (CPU explicit)             | cosmetic          |
| Inference SCALE mult  | engine multiplies by SCALE=400 at output      | **our nnue.rs does NOT multiply by SCALE**          | **KEY DIFF** |

What stock does that WE DO NOT:
  1. SCReLU activation (better gradient flow for quantized nets)
  2. WDL blending (game outcome reduces noise in extreme-eval positions)
  3. Quiet-position filter (removes captures/check positions, |score|<=10000 cap)
  4. Multiply by SCALE at inference — `eval = (accum + bias) * SCALE / (QA*QB)`
  5. Small output loss (`output.sigmoid()` keeps l1w in ±0.04 regime)

**CRITICAL IMPLICATION OF LOSS FUNCTION DIFFERENCE:**
- Stock: `sigmoid(output)` — network learns output ≈ score/400 ∈ [-2,2]
  For 900cp queen: need sum(crelu×l1w) ≈ 2.25. With 50 active neurons at crelu≈0.5:
  mean(l1w) needed ≈ 2.25/(50×0.5×2) = **0.045** — well within ±1.98 clip.
- Ours: `sigmoid(output/400)` — network learns output ≈ score (centipawns) ∈ [-800,800]
  For 900cp queen: need sum(crelu×l1w) ≈ 900. With 50 active neurons at crelu≈0.5:
  mean(l1w) needed ≈ 900/(50×0.5×2) = **18.0** — EXCEEDS ±1.98 clip by 9×.
Our loss forces l1w to operate 400× outside its clipped regime vs the stock formulation.

CHECK 2 — SF18 target distribution (n=2,000,000 sampled, seek-based)

| Stat     | Value  |
|----------|--------|
| min      | -29,997 cp |
| max      | +29,996 cp |
| mean     | +61.1 cp |
| std      | 3,353 cp |
| p1       | -1,017 cp |
| p10      | -571 cp |
| p25      | -283 cp |
| p50      | +46 cp |
| p75      | +442 cp |
| p90      | +737 cp |
| p99      | +1,058 cp |

Saturation fractions (for sigmoid(eval/400) loss):
  |eval| > 400cp  :  50.1%  (sigmoid < 0.27 or > 0.73)
  |eval| > 600cp  :  25.3%
  |eval| > 800cp  :   9.3%
  |eval| > 1000cp :   2.4%
  |eval| > 2000cp :   1.2%
  |eval| > 1178cp :   1.5%  (true sigmoid saturation: sigmoid < 0.05 or > 0.95)
  median |sigmoid - 0.5| = 0.232,  mean = 0.210

Distribution verdict: TRUE sigmoid saturation (±0.05/0.95 boundary) is only 1.5% of data.
The 50.1% figure at |eval|>400cp is "outside linear zone" but not yet saturated.
The extreme min/max (±30,000) are forced-mate evals — SF18 outputs mate scores as large cp values.
The std of 3,353cp is large; SCALE=400 is poorly calibrated for this distribution.
At SCALE=400: half the positions have targets where sigmoid gradient is already < 0.5× peak.
This does push the network toward large outputs, but is NOT the primary driver of l1w saturation —
1.5% sigmoid-saturated positions cannot force 100% l1w saturation (see CHECK 3).

CHECK 3 — d1v3-clean raw.bin (SB30 default-everything baseline)

| Layer | Metric          | Value               | Interpretation |
|-------|-----------------|---------------------|----------------|
| l1b   | raw float       | +1.980000           | PINNED AT CLIP (100%) |
| l1b   | quantized       | +32,314             | 32314/16320 = 1.98cp contribution |
| l1w   | mean_abs        | 1.9800              | ALL weights at clip boundary |
| l1w   | std             | 1.9800              | bimodal at exactly ±1.98 — no gradient |
| l1w   | |w|>=0.95×clip  | **100.0%**          | every single weight near-saturated |
| l1w   | |w|>=0.50×clip  | 100.0%              | no small weights at all |
| l0w   | mean_abs        | 0.6608              | substantial, not saturated |
| l0w   | |w|>=0.95×clip  | 8.80%               | small fraction at ft-weight clip |
| l0w   | |w|<=0.10       | 25.0%               | many near-zero (dead feature slots) |
| l0b   | mean            | +0.2820             | modest, not saturated |
| l0b   | std             | 0.1223              | varies across neurons |

Theoretical max float output (all neurons at crelu=1, all l1w at ±1.98, 2 perspectives):
  2 × 256 × 1.0 × 1.98 = **1014 cp** (hard upper bound for our inference)

Typical output for 50/256 active neurons (crelu≈0.5):
  2 × 50 × 0.5 × 1.98 = **99 cp** — consistent with observed queen eval of -84cp.

KEY FINDING: The DEFAULT d1v3-clean net (no clip experiments, just standard training)
already has ALL 512 l1w weights pinned at ±1.98. Mean_abs=1.9800 and std=1.9800 means
the distribution is bimodal at {-1.98, +1.98} — every weight is at the AdamW clip
boundary. This saturation is NOT caused by any clip experiment. It exists because
our loss `sigmoid(output/400)` requires centipawn-scale outputs, but ±1.98 clips
prevent l1w from ever reaching the ≈18 needed for a 900cp queen signal.

The gradient pushes ALL l1w toward ±∞; the clip pins them at ±1.98; nothing escapes.
The output layer has been reduced to 512 BINARY weights (+1.98 or -1.98) with zero
continuous information capacity. The network cannot represent material differences
beyond what its ~99cp ceiling allows (50 active neurons × 0.5 crelu × 1.98 l1w × 2).

CORRECTION to Experiment D mechanism check table: the "Baseline out_bias = -2,932"
row was read from pyro-d2-evalonly's deployed pyro.nnue, NOT d1v3-30 raw.bin.
D1v3-30 raw.bin shows out_bias = +1.98 (also at clip). The d2-evalonly net had a
negative bias — that's a different net, different training. The expD +32,314 anomaly
is simply expD also being at the +1.98 clip, same as d1v3. Both are fully clipped.

DIAGNOSTIC F — VERDICT

Root driver: **Loss function scale mismatch**
Our loss `sigmoid(output/400)` forces the network to output centipawns directly.
This requires l1w ≈ 18 for a 900cp queen eval (50 active neurons), but the AdamW
clip limits l1w to ±1.98. The gradient NEVER relaxes — it always pushes l1w toward
±18 — so all 512 output weights pin at ±1.98 immediately and stay there for the
entire training run. The output layer is permanently binary. This is the root cause
of all failed SPRTs from d1v2 onward. The l0w saturation (50/256 active neurons)
is a SECONDARY bottleneck — it matters, but fixing it alone (Experiment D) cannot
help because the l1w binary ceiling remains.

Ruling in/out:
  (a) Loss-scale mismatch: CONFIRMED root cause. l1w 100% pinned in DEFAULT net.
  (b) Unconstrained out_bias: NOT an independent cause. It's also pinned at clip,
      same reason as l1w. Symptom, not driver.
  (c) CReLU vs SCReLU: probably secondary. With correct loss scale, CReLU l1w
      would be ≈0.045, well within clip. SCReLU might help gradient flow but
      won't rescue a system where l1w must be 400× too large.
  (d) Data ceiling: NOT primary. 1.5% sigmoid-saturated targets cannot force
      100% weight saturation. Wide std (3353cp) adds noise but is not the driver.

Recommended next experiment (Experiment E — requires planning sign-off, DO NOT RUN):
  Change to stock inference formulation as a MATCHED PAIR of two files:
  1. pyro.rs: change loss to `output.sigmoid()` (remove the /SCALE division)
  2. nnue.rs: change eval formula to `(accum + out_bias) * SCALE / (QA * QB)`
     (add ×SCALE multiplication before the divide, as in simple.rs reference engine)
  Hold constant: 256 neurons, SF18 data, SB30, WDL=0, default AdamW clips, CReLU.
  These two changes are a matched pair (one logical change: loss/inference scale)
  and do not violate the one-variable rule.
  Expected: l1w needed ≈ 0.045 (vs 18.0 now). Clip becomes non-binding. All 512
  output weights free to express continuous values. Queen eval should reach ~900cp.
  Active neuron count (50) remains the secondary bottleneck — address after this passes.

**GATE C FAIL — Experiment E mechanism check (June 2, 2026)**

Net under test: pyro-expE-30 (256-neuron, stock loss output.sigmoid(), WDL=0, SB30, SCALE=400).

Comparison table:

| Metric               | d1v3-clean | expD (l0w±0.06) | expE (stock loss) | Verdict         |
|----------------------|------------|-----------------|-------------------|-----------------|
| l1w mean_abs         | 1.98       | ~0.04           | 0.0405            | expE fixed ✓    |
| l1w saturation       | 100%       | 0%              | 0.0%              | expE fixed ✓    |
| Queen eval (float)   | -84cp      | +23cp           | +24cp             | STILL BROKEN ✗  |
| Queen eval direction | right sign | wrong sign      | wrong sign        | SAME AS expD ✗  |
| Rook eval (float)    | -36cp      | n/a             | -30cp             | correct sign ✓  |

Key observation: expE is WORSE than d1v3-clean on queen eval (-84 → +24). Despite fixing
l1w saturation (the diagnosed root cause), material discrimination did not improve.

Root cause REVISION: Loss-scale mismatch was the correct first fix, but it was not
sufficient. The remaining failure is a TRAINING DATA DISTRIBUTION problem:

1. In SF18 self-play data, queens are present in almost every position for both sides.
   A feature that fires in every position provides near-zero gradient signal during
   training (cross-entropy trains on DIFFERENCES, not constants).

2. The test position (startpos - 1 queen) is out-of-distribution. No SF18 game
   begins with one queen removed. The network never learned to generalize
   "queen-at-d1 absent → catastrophic loss" from mid-game queen captures.

3. Observed sign evidence: removing queen at d1 → +24cp (better!), removing rook at a1
   → -30cp (worse). The queen at d1 is the undeveloped back-rank queen. SF18 data
   correlates "queen moved off d1 = developed = good." So l0w[queen_d1] has a slightly
   negative sign (its absence → slightly positive eval). This is genuine positional
   learning — but positional, not material.

What expE DID fix: l1w is no longer binary. The network now has continuous output
capacity. The pipeline is correct (float ≈ quant). The loss convention is right.
These fixes are NECESSARY but not SUFFICIENT.

What remains broken: the network learned POSITIONAL correlations from SF18 game
positions but did not learn MATERIAL values. Queens present in almost every training
position → near-zero discriminative signal for queen-vs-no-queen.

Candidate next experiments (need planning sign-off, ranked by expected impact):
  (F1) WDL blending WDL=0.5: game outcomes correlate more directly with material.
       When one side loses their queen and loses the game, WDL=0 provides gradient
       even for positions rarely seen in SF18 static eval. One variable vs expE.
  (F2) Data augmentation: include positions with material imbalances (random piece
       removal from game positions, scored by SF18 at depth 12).
  (F3) More training data (100M+): more queen-capture positions in training set.
  (F4) Different test: if queens DO appear in mid-game capture chains, test a
       position from WITHIN a game where a queen was just captured. This would
       verify the network IS learning from in-distribution queen-captures.

SPRT forbidden per protocol. Next: planning sign-off.

**DIAG SUITE EXPE (June 2, 2026) — OVERTURNS "material-blind" verdict**

Four read-only diagnostics run after Gate C FAIL. Result: **the network is NOT
material-blind. The Gate C test position is OOD and not informative.**

DIAG 1 — symmetry of W vs B queen missing:
  W queen missing: float raw=+0.060198, cp=+24.079
  B queen missing: float raw=+0.060198, cp=+24.079
  |stm_W - stm_B|max  = 3.6e-07  (floating-point noise)
  |nstm_W - nstm_B|max = 4.8e-07  (floating-point noise)
  CONCLUSION: identical by DESIGN. Chess768 symmetric encoding maps
  W queen at d1 from W perspective to the SAME feature index (259) as B queen
  at d8 from B perspective (sq^56 mirroring). startpos is mirror-symmetric, so
  removing a queen from the STM side yields LITERALLY the same 256-d accumulator.
  Identical output ≠ "eval insensitive to queen" — it's a tautology of the input
  encoding. This is NOT evidence of material blindness.

DIAG 2 — material sweep from startpos:
  | Piece removed (W)  | float cp  | Δfloat   |
  |--------------------|-----------|----------|
  | base startpos      |    +3.65  |  (base)  |
  | - Pawn (e2)        |    -7.46  |  -11.12  |  ← small, correct sign
  | - Knight (b1)      |  -160.27  | -163.92  |  ← LARGE, correct sign (~knight ≈ 300)
  | - Bishop (c1)      |   -32.03  |  -35.68  |  ← small, correct sign
  | - Rook (a1)        |   -30.30  |  -33.95  |  ← small, correct sign
  | - Queen (d1)       |   +24.08  |  +20.43  |  ← WRONG SIGN, small
  Knight delta -164cp ALONE proves the network is NOT material-blind. It IS
  capturing material for at least Knight; pawn delta also correct sign. Queen
  d1 wrong sign confirms a learned POSITIONAL preference (queen-at-d1 =
  undeveloped = slightly bad), which overrides the small residual material
  signal IN THE STARTPOS CONFIGURATION. Bishop c1 / Rook a1 similar regime —
  the on-back-rank features carry small positive weight (slight "in starting
  square" preference) that mostly cancels their material contribution.

DIAG 3 (DECISIVE) — in-distribution queen-down positions:
  Scanned 51 lines of SF18 .plain, found 5 mid-game positions where STM (white)
  has no queen, opponent has queen, ply≥16, SF18 cp ≤ -700.
  | SF18 cp | NNUE float cp | NNUE quant cp | FEN (abbrev) |
  |---------|---------------|---------------|--------------|
  |  -752   |    -747.32    |     -756      | 6k1/p1p5/3pp1q1/.../... w   |
  |  -730   |    -760.17    |     -764      | 6k1/p1p5/3pp3/7q/... w     |
  |  -751   |    -746.50    |     -752      | 6k1/p1p5/3pp3/.../...5q2/... |
  |  -731   |    -758.67    |     -759      | 6k1/p1p5/3pp3/.../1q6/... |
  |  -737   |    -796.09    |     -795      | 6k1/p1p5/3p4/4p3/2q5/... w |
  Mean |NNUE − SF18| = 18cp. **NNUE matches SF18 within ~30cp on every real
  queen-down position.** Network correctly evaluates queen-down at ~-750cp.
  THE NETWORK IS NOT MATERIAL-BLIND IN-DISTRIBUTION.

DIAG 4 — quant rounding (Python // vs Rust integer /):
  | pos               | int_out | Py //  | Rust /  | float cp | diff   |
  |-------------------|---------|--------|---------|----------|--------|
  | Startpos          |     346 |    +8  |    +8   |   +3.65  |    0   |
  | W queen missing   |    1164 |   +28  |   +28   |  +24.08  |    0   |
  | W rook missing    |   -1079 |   -27  |   -26   |  -30.30  |   -1   |
  | Endgame K+R vs K  |    6084 |  +149  |  +149   | +152.13  |    0   |
  | W up Q+R bare K   |     433 |   +10  |   +10   |  +18.60  |    0   |
  Py // differs from Rust / by 1cp only on negative integer_out (rook miss).
  The 8.6cp gap on "W up Q+R vs bare K" is a genuine quantization residual
  (low piece count, large per-piece weights), NOT a Python/Rust mismatch.
  gate_cd.py's "FQ-gap > 5cp" threshold flagged this but it is NOT an artifact.

REVISED VERDICT — Gate C "FAIL" was driven by an OOD test position, not by a
deficient network:

  - The network correctly evaluates queen-down positions at ~-750cp on REAL
    in-distribution positions (DIAG 3).
  - The startpos-minus-queen test position is unrealistic: all pieces at
    starting squares except one queen. This configuration never occurs in
    real games. The network's strong "undeveloped piece" feature for d1
    queen dominates the residual material signal in this artificial setup.
  - Knight removal from startpos already showed -164cp delta (DIAG 2) —
    direct evidence the network DOES learn material when the positional
    feature doesn't dominate.

  The OOD-test diagnosis (originally proposed as F4) is CONFIRMED by DIAG 3.
  The "data-distribution / WDL blending" path (F1) is NOT NEEDED.

  **Gate C as written is NOT a useful gate for this network.** The startpos-
  minus-queen test is fundamentally OOD. A better Gate C uses real game
  positions like the DIAG 3 set — and the network passes those decisively.

  RECOMMENDATION: revise Gate C to use mid-game material-imbalanced positions
  drawn from SF18 .plain (or equivalent), then re-check. If revised Gate C
  passes, proceed to SPRT with expE-30 as the gate-cleared candidate.
  No retrain needed pending revised-gate result.

**CORRECTED GATE D (June 2, 2026) — sibling ranking on REAL mid-game positions**

Setup: 10 positions from SF18 .plain with ply>=20, both sides have queens,
|score|<=200cp (roughly balanced), in-check excluded. For each: top quiet move
per NNUE float static eval (negated through child positions) vs top quiet move
per engine `--no-nnue` depth-1 (PeSTO).

Result: **1/10 agreement on REAL mid-game positions.**
  Baseline (old startpos-like Gate D on d2-evalonly): 0/10
  Baseline (expD, l0w clip ±0.06):                    2/10
  expE (this run):                                    1/10

Deployment gate (re-verified before this check):
  md5 engine/pyro.nnue                  = 23bfcd331411b8b9c6a05191d42caef5
  md5 engine/target/release/pyro.nnue   = 23bfcd331411b8b9c6a05191d42caef5
  MATCH: YES. Deployed net is still pyro-expE-30. Unchanged since Gate B.

Interpretation: this is the "correct absolute material, scrambled relative
ranking" scenario. DIAG 3 confirmed expE prices queen-down at ~-750cp matching
SF18 (correct ABSOLUTE eval). But on quiet move ranking within a position,
NNUE picks the same top quiet move as PeSTO only 1/10. Either:
  (a) NNUE and PeSTO are different evaluators and legitimately disagree on
      the best quiet move (PeSTO is not ground truth; SF18 would be a better
      reference). 1/10 vs PeSTO is not the same as 1/10 vs the "truth".
  (b) NNUE's within-position eval landscape is noisy (delta-per-move ~10cp
      vs PeSTO's smoother landscape), and small noise re-orders the top
      move on most positions.
  (c) The test positions are biased — SF18 picked them mid-game where SF18's
      preferred move was a CAPTURE or CHECK, so "top quiet move" is
      a second-class decision both engines find hard.

The check was designed to predict SPRT outcome. 1/10 is no better than the
prior contaminated/lost baselines. Per protocol, STOP and ask planning before
running SPRT. SPRT NOT RUN.

**SF18-REFERENCED SIBLING SPEARMAN (June 2, 2026) — informational, not a gate**

15 mid-game positions (ply>=20, both sides have queens, |score|<=200cp), all
25 quiet child moves per position evaluated by both expE (float) and Stockfish
depth=10. Spearman correlation of NNUE-child-eval vs SF18-child-eval, computed
per position then averaged.

  Mean rho across 15 positions:  +0.155
  Median:                        +0.151
  Min / Max:                     -0.116  / +0.542
  Fraction rho > 0.3:            0.20  (3/15)
  Fraction rho > 0.0:            0.73  (11/15)

Interpretation: real positive signal, well below the 0.3 threshold for "tracks
SF18". Network's within-position ranking is noisy but not random. Pre-registered
prediction: SPRT will likely land BETWEEN the old 0.7% floor and a passing
score — informative but probably not a pass. Whatever the number, this is the
first SPRT measuring the NET (continuous output, material-correct on
in-distribution positions) rather than the plumbing.

**SPRT EXPE (June 2, 2026) — first trusted SPRT in project history**

Config: pyro-expE-30 vs pyro --no-nnue (PeSTO), TC=10+0.1, SPRT elo0=0 elo1=10,
α=β=0.05, adjudication draw@move40 score=10, resign movecount=5 score=1000,
cutechess concurrency=1 -recover, color-paired openings (-repeat).

Pre-flight: deployment md5 verified match (23bfcd33...) before launch.

Result: **H0 accepted at 60 games.**
  W-L-D:                       0 - 58 - 2
  Score%:                      1.7%
  Elo difference:              -708.3
  LOS:                         0.0%
  DrawRatio:                   3.3%
  SPRT llr:                    -2.95 (lbound -2.94)
  White vs Black:              29-29-2 (no color bias)
  Pyro-NNUE as White:          0W-29L-1D
  Pyro-NNUE as Black:          0W-29L-1D

Loss decomposition:
  Mated:                     37  (21 black-mated + 16 white-mated)
  Adjudicated (>=1000cp):    21  (8 black-adj + 13 white-adj)
  Drawn (3-fold repetition):  2

Zero wins. Equal losses as both colors. All decisive games ended in mate or
material-collapse adjudication — the network never built nor defended a
position. This is the first SPRT in the project's history that measures
the NET, not the plumbing:
  - Gate A confirmed continuous output layer (no binary l1w)
  - DIAG 3 confirmed absolute material correct on in-distribution positions
  - Deployment md5 verified at launch
  - SPRT ran to completion without manual bailout

The score is 1.7% — slightly above the old contaminated 0.7% floor but in the
same regime: no significant improvement over PeSTO. This is the trusted
number we've been circling for four experiments. The conclusion is now
grounded: expE is the first CORRECTLY-TRAINED net, and at this architecture
(256 neurons + 20M positions + CReLU + WDL=0 + no king buckets) it is
materially weaker than PeSTO.

What this rules in (with evidence):
  - The training pipeline (data → bullet → quantization → engine) is sound.
  - The loss convention fix worked as designed (Gate A).
  - The network learns absolute material from in-distribution positions
    (DIAG 3) but learns relative ranking with too much noise (Spearman 0.155,
    sibling vs PeSTO 1/10, SPRT 1.7%).

What this does NOT rule in or out:
  - 512 neurons could fix ranking noise OR could be no better.
  - WDL>0 blending could fix or worsen.
  - SCReLU could help or hurt (still unknown).
  - 100M positions instead of 20M could fix or be marginal.
  - King buckets could matter or not.
  - The Tal-modifier post-hoc approach (use NNUE for absolute eval but
    overlay PeSTO+Tal for tactical sharpness) was not tested.

Next planning decision is now well-posed. The cheapest informative next
experiment is the one that changes the variable most likely to improve
within-position ranking. The Spearman 0.155 + SPRT 1.7% combination is the
new baseline against which next experiments are measured.

**Experiment B (512clip10) — UNTESTED, caution warranted**
- Training complete (SB30, loss=0.003370). Checkpoint at
  bullet/checkpoints/pyro-d2-512clip10/pyro-d2-512clip10-30/. Not converted.
- RISK: clip10 is confirmed harmful at 256 neurons. If the root cause is
  l1w range (not neuron count), 512clip10 will fail the same way. The one
  variable for Experiment B was 512 neurons; clip10 is held constant from
  a CATASTROPHICALLY BAD baseline. Do NOT run SPRT without planning sign-off.
- PROPOSED alternative: Experiment C = 512 neurons + DEFAULT clip. This
  cleanly tests capacity without the clip10 confound.

### FIX APPLIED (May 31, 2026) — robustness 96/96 green
Two changes were required in `engine/src/search.rs`, `best_move_nodes`:

**Fix 1 (approved): root move loop reorder**
- Moved `if score >= beta` and `if score > alpha` blocks to BEFORE the
  `(nodes >= limit || time_up) && best.is_none()` check. Score is now committed
  to `best` before the budget abort fires. Fixes `go nodes 1`: first move's
  result is captured even when the node counter trips immediately.

**Fix 2 (discovered during verification): soft-check depth guard**
- Added `depth > 1 &&` to the soft time check at the top of the depth loop
  (was: `if time_up(...)`, now: `if depth > 1 && time_up(...)`).
- Root cause: `go movetime 1ms` and `go movetime 10ms` both compute a 1ms
  deadline (`N.saturating_sub(50).max(1) = 1ms`). Thread setup + accumulator
  construction takes >1ms, so the soft check fired at depth=1 BEFORE any
  iteration ran. `best_overall = None` guaranteed. Fix: depth=1 always runs.
- This also fixes the SPRT-irrelevant `movetime 1` / `movetime 10` cases.

**Result**: robustness check 96/96 PASSED. Stalemate test position replaced
with `7k/8/6R1/8/8/8/8/1K6 b - - 0 1` (Kh7 only legal move).

### CRITICAL CORRECTION (May 30, 2026) — stale weights invalidate prior results
The engine loads pyro.nnue from target/release/, but bullet_to_pyro_nnue.py
only wrote engine/pyro.nnue. From ~May 7, every SPRT ran a stale d1v3 net, not
the config under test. Separately, nnue_verify.py loaded the NEW net in Python
while the engine subprocess ran the OLD net — so every "Python vs engine eval"
discrepancy (including the +492cp depth-1 ghost chased across ~5 experiments)
was a two-different-networks artifact, not a real phenomenon. Consequence: the
"Phase D1 FINAL VERDICT: capacity bottleneck" and "D2 Step 1: go to 512" are NOT
established — they rest on contaminated SPRTs. We are at experiment ZERO with a
now-fixed harness, not three experiments deep.

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
│   │   ├── validate_nnue_rust.py      # SPRT validator via cutechess-cli (real SPRT, preflight, 10+0.1 TC)
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
python -m scripts.validate_nnue_rust          # real SPRT via cutechess-cli, 10+0.1 TC
python -m scripts.validate_nnue_rust --games 2000  # override game cap
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
- CRITICAL (found May 30): engine loads pyro.nnue from target/release/, not
  engine/. Converter now mirrors to BOTH paths. ALWAYS md5-verify the two
  match before SPRT. This bug silently contaminated every SPRT since ~May 7.
  converter mirrors both paths: CONFIRMED (bullet_to_pyro_nnue.py write_nnue +
  exe_dir_copy logic present and verified).
- FIXED (May 31): `go nodes N` and `go movetime N` (N ≤ 50ms) returned
  bestmove (none). Two root causes fixed: (1) root move loop budget check fired
  before first score was committed to `best` → reordered score-commit first;
  (2) soft time check at depth=1 fired before any iteration ran for 1ms
  deadlines → guarded with `depth > 1`. Robustness check now 96/96 green.
  `go wtime/btime` (SPRT path) was never affected. `one_legal_move` (none) at
  depth 1 was stalemate — not a bug; test FEN replaced with a real forced-move
  position.
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

G2. Lazy SMP multithreading ✅ VALIDATED (June 2026 baseline run)

    Session 1: TTable thread-safe (Vec<TTSlot>, paired AtomicU64s,
    XOR-checksum torn-entry detection), node counter AtomicU64,
    stop flag AtomicBool plumbed through ab_search/quiescence.
    Session 2: std::thread::scope spawns N-1 worker threads (smp_worker),
    each runs independent ID loop sharing the TT. UCI Threads option added.
    rust_engine.py sends setoption Threads 4 at startup.

    NO-OP PROOF (June 5, 2026): 10/10 positions byte-identical at Threads=1.
    DEPTH CHECK: startpos movetime 5000: Threads=1→depth12, Threads=4→depth13.
    +1 ply confirmed (within predicted 1-2 ply range).

    RUN B (June 5, 2026): Threads=4 vs Threads=1 self-play, 100 games.
      42W-44L-14D = 49.0%, Elo -7 ± 64. Concluded "SMP neutral" — WRONG.
      A/B self-play understates SMP because BOTH sides gain the extra ply, so
      the advantage cancels. The SF-ladder (fixed opponent) is the right test.

    SF-LADDER VALIDATION (June 2026 verified baseline, anchor commit b8e25f0):
      T1: 44.3% vs SF-1700 (−40 ± 47), 33.8% vs SF-1900 (−117 ± 49) → ~1721.
      T4: 61.0% vs SF-1700 (+78 ± 64), 44.5% vs SF-1900 (−38 ± 68) → ~1820.
      SMP delta: +117.8 Elo vs SF-1700 (CIs disjoint → significant),
      +78.8 Elo vs SF-1900 (same direction, suggestive). Matches the
      "+50-150 Elo on 4-core hardware" prediction.
      VERDICT: ✅ VALIDATED. SMP is POSITIVE, not neutral.

    1835 MYSTERY RESOLVED: old 1835 ≈ T4 ~1820. It was a Threads=4 number;
    June-5's "cannot reproduce" compared a single-thread rebuild (~1721)
    against a 4-thread historical figure. The IID/LMP/dep-NMP deletion was
    therefore likely chasing a thread-count artifact — flag for the re-add fork.

    Expected impact (confirmed): +80-118 Elo on the SF-ladder at 4 threads.

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

G9. Sacrifice-seeking in search — TRIED (June 4-5, 2026), FAILED Elo floor
    Code: TUNE_SPEC_BONUS UCI param (default 0 = byte-identical to baseline).
    Gate (SEE<0 AND to-sq in enemy king zone AND >=2 STM attackers in zone
    excluding mover) lifts gated sacs from ~3000 to ~5000 ordering score
    when SPEC_BONUS>0. STEP 0 no-op proof PASS (10/10 identical at default).
    STEP 1 baseline aggression on Apr-16 PGNs (200 games vs SF-1700+1900):
      sac_rate=73.5%, kz_sac_rate=25.5%, sacs/g=1.22, kz_sacs/g=0.32
    STEP 2 gauntlet @ SPEC_BONUS=2000, 100 games each @ 10+0.1:
      vs SF-1700: 13W-85L-2D = 14.0%  (Elo diff -315; was +123 baseline; Δ -438)
      vs SF-1900: 12W-87L-1D = 12.5%  (Elo diff -338; was -53  baseline; Δ -286)
      implied Pyro Elo ~1473 (was ~1835; Δ -362; floor was -40)  ← BLOWN
      Style: sac_rate 92.5%, kz_sac_rate 37.5%, sacs/g 1.99, kz_sacs/g 0.45
              (kz_sac_rate +47% relative — meets style target)
    STEP 3 verdict: CLAUSE (1) style PASS, CLAUSE (2) Elo FAIL by 9x the floor.
    FINAL VERDICT: REJECTED — ordering-bonus is the wrong instrument.
    It biases WHAT GETS SEARCHED, not what calculation confirms. Default
    SPEC_BONUS=0 stays (byte-identical to baseline). Do not retry tightened.
    The dynamic-eval tiebreak approach (Experiment 2, DYNAMIC_BONUS in eval)
    is the correct instrument — it can only break ties between near-equal moves.

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

Phase G is COMPLETE. All items either done or consciously closed:
- G9 (sacrifice-seeking): ❌ REJECTED — ordering-bonus is wrong instrument (-362 Elo). Code dormant at SPEC_BONUS=0.
- G11 (anti-quiet): DEFERRED — would cost Elo for marginal style gain
- G14 (theatrical timing): SKIPPED by user preference
- Deployment: configs ready (Netlify + Railway), deploy when ready

Active development: G2 Session 2 (Lazy SMP) → Experiment 2 (DYNAMIC_BONUS eval tiebreak) → G13/G15 personality.

---

## Phase D — NNUE v2 (SHELVED — awaiting GPU/CUDA fix)

### Status: pipeline is correct, CPU-only hardware insufficient

expE-30 (first trusted net) scored 1.7% vs PeSTO (SPRT, -708 Elo).
The pipeline is sound (loss convention fixed, deployment verified),
but 256-neuron / 20M positions / CPU-only training cannot compete.
NNUE resumes when the RTX 3050 CUDA/cudarc mismatch is resolved.
Until then the live engine runs PeSTO+Tal (--no-nnue flag required).

### Original goal: Pyro at 3000+ CCRL with personality intact

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

### Phase D1 progress (as of May 4, 2026):
- [x] Data generator fixed (depth 6, --no-nnue, quiet filter,
      pipe format, --target flag, progress reporting)
- [x] 20M positions generated (selfplay_d6_combined.plain, ~1.3 GB)
- [x] Incremental accumulator (acc_update, threaded through
      full search stack, 0 from_board rebuilds during search)
- [x] SCALE updated 400→600 in nnue.rs
- [x] Homebrew trainer abandoned — float CReLU saturation creates
      structural ceiling; queen eval capped at ~508 cp (0.56× expected);
      three full training runs all failed SPRT catastrophically.
      See memory/feedback_nnue_homebrew_trainer_ceiling.md.
- [x] Validator hardened: real SPRT via cutechess-cli (elo0=0, elo1=10,
      α=β=0.05), TC=10+0.1 matches gauntlet, preflight rejects missing/
      corrupt pyro.nnue before launch, -recover for crash safety
- [x] Bullet integration — Session 2 complete (May 5, 2026):
      - Training script: bullet/examples/pyro.rs (HIDDEN=256, CReLU, custom loss)
      - Bullet binary: bullet/target/release/examples/pyro.exe (CPU backend, CUDA 13.2 too new)
      - Converter: backend/scripts/bullet_to_pyro_nnue.py (strips 62-byte "bullet" footer trailer)
      - Training run 1 (FAILED): 30 superbatches, loss 0.0345→0.0165 (plateaued).
        SPRT: 4W-24L-2D = 16.7% after 30 games. Root cause: BulletFormat encoding bug —
        converter used ABSOLUTE piece colors (white=0, black=1) and RAW squares instead
        of STM-normalised encoding. Bullet's Chess768 input always maps bit3=0→STM pieces,
        bit3=1→NSTM pieces. With absolute colors, all black-to-move positions had inverted
        STM/NSTM features. ~10M of 20M positions were garbage. Score was white-relative
        instead of STM-relative. Result was white-relative instead of STM-relative.
      - Bug fixed in convert_plain_to_bullet.py (May 5, 2026):
        - bit3=0 for STM's pieces (black pieces when black to move)
        - bit3=1 for NSTM's pieces (white pieces when black to move)
        - squares mirrored (sq^56) when black to move, then sorted by ascending sq
        - score = eval_stm (already STM-relative, removed -eval_stm for black)
        - result flipped for black to move (0↔2)
      - Re-encoded 20M positions (selfplay_d6.data). Retrained as pyro-d1v2 (SB30).
      - SCALE fix in pyro.rs loss: (output/400).sigmoid() makes model output centipawns
        directly, matching engine's output/(QA*QB) formula. This worked correctly —
        queen eval 966 cp (was 508 cp homebrew). Loss fix is unrelated to STM bug.
- [x] Re-encode data with STM-normalised converter (done May 5, 2026)
- [x] Retrain Bullet on corrected data — pyro-d1v2, SB30, loss=0.01574
- [x] Convert SB30 quantised.bin → pyro.nnue (394,762 bytes)
- [x] SPRT v2 (PeSTO data): 34% over 100+ games (~−130 Elo vs PeSTO). Pipeline proven.

### Phase D1.5: SF18 re-evaluation — COMPLETE ✅ (May 5-6, 2026)
- [x] SF18 re-eval: 20,000,365 positions, 0 errors, 17.35h at 320 pos/s
        Output: C:/torch_data/selfplay_sf18_d12.plain (1.3 GB)
- [x] Converted to Bullet format: C:/torch_data/selfplay_sf18_d12.data (610.4 MB, 876s)
- [x] Retrained as pyro-d1v3 (SB30, loss=0.01607)
- [x] SPRT v3 (SF18 data): ~32% over 47 games — NO IMPROVEMENT over v2

### Phase D1 — FINAL VERDICT: FAIL ❌

> ⚠️ CONTAMINATED — see 'CRITICAL CORRECTION (May 30)' in the NNUE EXPERIMENT PROTOCOL section. The SPRTs behind this verdict ran stale weights. Do not treat the capacity conclusion or the 512-neuron plan as confirmed.

Both v2 and v3 score ~32-34% vs PeSTO+Tal. Data quality is NOT the bottleneck.

| Version | Data | Loss  | Queen-up | SPRT  | Games |
|---------|------|-------|----------|-------|-------|
| v2      | PeSTO depth-6 | 0.01574 | 966cp | 34%  | 100+  |
| v3      | SF18 depth-12 | 0.01607 | 966cp | ~32% | 47    |

Root cause analysis (rank-ordered bottlenecks):
1. **Network capacity** — 256 hidden neurons is too small. PeSTO+Tal encodes
   decades of chess knowledge. A 256-neuron NNUE from 20M self-play positions
   cannot match it. D2 must increase to 512+ neurons.
2. **Game outcome quality** — depth-6 self-play WDL is too noisy; NNUE tries
   to learn from games played by a depth-6 engine it can't yet beat.
3. **Data volume** — 20M is the floor; 100M+ needed for generalization.
4. **Inference cost** — NNUE may be slower than PeSTO at 10+0.1 TC; worth
   profiling before D2.

All training data, weights, and scripts preserved for D2 ablations:
  - backend/data/selfplay_d6_combined.plain (PeSTO evals, original)
  - C:/torch_data/selfplay_sf18_d12.plain   (SF18 evals)
    (July 2026: only the SF18-d12 set — .plain + .data — survives in C:/torch_data;
    the re-encoded selfplay_d6.data was deleted)
  - bullet/checkpoints/pyro-d1v2/           (v2 weights)
  - bullet/checkpoints/pyro-d1v3/           (v3 weights)

### Phase D2: Scale up (ACTIVE NEXT — target: 2200+ Elo)

> ⚠️ CONTAMINATED — see 'CRITICAL CORRECTION (May 30)' in the NNUE EXPERIMENT PROTOCOL section. The SPRTs behind this verdict ran stale weights. Do not treat the capacity conclusion or the 512-neuron plan as confirmed.

**First objective: beat PeSTO at all. Then worry about 2600.**

D1 verdict forces a resequencing. D2 must first prove NNUE can beat
PeSTO before chasing D2's original 2600-2800 Elo targets. The
bottleneck is network capacity, not architecture sophistication.

**D2 Step 1 (immediate): 256 → 512 hidden neurons, same data**
- Change HIDDEN_SIZE to 512 in bullet/examples/pyro.rs
- Update engine/src/nnue.rs: HIDDEN_SIZE=512, layer sizes, weight loading
- Retrain on existing C:/torch_data/selfplay_sf18_d12.data (20M SF18 positions)
- SPRT vs PeSTO: if score crosses 50%, the capacity hypothesis is confirmed
- Expected: +50-150 Elo from capacity alone

**D2 Step 2 (if Step 1 passes): SCReLU + 100M positions**
- Switch .crelu() → .screlu() in pyro.rs; update nnue.rs activation
- Generate 100M positions at depth 8 (5× current data, deeper games)
- Retrain, SPRT vs PeSTO baseline

**D2 Step 3 (if Step 2 passes): king buckets**
- Add 8 king buckets (king position bins the input features)
- 768×8 → 6144 input features with horizontal mirroring
- Only add this complexity after plain 512+SCReLU is validated

Architecture for Step 1: (768→512)×2→1
- 512-neuron accumulator (double D1)
- SCReLU activation (Squared Clipped ReLU — better gradient flow)

Data: start with existing 20M SF18 positions, scale to 100M+ after Step 1 confirms capacity helps

SIMD optimization:
- AVX2 vectorized accumulator updates
- i16 weights for accumulator layer
- i8 weights for output layers
- Quantization-aware training in Bullet

Expected Elo after full D2: ~2200-2600

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

<!-- END verbatim archive of CLAUDE.md @ c26d387 -->

## IID re-add experiment — CLOSED NEUTRAL (July 2, 2026)

The IID re-add experiment (July 2, 2026) is CLOSED as NEUTRAL. IID was re-implemented
in engine/src/search.rs behind UCI param IID_ENABLE (AtomicBool, default false) with
the SE-gate fix (original_tt_entry captured before IID runs, so singular extension
cannot fire on the shallow depth-2 entry IID writes). No-op proof passed (10/10
byte-identical at default; 2/10 differ when on). It was then measured — 600 games
total at Threads=1, TC 10+0.1, vs the T1 anchor (44.3% vs SF-1700, 33.8% vs SF-1900):
  - Self-play IID-on vs IID-off, 200 games (two 100g invocations): 50.5% and 47.0%,
    pooled 48.75% → null.
  - vs SF-1900, 200 games (two invocations): 37.0% and 31.5%, pooled 34.25% vs anchor
    33.8% → null.
  - vs SF-1700, 200 games (two invocations): 46.5% and 60.5%, pooled 53.5% vs anchor
    44.3% → nominal +9pp, but the two identical-config halves disagree by more than
    the effect size (~97 Elo apart), it's a single ~1.9σ leg out of three instruments,
    and it is NOT credited.
VERDICT: IID_ENABLE stays default FALSE; code stays dormant (the SE fix is retained —
it is correct code). Likely mechanism: killers+countermove+history already order
TT-miss nodes well enough that the depth-2 sub-search's benefit ≈ its overhead at
fast TC. DOWNSTREAM: June data showed LMP-without-IID is catastrophic, so with IID
neutral, LMP-alone is predicted to fail → LMP and dep-NMP are PARKED (not next).
Elo-hunting the trio is off-mission. Next active experiment: DYNAMIC_BONUS.
Note: the two script invocations overwrote logs (tee without -a) but PGNs appended;
raw data is backend/scripts/gauntlet/results/iid_experiment/ (200-game PGNs).

## DYNAMIC_BONUS=20 experiment — CLOSED, STYLE CLAUSE FAILED (July 4, 2026)

The DYNAMIC_BONUS experiment (PATH TO THE GOAL item 2) is CLOSED. The term was
implemented in engine/src/search.rs behind UCI param DYNAMIC_BONUS (default 0,
no-op proof passed), a capped eval-side bonus rewarding initiative toward the
enemy king (attackers standing on the board, heavy pieces on files), hard-capped
so it only breaks near-ties. Measured at DYNAMIC_BONUS=20, Threads=1, TC 10+0.1,
concurrency=1, no book, 200 games vs the T1 anchor (~1721; agg 77.2% /
kz_sac 31.0%).

VERDICT: Clause 2 (Elo floor) PASS. Clause 1 (style: kz_sac_rate must not drop)
FAIL. Param stays dormant at default 0.

Elo results (clause 2 — PASS):

| Opponent | Score | Elo diff | Anchor | Delta |
|----------|-------|----------|--------|-------|
| SF-1700  | 48-46-6 → 51.0% | +6.9 ±66.7 | 44.3% | +6.7pp |
| SF-1900  | 34-56-10 → 39.0% | −77.7 ±66.9 | 33.8% | +5.2pp |

Implied ~1765 vs anchor ~1721 — nominal +44, within noise. The Elo floor
comfortably held; if anything the term was slightly positive for strength.

Style results (clause 1 — FAIL):

| Leg | agg% | kz_sac% | Anchor kz_sac |
|-----|------|---------|---------------|
| vs SF-1700 (100g) | 76.0% | 15.0% | 31.0% |
| vs SF-1900 (100g) | 82.0% | 26.0% | 31.0% |
| Pooled (200g)     | 79.0% | 20.5% | 31.0% |

kz_sac_rate dropped 31.0% → 20.5% pooled (−10.5pp, ~2.7σ), with BOTH legs below
the anchor. This is the opposite of the design intent and fails clause 1.

MECHANISM: the term pays for attackers standing on the board and heavy pieces on
files; a sacrifice removes both, so it incentivizes holding pressure over cashing
in. Initiative-presence ≠ sacrifice incentive.

STRUCTURAL NOTE: total eval-side king-attack budget (~≤150cp) can never price a
~300cp piece sac as compensated; sacs come only from search resolving the attack.
DO NOT retry larger caps — bigger cap = stronger anti-sac incentive.

OPEN DECISION (not made here): a compensation-gated v2 (bonus applies only when
material was invested) vs moving the dynamic-style goal entirely to the
personality layer (item 4). Raw data:
backend/scripts/gauntlet/results/dynamic_bonus_2026-07/ (two 100-game PGNs;
per-leg style computed with backend/scripts/aggression_rate.py).

## COMP_BONUS — CLOSED, eval-side beauty exhausted (July 5, 2026)

Final eval-side beauty experiment: compensation-gated attack term inverting the
DYNAMIC_BONUS incentive — pay for attack signals ONLY when material-down
(100..350cp window, queen-led, >=2 non-pawn zone attackers), so the position
AFTER a sacrifice holds eval value. TUNE_COMP_BONUS in evaluate() (HCE path),
white-relative, graduated min(attackers,4)*cap/4, hard cap; measured at cap=100.
DYNAMIC_BONUS untouched at 0 (one variable). Code at commit ce92f63; base 0f19f77.

NO-OP PROOF (both halves):
- Default (0): 10/10 byte-identical bestmove + final info line vs the preserved
  HEAD binary (0f19f77) on the standard suite, depth 8, --no-nnue both sides.
- Gate-alive: the standard suite is material-EQUAL, so the g2 gate cannot fire
  there. On 3 material-imbalanced attack FENs, COMP_BONUS=100 changed the
  reported score on 2/3 (piece-down hunt -261 -> -231; black-down attack
  -95 -> -112; the third resolved to forced mate, masking the term).

PREDICTION (written before games): pooled kz_sac_rate 31.0% -> 35-42%; sacs_pg
up from 1.30; implied Elo within -20..+15 of ~1721; no crashes.
OUTCOME: mostly did NOT hold. kz_sac 32.7% (below range); sacs_pg 1.23 (down,
not up); Elo +27 nominal (floor held, upper bound exceeded); no crashes (one
"bestmove (none)" loss, game 61 vs SF-1700 — identical event exists in the
June baseline log, pre-existing ~1/200-300 game edge, not the tripwire).

GAUNTLET (clean 200 games, TC 10+0.1, Threads=1, --no-nnue, COMP_BONUS=100):
| Leg              | W-L-D    | Score | Elo diff   | Implied |
|------------------|----------|-------|------------|---------|
| vs SF-1700 (100) | 49-40-11 | 54.5% | +31 +/- 64 | ~1731   |
| vs SF-1900 (100) | 30-67-3  | 31.5% | -135 +/- 73| ~1765   |
Implied (leg average, baseline method): ~1748 vs anchor ~1721.
Legs disagree in sign vs anchors (SF-1700 +10.2pp, SF-1900 -2.3pp) — the
single-instrument scatter of working rule 8, same pattern as IID.

STYLE vs T1 anchor:
| Metric        | Anchor | SF-1700 | SF-1900 | Pooled (199g) |
|---------------|--------|---------|---------|---------------|
| aggression    | 77.2%  | 76.8%   | 73.0%   | 74.9%         |
| kz_sac_rate   | 31.0%  | 39.4%   | 26.0%   | 32.7%         |
| sacs_per_game | 1.30   | 1.25    | 1.21    | 1.23          |
| kz_sacs_pg    | 0.35   | 0.43    | 0.29    | 0.36          |

CLAUSE VERDICTS (pre-committed):
1. DYNAMIC UP — FAIL. Pooled kz_sac_rate 32.7% < 35% threshold. All style
   metrics within noise of anchor: the term did approximately NOTHING to style
   (unlike DYNAMIC_BONUS, which actively inverted sacs).
2. SENSIBLE HELD — PASS. Implied ~1748 >= 1701 floor.

BRACKETING ARGUMENT — eval-side sac incentives PROVEN exhausted: the two
instruments bracket the design space. Presence-reward (DYNAMIC_BONUS: pay for
attackers standing on the board) INVERTED sacs (31.0 -> 20.5%). Compensation-
reward (COMP_BONUS: pay only after material is invested) was INERT (32.7% vs
31.0%). Neither direction moves the sac rate up; sacs come from search
resolving attacks, not from leaf bonuses. Both params dormant at 0, no-op
proven. Beauty work moves to the personality layer (G13/G15).

SIDE-FINDING (uncredited): both dormant terms were nominally Elo-POSITIVE at
the caps tested (DB=20 +44, CB=100 +27 vs the ~1721 anchor) — neither credited
(single-leg scatter exceeds effect; see rule 8) but both are SPSA candidates
if the project ever Elo-hunts. Do not reopen for style.

INCIDENT (phantom process): the first gauntlet invocation was reported
"killed" by the harness but the bash/cutechess tree survived detached and ran
to completion; a continuation started on that false premise overlapped it for
53 minutes (concurrency=1 violated, interleaved PGN appends, ~86 game records
mangled). Contaminated data quarantined in
results/comp_bonus_2026-07/contaminated_run1/ (NOTE.md documents it); the
verdict uses only the 82 pre-overlap games (validated against the run log:
40-32-10) plus 118 games played after verified process cleanup. Countermeasure:
working rule 9 + tasklist guard in run_comp_bonus_gauntlet_finish.sh.

Raw data: backend/scripts/gauntlet/results/comp_bonus_2026-07/.

## Phase D reopened — capacity ladder, session 1 (July 12, 2026)

First training session on the GPU-unblocked pipeline (bullet cebc78a0, RTX
3050, ~6-15 min per SB30 run). Tested the CAPACITY axis of the expE failure
hypothesis ("256 neurons + 20M positions is under capacity for move-ranking").
One variable per candidate vs expE. NNUE remains SHELVED throughout.

CANDIDATES (all: 768→Hx2→1, eval-only WDL=0, stock loss, SB30, batch 16384,
cosine 1e-3→1e-5, 20M SF18-d12 positions):
- Candidate 0 — pyro-gpu (last night's GPU parity run of the exact expE
  config, HIDDEN=256, CReLU). Final loss 0.0033.
- Candidate A — pyro-gpu-512 (HIDDEN 256→512, only change). Loss 0.0033.
- Candidate B — pyro-gpu-screlu (CReLU→SCReLU, only change). Loss 0.0033.
- Candidate C — 512+SB60: NOT TRAINED (gated on A gating well; A did not).

All three converged to per-batch losses identical to 4-5 significant digits —
the loss floor is target-noise dominated and NONE of the changes fit the data
better. Loss recorded per protocol but not used for decisions.

GATE TABLE (gate_ladder.py — new width/activation-parameterized suite off
raw.bin; one shared SF18-d10 cache, 15 midgame positions × ≤25 quiet children):

| candidate            | Gate A (l1w sat) | Gate M (Q-down ratio) | Spearman rho |
|----------------------|------------------|-----------------------|--------------|
| 0 (GPU-256-CReLU)    | PASS 0.0%        | PASS 1.03             | +0.125       |
| A (512-CReLU)        | PASS 0.0%        | PASS 1.03             | +0.045       |
| B (256-SCReLU)       | PASS 0.0%        | PASS 1.03             | +0.213       |
| (expE reference)     | PASS             | PASS                  | +0.155       |

PREDICTIONS (written before training) vs outcomes:
- C0 ≈ expE's +0.155: got +0.125 — held approximately (GPU parity confirmed;
  rho gate has position-sample noise, same profile).
- A: "capacity binding → rho > 0.25; data binding → loss flat, rho ~0.15":
  loss flat AND rho fell to +0.045 — capacity branch REFUTED at this data size.
- B: "+0.05-0.10 over 0.155": +0.213 — HELD.

VERDICT (pre-committed decision table): best rho +0.213 < 0.25 → STOP, no
SPRT. Capacity was NOT the (only) bottleneck at 20M positions. Doubling width
made ranking WORSE (more parameters fitting the same noisy eval targets);
richer activation (SCReLU) gave the only real improvement (+0.09 rho) and is
the strongest single-variable lever found so far.

RECOMMENDATION for session 2 — the DATA axis, carrying SCReLU forward:
more positions and/or a better mix (the 20M set is eval-only d12 self-play);
consider WDL blending. SCReLU should be the base activation for the next
ladder (it is strictly better here and is the standard modern choice), with
one CReLU control. NOTE: a SCReLU net needs an inference change in
engine/src/nnue.rs before any SPRT (square the clipped accumulator, output
renormalised /QA — see bullet examples/simple.rs); HIDDEN=256 stays, so it is
a small, branch-scoped change.

TOOLING added this session (durable in git):
- backend/scripts/gate_ladder.py — parameterized gate suite (Gate A + DIAG-3
  material pricing + Spearman) for any width/activation, off raw.bin.
- bullet_to_pyro_nnue.py --hidden N — converter width parameter (warns that
  the engine loader is 256-only).
- bullet_port/pyro_gpu_512.rs, pyro_gpu_screlu.rs — trainer variants (durable
  copies; also registered in the Cargo.toml snippet).
- engine/src/nnue.rs finding: HIDDEN_SIZE is a compile-time const (line 12)
  with const-sized arrays; a 512 build = change the constant in a branch
  build. Live engine untouched.

Integrity: engine/pyro.nnue + target/release/pyro.nnue md5
23BFCD331411B8B9C6A05191D42CAEF5 before and after session (never touched;
all conversions went to scratch). Checkpoints: bullet/checkpoints/
pyro-gpu-512/, pyro-gpu-screlu/. Gate log: scratchpad gate_run.log
(gate table reproduced above in full).

## Phase D session 2a — WDL blending: axis DEAD on this data (July 12, 2026)

Question: does blending game-outcome (WDL) signal into the existing 20M
eval-only SF18-d12 set lift move-ranking? Recon first, then a 3-point WDL
ladder on the SCReLU-256 base (candidate B config, one variable = WDL weight).

RECON (all premises verified before training):
- Q1, result-field provenance: the field is REAL and STM-correct. 100k-record
  stride sample of the .data: 26.1% STM-win / 48.1% draw / 25.8% STM-loss,
  zero out-of-range bytes. Zero label inversions at |white-POV eval| >= 2500
  (0/128 white-crushing, 0/551 black-crushing); in-game mate-score
  trajectories always match the label. Perspective chain verified in code
  (generation → reeval passthrough → converter STM flip at
  convert_plain_to_bullet.py:51-58) and empirically (stm-conditioned
  agreement at ±700).
  DATA-QUALITY FINDINGS (for Session 2b): (1) game-level results are
  31% white / 18% draw / 51% BLACK wins — a color bias impossible for
  fair same-engine selfplay; the generation corpus (April, PeSTO-d6,
  random openings) is biased. STM-normalized features can't see color, so
  it acts as label noise, not learnable poison — but it inflates outcome-
  label noise. (2) MAX_GAME_PLIES=400 cap + 80-ply shuffle rule finalize
  unconverted wins as draws → 48% of positions carry draw labels; at
  SF18-eval >= +700 (STM winning), 49% of records are labeled draw.
  Weak-play outcomes are genuine but very noisy targets.
- Q2, blend semantics at cebc78a0 (value.rs:115):
  target = blend * result + (1-blend) * sigmoid(score/SCALE), result
  STM-relative {0,0.5,1}, blend = ConstantWDL value → the ladder values
  weight the RESULT. Direction confirmed. LinearWDL/Warmup ramps exist.
- Q3, gate noise: gate_ladder.py run twice on candidate B → +0.213 both
  times (0.000 mechanical noise; deterministic position scan + 1-thread
  SF18 d10). Relevant uncertainty is position-sample SE ≈ 0.05 (15
  positions, per-position rho spread −0.15…+0.49) → deltas < 0.05
  treated as ties; thresholds unchanged (same fixed instrument as S1).

LADDER (SCReLU-256, SB30, stock loss, same data; final losses NOT comparable
to session 1 — different targets = different floor; floors moved DOWN
(0.0027/0.0016/0.00085), against my predicted direction, because draw-heavy
blended targets sit near sigmoid 0.5):

| candidate  | act    | WDL | final loss | Gate A | Gate M ratio | rho    |
|------------|--------|-----|-----------|--------|--------------|--------|
| B (ref)    | SCReLU | 0.0 | 0.0033    | PASS   | 1.03         | +0.213 |
| D1         | SCReLU | 0.1 | 0.0027    | PASS   | 1.09         | +0.199 |
| D2         | SCReLU | 0.3 | 0.0016    | PASS   | 1.24         | +0.117 |
| D3         | SCReLU | 0.5 | 0.00085   | PASS   | 1.44         | +0.008 |
| D4 (ctrl)  | CReLU  | 0.1 | 0.0027    | PASS   | 1.09         | +0.085 |
| C0 (ref)   | CReLU  | 0.0 | 0.0033    | PASS   | 1.03         | +0.125 |

PREDICTIONS vs outcomes: D2-sweet-spot prediction WRONG — the flagged sharp
failure mode ("48% draw mass flattens targets → monotonic rho drop") is what
happened. Gate M drifted OPPOSITE to prediction: not deflated but INFLATED
(1.44 at WDL 0.5) — material-down positions are near-certain losses in this
corpus, so outcome targets overshoot SF18's calibration; >20% off at
WDL >= 0.3, the flagged absolute-eval failure, in mirror image.

D4 (CReLU control at best-gating WDL = 0.1): initially skipped (decision
table row 3 had fired), then run on explicit request to complete the
activation x WDL 2x2. Result rho +0.085 (prediction band +0.10-0.13:
direction held, magnitude slightly larger). The 2x2 (C0/B/D1/D4) shows WDL
0.1 is a pure penalty in BOTH activation columns (CReLU −0.040, SCReLU
−0.014) — no interaction rescue, and SCReLU's advantage WIDENS under
outcome-label noise (+0.088 → +0.114). Curious replicated detail: per-batch
loss floors match across activations at fixed WDL to ~5 digits (D4 vs D1,
C0 vs B) — the floor is a property of the TARGETS, further evidence all
these nets are target-noise-limited, not fit-limited.

VERDICT (pre-committed): WDL axis DEAD on this data. Best config remains
candidate B (SCReLU-256, WDL 0.0, rho +0.213). No SPRT (nothing >= 0.3).

SESSION 2b RECOMMENDATION — data volume/variety, specifically fixing the
two corpus defects found tonight: (1) regenerate selfplay with the CURRENT
T4 engine (~1820, Syzygy-finished endgames convert wins → far fewer fake
cap-draws; also investigate the black bias before generating — it may be a
bug in the April opening randomizer), (2) more positions (20M → 50M+ now
that GPU trains at ~4M pos/s), (3) re-eval at SF18 d12 as before. WDL
blending may be worth ONE retry on the new corpus (draw fraction should
drop sharply), but volume+quality is the primary axis. Carry SCReLU.

Checkpoints: bullet/checkpoints/pyro-gpu-wdl01|03|05|01-crelu/. Gate log:
scratchpad gate_wdl.log (table above complete). Live nets untouched:
md5 23BFCD331411B8B9C6A05191D42CAEF5 both locations, before and after
(re-verified again after the D4 addendum).


## Session 2b Stage 2 — the v2 data campaign (July 16-20, 2026)

**Outcome: 50,000,415 positions on disk (wc -l ground truth; worker stats read
50,000,083 at the final flush), 1,055,338 games, 0 bad lines, completed cleanly
July 20 ~03:20.** Output `C:/torch_data/selfplay_v2.shard0-9.plain`, generator
`backend/scripts/generate_selfplay_v2.py`, nodes=4000, seed 20260716. Replaces
the v1 recipe whose 20M corpus was ~30 distinct games replayed ~10,000x.

Recipe: random-legal 4-8-ply stems screened at depth 4 to |eval| <= 150cp; global
stem partition by crc32(epd) % workers (transpositions collapse); every stem played
twice color-mirrored (balance BY CONSTRUCTION; self-mirror stems play once);
adjudication = python-chess rules draws + Syzygy WDL <= 6 + resign ±900cp x 4 plies
+ shuffle + 250-ply cap; v1 quiet recording filter (pipeline-compatible).

### Audit trail (mini-audits on 2M-line samples; final on full corpus)

| Gate | Pilot 8000n | @10M | @20M | @50M FULL |
|---|---|---|---|---|
| Draws < 25% (games) | 20.1% | 21.3% | 21.3% | 21.2% PASS |
| Color balance z | +0.73 | −0.35 | +1.20 | +8.60 (white 50.5% of decisive) |
| Inversion-flagged | 2.06% | 1.88% | 2.02% | 1.94% (SF18 spot-checks: ~0 true, twice) |
| Fake-draw flagged | 17.9% | 18.1% | 17.9% | 17.83% (nodes=4000 deciding gate HELD) |
| Variety (distinct/games) | 0.986 | 0.988 | 0.990 | **0.894** (87,036 dup sigs, max replay 12) |
| Cap games | 0 | 2 | ~0 | 6 per 1.06M |

No 30M mini-audit exists: the 30M watcher fired as WORKER LOSS during the July 18
OOM instead of a crossing. End reasons (full): 67.8% resign / 18.8% rules-draw /
10.1% Syzygy / 3.4% checkmate.

**Final-audit findings (not visible in early-shard samples):**
1. Variety 0.894 full-corpus: ~6 restart boundaries each reset the in-memory stem
   dedup ("restart amnesia") and deterministic RNG re-seeding replayed overlapping
   stem streams — 111,749 excess games (10.6%) are byte-identical replays. Remedy
   (approved): Stage 3 step-0 exact-line dedup (blake2b-8) removes replays wholesale
   — predicted ~11-13% dropped, ~43.5-44.5M unique kept; post-dedup corpus is
   duplicate-free by construction. Sidecar stem persistence (crc32-hex per line)
   is active from the final segment onward and prevents the class.
2. z=+8.60 is large-n statistics on a 0.5pp effect (n=831k decisive): white 50.5%.
   Direction/size chess-plausible (first-move edge through the ≤47cp color jitter
   in pyro's eval); v1's defect was 51% BLACK. A label characteristic, not a bug.

### Ops incident log (the hard-won lessons, in order)
1. **Phantom console SIGINT** (July 16): schtasks test died 0xC000013A ("^C") 6s in;
   the first WMI campaign launch died ~1 min in — 9 worker tracebacks with headers
   only, master banner lost in stdout buffering. Fix: V2_HEADLESS=1 → SIG_IGN in
   master and workers; python -u for unbuffered logs; Start-Process detached launch.
2. **EcoQoS throttling by launch context** (July 14-16): everything launched from a
   background session ran ~6x slow (15-28 pos/s, CPU pinned at 48-50% frequency,
   all processes near-idle). Priority was NOT the cause (BelowNormal never engaged).
   Fix: SetProcessInformation(ProcessPowerThrottling, never-throttle) on master,
   workers, engines — CPU 48%→144% instantly, 28→188 pos/s. Baked into the
   generator; qos_off.py is the manual tool.
3. **Windows Update reboot** (July 16 night): killed the campaign at 883,635
   positions. Fix: Active Hours 08:00-02:00 (18h max), updates paused 14 days,
   logon-resurrection via Startup .vbs (schtasks ONSTART/ONLOGON need elevation);
   resume is lossless (shard line counts).
4. **Idle-throttle stall** (July 17): 8h at ~18 pos/s (12:22-20:36) with heartbeat
   timers coalesced (process alive, log silent); recovered when the box woke. Cost
   ~4.5M positions. Fix: watchdog asserts ES_SYSTEM_REQUIRED keep-awake every 15 min
   + re-applies qos-off; heartbeat rate-delta bug (never updated prev totals — all
   lines read "first") found and fixed in the same review.
5. **OneDrive 52GB OOM** (July 18 16:39-16:45, Event Log Resource-Exhaustion names
   OneDrive.exe at 52,228,489,216 bytes; pagefile peaked 35.7GB/48.9GB): a pyro
   spawn failed mid-famine → "Engine process died" → fleet lost at ~27.98M. Fixes:
   workers 10→8 (8 ran FASTER: 185 vs 171 pos/s — less contention), engine copied
   out of the OneDrive tree (C:/torch_data/pyro_campaign.exe), spawn retry with
   backoff + fleet death tolerance, watchdog memory guard (<800MB warn, <400MB
   controlled restart) + auto-resume when engines are gone, hash-based stem sets.
   Standing rule: OneDrive QUIT during campaigns.
6. **Double-launch race + rename blindness** (July 18): two resume invocations
   minutes apart could double-launch (guard raced); the pyro→pyro_campaign rename
   blinded every name-keyed check — watchdog logged 8 pyro_campaign procs while
   exiting for "no engines"; heartbeat showed 0 workers; the resume guard grepped
   the old image name. Fixes: guards keyed on COMMAND LINE not process name,
   pyro* prefix matching everywhere, self-PID exclusion in kill-by-pattern
   (a kill pattern matched the invoking shell twice).

Throughput history: 94.5 pos/s (10w, interactive, 8000 nodes) → 20-28 (throttled)
→ 188 (qos fix, 4000 nodes) → 185 sustained at 8 workers. The nodes 8000→4000 cut
was gated by a 50k side-smoke (fake-draws flat, resign spot-check 48/50 sane) and
scales super-linearly (node limit checked at iteration boundaries: 47ms→19ms).

Stage 3 pre-staged and tested before the go: hardened reeval_with_sf18.py (EcoQoS,
SIGINT immunity, truncate-reconcile resume — live-tested kill/resume line-exact vs
control, warm-TT eval jitter p50 14cp documented), dedup_plain.py (validated on
pilot: 2.07% single-segment), filter_wdl_clean.py, stage3_resume.cmd + heartbeat +
staged-outside-Startup .vbs. Live nets untouched all campaign: pyro.nnue md5
23BFCD331411B8B9C6A05191D42CAEF5 both locations, re-verified at completion.

---

## ARCHIVED CLAUDE.md — pre-Session-2b operating context (snapshot July 20, 2026)

The following is the CLAUDE.md that governed June 5 - July 20, 2026, archived
verbatim before the post-campaign rewrite:

# CLAUDE.md

Guidance for Claude Code in this repo. AI chess app ("Torch"/"Pyro"): React frontend,
FastAPI backend, hand-built Rust engine (PeSTO+Tal eval). Full development history,
completed phases, and resolved investigations live in HISTORY.md — read it only when
you need the "why" behind a past decision. This file is the live operating context.

---

## CURRENT GOAL (reset June 5, 2026)

Pyro plays **beautiful, sensible, dynamic, powerful chess** on the PeSTO+Tal
hand-crafted-eval base, finished with Syzygy-perfect endgames. NOT a max-Elo race.

**DESIGN PRINCIPLE** — every change is measured against this:
Pyro plays beautiful chess by calculating deeply and accurately, then — among moves
the search rates near-equal — preferring the more dynamic, aggressive one. Aesthetics
are a TIEBREAK, never an override. Pyro never plays a move the search shows is worse
to look flashy. Sound sacrifices EMERGE from deeper search; they are never forced by a
move-ordering thumb. (G9 proved the forcing approach fails: −362 Elo. Closed.)

---

## WORKING RULES (read before every turn)

1. ONE VARIABLE per experiment. If you can't name exactly one change vs the last
   measured state, STOP and ask.
2. PREDICTION FIRST. Write a falsifiable prediction before running; record if it held.
3. NO-OP PROOF. Any new UCI param defaults to 0/off and must be byte-identical to
   baseline at default before any gauntlet.
4. THE GAUNTLET IS GROUND TRUTH — not depth-reached, not aggression-rate, not loss.
   Never mark a feature ✅ on a bench metric.
5. SAMPLE SIZE: ≥100 games for any verdict, ≥150-200 to set a baseline. 20-30 game
   matches are noise (±120 Elo) and must never drive a code decision.
6. MEASURE VS A FIXED LADDER, NOT SELF-PLAY, for depth/SMP changes. Self-play A/B
   understates them — both sides gain the ply, so the advantage cancels. (June 2026:
   self-play called SMP "neutral" at 49%; the SF-ladder showed +80-118 Elo.)
7. The live engine runs PeSTO+Tal via `--no-nnue`. Do not ship NNUE as eval.
8. RUN-TO-RUN VARIANCE IS REAL. Identical-config 100-game runs have been
   observed 14pp (~97 Elo) apart (IID vs SF-1700: 46.5% then 60.5%). A single
   100g leg never overrides pooled multi-instrument evidence; anchors carry
   their own CI. When a script may run twice, use tee -a (append) or unique
   log names — logs were overwritten in the IID experiment.
9. BACKGROUND-TASK "killed" NOTIFICATIONS ARE UNRELIABLE on Windows — the
   process tree may survive detached. Verify via Get-Process
   (cutechess/pyro/stockfish) before starting or restarting any gauntlet.
   Gauntlet scripts must guard against running engines (see
   run_comp_bonus_gauntlet_finish.sh).

---

## VERIFIED BASELINE (June 2026) — measure everything against this

Anchor: commit `b8e25f0` · binary md5 `587567f2bbd5ce54e40481b7cc9ccea6` · `--no-nnue`
· TC 10+0.1 · concurrency=1 · no book · 600 games · 0 disconnects.

- **T1 (engineering baseline — reference for "did a code change help"):**
  44.3% vs SF-1700 (−40±47), 33.8% vs SF-1900 (−117±49) → implied **~1721**.
- **T4 (production / what ships; rust_engine.py sends Threads 4):**
  61.0% vs SF-1700 (+78±64), 44.5% vs SF-1900 (−38±68) → implied **~1820**.
- **Style anchor (for DYNAMIC_BONUS clause 1):** T1 agg 77.2% / kz_sac 31.0%;
  T4 agg 71.0% / kz_sac 38.0%.
- The old "1835" was a Threads=4 number all along (≈ this T4 ~1820), not fiction.
- Raw data: `backend/scripts/gauntlet/results/baseline_2026-06/`.

---

## PATH TO THE GOAL (sequenced, one variable each, gauntlet-validated)

1. **POWERFUL** — Lazy SMP. ✅ VALIDATED June 2026: +80-118 Elo on the SF-ladder at
   Threads=4. Ships at Threads=4 (~1820).
2. **DYNAMIC** — capped dynamic-eval tiebreak (DYNAMIC_BONUS, default 0, in EVAL not
   ordering). Small term rewarding initiative toward the enemy king, hard-capped
   ~15-25cp so it only breaks near-ties. Measure vs T1 ~1721 + the style anchor.
   STATUS: EVAL-SIDE CLOSED (July 5, 2026): both instruments measured.
   DYNAMIC_BONUS=20 (presence-reward): Elo held, kz_sac DOWN 31.0→20.5%.
   COMP_BONUS=100 (compensation-reward): Elo held (~1748 vs ~1721), kz_sac
   FLAT 32.7% vs 31.0% (threshold 35%). Eval-side sac incentives PROVEN
   exhausted — sacs come from search resolving attacks, not from leaf bonuses.
   Both params dormant at 0. Do not reopen without sign-off. Beauty work
   proceeds at the personality layer.
3. **BEAUTIFUL** — emerges from 1+2 over the existing Syzygy endgame base.
4. **PERSONALITY** — G13 taunts, G15 visual attack cues (pure frontend, no Elo risk).
   STATUS: ACTIVE — next work.

**Re-add fork: CLOSED (July 2, 2026).** IID was re-added cleanly (SE-gate fix:
original_tt_entry captured pre-IID so SE can't fire on IID's shallow entry) and
measured NEUTRAL across 600 games vs the T1 anchor: self-play 48.75% (200g),
vs SF-1900 34.25% (200g, anchor 33.8%), vs SF-1700 53.5% (200g, anchor 44.3% —
not credited: the two identical-config 100g halves were 46.5%/60.5%, disagreeing
by more than the effect). IID_ENABLE stays default false; code dormant, SE fix
retained. Since LMP-without-IID is catastrophic (June data), LMP and dep-NMP are
PARKED — the trio only plausibly pays as a tuned package, and Elo-hunting it is
off-mission. Raw data: backend/scripts/gauntlet/results/iid_experiment/.

**NNUE-as-eval: SHELVED.** First trusted net (expE) lost to PeSTO by ~700 Elo when
training was CPU-bound. The hardware blocker is FIXED (July 12, 2026): bullet pinned to
cebc78a0 (cudarc-free CUDA-13 backend) + driver 610.62 trains on the RTX 3050 —
SB30 on the 20M-position set in ~6 min (~1.5-4M pos/s). Full diagnostic record in
HISTORY.md. Still do not reopen without explicit sign-off.
Capacity ladder, session 1 (July 12, 2026): three candidates trained on GPU
(expE-config parity / HIDDEN=512 / SCReLU-256, one variable each), gated with
the new backend/scripts/gate_ladder.py — rho: parity +0.125, 512 +0.045,
SCReLU +0.213 (expE ref +0.155; bar 0.3). Best rho < 0.25 → pre-committed
STOP, no SPRT run; live pyro.nnue untouched (md5 verified). Capacity refuted
as the bottleneck at 20M positions; SCReLU was the only gain. Next session:
DATA axis with SCReLU as base. Full record in HISTORY.md.
Session 2a (July 12, 2026): WDL blending on the existing data is DEAD —
rho monotonically worse (0.1/0.3/0.5 → +0.199/+0.117/+0.008 vs B's +0.213)
and material calibration inflates (Gate M 1.44 at 0.5). D4 CReLU control
(WDL 0.1 → +0.085 vs C0's +0.125) completed the 2x2: WDL penalizes both
activations, no interaction; SCReLU's edge widens under label noise. Recon proved the
result field genuine/STM-correct but noisy: game-level 51% BLACK wins
(biased April generation corpus) and 48% draw labels from 400-ply cap
non-conversions. Session 2b: regenerate selfplay with the current T4 engine
(fewer fake draws; investigate black bias first), scale 20M→50M+, keep
SCReLU, optionally retry WDL once on the clean corpus. Full record in
HISTORY.md.

---

## KEY PATHS

- Engine binary: `engine/target/release/pyro.exe` (loads `pyro.nnue` beside it unless `--no-nnue`)
- Engine src: `engine/src/{search.rs, main.rs, movegen.rs, board.rs, nnue.rs}`
- UCI wrapper: `backend/app/engine/rust_engine.py` (sends `Threads 4` + `--no-nnue` at startup)
- Gauntlet/scripts: `backend/scripts/gauntlet/`, `backend/scripts/aggression_rate.py`,
  `backend/scripts/validate_nnue_rust.py` (real SPRT, works for any A/B)
- GPU trainer port: `backend/scripts/bullet_port/` (bullet-submodule local additions;
  restore procedure in its README)
- Syzygy tablebases: `backend/data/syzygy/` (WDL+DTZ, ≤6 pieces) — perfect endgames, wired in
- SF18: `C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe`
- cutechess: `C:/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe`
- History/archive: `HISTORY.md`

---

## COMMANDS

```bash
cd engine && cargo build --release
echo -e "uci\nisready\nposition startpos\ngo depth 8\nquit" | ./target/release/pyro.exe --no-nnue
cd backend && source venv/Scripts/activate && uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

Windows: Git Bash or PowerShell, not CMD. venv is `venv/` not `.venv/`.
Don't `taskkill` uvicorn — Ctrl+C in its terminal.

---

## STANDING CONTEXT

- **Hardware:** Windows 11, 12 cores, 8GB RAM. RTX 3050 trains Bullet since July 12,
  2026 (bullet cebc78a0 CUDA-13 backend + driver 610.62): SB30 ≈ 6 min. NNUE stays
  shelved on Elo grounds, not hardware.
- **Workflow:** chat-Claude plans, Claude Code executes, user relays and runs git.
  Confirm `git status` shows only `m bullet` before pushing; never stage the submodule.
- **Git:** branches `feat/`/`fix/`/`chore/`; commits imperative mood.
- **Engine features live now:** alpha-beta + PVS + aspiration + NMP + LMR + killers +
  countermove + qsearch + SEE + singular extensions + check-extension ply cap + full
  UCI time mgmt + Lazy SMP (validated) + incremental NNUE accumulator (dormant) +
  31-GM opening book + Syzygy. Dormant behind default-off params: IID (IID_ENABLE,
  measured neutral July 2026), G9 SPEC_BONUS. Deleted and parked: LMP, dep-NMP
  (predicted to fail without IID).
- **G9 dormant:** SPEC_BONUS param exists, default 0, byte-identical to baseline. Closed.

---

## DO-NOTS

- Don't make code decisions on <100-game samples; don't use self-play for depth/SMP.
- Don't ship NNUE as eval (runs --no-nnue).
- Don't reopen IID/LMP/dep-NMP without explicit sign-off — measured/parked July 2026.
- Don't run `uvicorn --workers >1` (in-memory game state).
- Don't import chess.js in backend or python-chess in frontend.
- Don't bundle two changes into one experiment.
## Session 2b Stage 3 + wrap — dedup, SF18 relabel, the training-ready corpus (July 22-25, 2026)

Completes the Session 2b arc. Backstory in the two sections above: the Stage 0
autopsy (the v1 20M corpus was ~30 distinct games replayed ~10,000x — the root
cause of every Phase D ceiling) and the Stage 2 campaign record (50,000,415
positions over July 16-20, with the six-incident ops log: phantom SIGINT,
EcoQoS launch-context throttling, the Windows-Update reboot, the 8h
idle-throttle stall, the OneDrive 52GB OOM, the rename-blinded guards).

### Step 0 — dedup (July 22)
Full-line blake2b-8 exact dedup over the 10 shards: 50,000,415 -> 42,799,245
kept, 7,201,170 dropped (14.402%), 5.2 min. Gate band 8-16% PASS (prediction
11-13%: direction held, magnitude under — the signature count was a lower
bound missing in-game repetition lines and partial replays). Post-dedup full
audit: variety 0.995 (was 0.894 raw), max replay 4 — spot-checked 3 groups:
zero byte-identical lines; collisions are stem-length transpositions (same
board positions, different FEN counters, TT-divergent evals; one group's games
even had different results). Distinct (FEN,result) pairs measured via numpy
uint64 digests: 42,799,244 of 42,799,245 — pyro's determinism means same-FEN
lines had identical evals and were already removed; a post-relabel re-dedup
has a clean ~zero-drop baseline. Per-shard drift table (full parse): draw%
20.9-21.4, white share 50.1-50.8, end reasons +-0.4pp — homogeneous, no step
changes; shards 8-9 (frozen pre-OOM) match 0-7 on every metric.

### Disk remediation (July 22)
24GB free was under the 25GB bar: deleted pip cache (5.7GB) + npm cache
(4.9GB) -> 34GB. Protected and untouched: C:/torch_data, backend/data (v1-era
corpus + Syzygy in the repo tree), checkpoints (expE protected), pagefile
47.2GB / hiberfil 6.3GB (not authorized; hiberfil noted as the next 6.3GB via
powercfg /h off if ever needed).

### SF18 relabel (July 22-24) — 58.7 hours, zero errors
reeval_with_sf18.py (multi-worker since April; hardened this session with
EcoQoS self-apply on master/workers/each SF18, V2_HEADLESS SIGINT immunity,
truncate-reconcile resume — live-tested July 17 by kill-mid-chunk + resume,
line-exact vs an uninterrupted control, including a simulated
flushed-ahead-of-checkpoint truncation). Run: --workers 10 --depth 12
(mandatory: matches the old corpus labels), OneDrive quit first (standing
rule), launched via the stage3_resume.cmd resurrection path with watchdog +
S3 heartbeat + a new standalone disk monitor (5-min polls, <5GB -> clean
tree-kill for resume). Result: 42,799,245/42,799,245 written, 0 errors,
211,479s (202 pos/s), survived nightly shutdowns via logon resurrection.

THE THROUGHPUT LESSON: 202 pos/s at 10 workers vs April's 320 at 6. The
April rate was flattered by v1's duplication — SF18's TT stayed warm on
endlessly repeated positions. 42.8M unique positions pay the true cold-TT
cost of depth 12. Recorded on the corpus card for future relabel estimates.

Mid-relabel incident (July 22): the watchdog died at 02:53 by the same class
of bug as the pyro_campaign rename — its qos scan bucketed the workers as
'stockfish-windows-x86-64-avx' while the idle-exit logic looked up the exact
key 'stockfish'; it logged 10 workers and "no engines" simultaneously, then
exited (keep-awake unasserted ~9h; no harm — the box stayed active). Fix:
BOTH engine counts now prefix-match the same bucketed name set the scan
produces, and every cycle logs "engines: pyro N sf N idle_cycles N/8" so the
two code paths can never disagree silently again. The auto-resume guard chain
held during the bug: corpus_total() >= target blocked a spurious campaign
resume — two independent guards, one saved us.

### WDL-clean split + conversions + verification (July 24-25)
filter_wdl_clean.py: dropped 2,203,918 draw-labeled positions with
|white-POV SF18| >= 400 (5.15%; gate 2-6%; zero non-draw lines by
construction). Cross-check: the final audit independently counts exactly
2,203,918 such positions. convert_plain_to_bullet.py on both .plains:
0 skipped on either; size == 32 x records asserted on both. 200-record
random STM spot-check on EACH .data (score vs eval_stm, result byte under
STM flip, occupancy popcount, king squares, full piece-nibble mirror
round-trip): 200/200 and 200/200.

### The deliverables (corpus card: C:/torch_data/selfplay_v2_corpus_card.md)
- selfplay_v2_sf18.data — FULL corpus, 42,799,245 records, 1,369,575,840
  bytes, md5 0f8115f33c19ee7b896e2161cb8e24c5. Eval training.
- selfplay_v2_sf18_wdlclean.data — 40,595,327 records, 1,299,050,464 bytes,
  md5 7afff9cc3a96d53c3b1c0f7da1684170. THE ONLY FILE THE ONE-SHOT WDL RETRY
  MAY USE.
Documented characteristics (on the card, not defects): the variety history
(six restart boundaries, ~10.6% replays, erased by dedup; sidecar persistence
prevents the class); the color characteristic (white 50.4-50.5% of decisive,
z inflated by n, real first-move edge — v1's 51%-black artifact gone); 21.6%
of draw labels are honest non-conversions (absent from the wdlclean file);
19,487 thrown-game positions (0.046%, real outcomes); SF18 warm-TT label
jitter (p50 14cp between hypothetical reruns); the 202-pos/s cold-TT rate.

Wrap: intermediates deleted (dedup/wdlclean .plains, re-derivable), stage3
launcher out of Startup, armor self-terminated, 26GB free. Sources kept: raw
shards + selfplay_v2_sf18.plain + the old 20M anchor (superseded by v2,
retained for one-variable comparisons, still never-delete). Live nets
untouched through the entire session: pyro.nnue md5
23bfcd331411b8b9c6a05191d42caef5 at both locations, verified at every stage
boundary. Ops scripts committed to backend/scripts/ops/ (README = runbook).

Phase D reopens on this corpus: SCReLU-256 baseline, the 512 re-test, the
earned WDL retry — one variable each, ~6 min/run, rho >= 0.3 earns an SPRT,
deployment gated on style. Fresh session on explicit go.

## Phase D training ladder on v2 corpus — SCReLU-512 champion (July 25, 2026)

The ladder ran against one frozen, deterministic ruler. Before candidate training,
`gate_ladder_frozen.py` reproduced the archived Session-1 SCReLU-256 anchor exactly:
Gate A PASS at 0.0% saturation, Gate M `1.03`, and Spearman rho `+0.213384615`
(`+0.213`). All five anchor checks passed. The frozen manifest SHA-256 is
`3479ac0dd90c85447d3ef2bbb32fef56c888cdfc54bb130602cc1cf6119b0046`.

### Experimental control and D0

Every run used the Session-1 schedule: 1,221 batches × 30 superbatches =
36,630 updates, batch 16,384, 600,145,920 positions consumed, seed 198273612,
cosine LR `1e-3 → 1e-5`, SCReLU, and final SB30 selection. D0 was the rung-(a)
matched-seed duplicate, so determinism was measured on the exact headline
configuration rather than a throwaway preflight.

D0 was NOT byte-deterministic: all 18 checkpoint exports and optimizer-state
files differed between identical CUDA runs, consistent with GPU `atomicAdd`
ordering. The rho values were `+0.533230769` and `+0.534205128`, a spread of
`0.000974359`. That became the measured noise floor; every later rung used a
matched-seed pair, and a real edge had to clear it.

### Ladder result

| Rung | One variable | Pair rhos | Pair mean | Pair spread | Verdict |
|---|---|---:|---:|---:|---|
| (a) SCReLU-256/full v2 | data file vs Session 1 | +0.533231 / +0.534205 | **+0.533718** | 0.000974 | v2 data wins |
| (b) SCReLU-512/full v2 | hidden 256 → 512 | +0.623487 / +0.623641 | **+0.623564** | 0.000154 | champion |
| (c0) SCReLU-512/WDL-clean | full → WDL-clean file | +0.616974 / +0.617385 | **+0.617179** | 0.000410 | file is not neutral |
| (c1) SCReLU-512/WDL-clean | WDL 0.0 → 0.1 | +0.603077 / +0.604564 | **+0.603821** | 0.001487 | WDL permanently closed |

**Rung (a) — corpus effect.** The trainer was the exact Session-1 SCReLU-256
configuration with only the data path changed to `selfplay_v2_sf18.data`.
The headline rho rose from `+0.213` to `+0.5332` (pair mean `+0.5337`):
`+0.320` over the anchor and `+0.233` over the `0.300` SPRT bar. The same
architecture and compute gained about 2.5× rho from the corpus alone, proving
the Session-1 diagnosis that data—not architecture or loss floor—was the ceiling.

**Rung (b) — 512 re-test.** The only change from (a) was `HIDDEN_SIZE 256 → 512`.
Pair mean rho reached `+0.623564`; against the designated rung-(a) run,
the gain was `+0.090333`, or 92.7× the D0 noise floor. This overturns the
Session-1 “512 is worse” verdict as a data artifact: on the starved corpus,
extra capacity memorized noise (`+0.045`); on roughly 913k real games it paid
decisively (`+0.624`).

**Rung (c0) — the file control caught a real effect.** c0 held the 512-SCReLU,
WDL-0 configuration fixed and changed only to
`selfplay_v2_sf18_wdlclean.data`. Its mean was `+0.617179`, so
`mean(c0) − mean(b) = −0.006385`, 6.5× the noise floor. Dropping the 5.15%
winning-but-drawn records measurably hurt even eval-target training: those
positions carried useful evaluation signal. The file was not neutral, which
is why c0—not rung (b)—is the required attribution control for c1.

**Rung (c1) — the earned WDL retry failed.** The only change from c0 was
`ConstantWDL 0.0 → 0.1`. Its mean was `+0.603821`, so
`mean(c1) − mean(c0) = −0.013359`: 13.7× the D0 noise floor in the wrong
direction, and 9.0× c1's own larger pair spread. Parents 3 and 7 were the
mechanism-level collapse points, where outcome and SF18 evaluation disagree.
WDL is DEAD on clean data too: Session 2a's fake-draw explanation has spent
its one appeal. This is the second and final strike; the WDL axis is
permanently closed.

### Per-parent pair means

| Parent | (a) 256/full | (b) 512/full | c0 512/clean | c1 512/clean/WDL .1 |
|---:|---:|---:|---:|---:|
| 1 | +0.657 | +0.684 | +0.671 | +0.640 |
| 2 | +0.615 | +0.531 | +0.598 | +0.614 |
| 3 | +0.345 | +0.528 | +0.542 | +0.430 |
| 4 | +0.745 | +0.700 | +0.692 | +0.756 |
| 5 | +0.581 | +0.653 | +0.668 | +0.680 |
| 6 | +0.635 | +0.674 | +0.560 | +0.604 |
| 7 | +0.275 | +0.518 | +0.624 | +0.439 |
| 8 | +0.682 | +0.731 | +0.693 | +0.675 |
| 9 | +0.031 | +0.238 | +0.232 | +0.223 |
| 10 | +0.719 | +0.796 | +0.783 | +0.757 |
| 11 | +0.555 | +0.789 | +0.640 | +0.758 |
| 12 | +0.391 | +0.443 | +0.561 | +0.509 |
| 13 | +0.736 | +0.819 | +0.725 | +0.783 |
| 14 | +0.436 | +0.553 | +0.572 | +0.527 |
| 15 | +0.602 | +0.695 | +0.698 | +0.661 |

Parent 9 remains the unresolved position type: it improved from only `+0.031`
at 256 to `+0.238` at 512, then stayed near `+0.23` through c0 and c1.
Neither added capacity nor clean-data/WDL treatment cracked it. This is a
future-experiment note, not a reason to reopen this ladder.

### Gate M trend and champion designation

Gate A passed at 0.0% saturation for every net. Gate M also passed throughout,
but trended `1.03` (Session 1) → `1.36` (256/v2) → `1.38` (512/full) →
`1.40` (c0/c1). The v2 nets—especially the wider variants—calibrate material
more steeply versus SF18. WATCH this during engine validation because material
scaling interacts with search.

**CHAMPION:** rung (b), 512-wide SCReLU trained on the full
`selfplay_v2_sf18.data` corpus with WDL 0.0, pair mean rho `+0.623564`.
It wins by a margin far beyond measured noise. The best Session-1 net was
`+0.213`; the champion is `+0.624`, about 2.9× higher, vindicating the entire
v2 corpus campaign.

The sole inference-block candidate is staged outside the live engine:

- `C:/torch_data/phase_d_champion/pyro_v2_screlu512_raw.bin`
- SHA-256 `50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184`
- MD5 `56c14d958057aa23f16103c15b911ec6`

Status is **SPRT-eligible, NOT validated, NOT shipped**. The remaining path is
SCReLU-512 inference implementation and verification → SPRT versus PeSTO →
gauntlet plus STYLE check. Per mission, a net that wins the SPRT but costs
Pyro's beautiful, aggressive, sacrificial style does not ship. The live engine
continues to run PeSTO+Tal via `--no-nnue`.

## Phase D COMPLETE — SCReLU-512 champion validated (July 25, 2026)

Context (all decided; recording, not re-litigating): Phase D is COMPLETE. The
SCReLU-512 v2 champion is confirmed ship-eligible at production config but NOT yet
deployed. Full chain:

### TRAINING LADDER (frozen gate, matched-seed pairs, noise floor 0.000974)

- Frozen gate reproduced Session-1 anchor exactly (`+0.213`).
- Rung (a) SCReLU-256 on v2, SAME schedule as Session 1 (36,630 updates): rho
  `+0.533`, `+0.320` over anchor. ONE VARIABLE = data. Proves "data was the
  ceiling."
- D0: CUDA training non-deterministic (noise `0.000974`); later rungs = matched
  pairs.
- Rung (b) 512 re-test: rho `+0.6236`, `+0.090` over (a) = 92.7x noise.
  OVERTURNS the Session-1 "512 worse" verdict as a starved-data artifact.
- Rung (c) WDL: c0 (clean file, WDL 0) `+0.6172`; c1 (WDL 0.1) `+0.6038`,
  `-0.0134` vs c0. WDL DEAD on clean data too -> permanently closed
  (2nd/final strike). c0 also showed dropping the 5.15% winning-draws slightly
  HURT (`-0.0064`) -> those positions carry useful eval signal.
- Gate-M material-scaling trend across ladder: `1.03 -> 1.36 -> 1.38 -> 1.40`
  (all PASS); flagged for engine validation. It did NOT cause any board-level
  problem (see T4).
- Residual: parent-9 rho stuck `~0.23` across ALL nets -> future-experiment note.

**CHAMPION:** 512-SCReLU v2 WDL 0.0, rho `+0.6236`. Staged
`C:/torch_data/phase_d_champion/pyro_v2_screlu512_raw.bin`, SHA-256
`50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184`.

### INFERENCE (branch feat/screlu-512-inference, commit f7209ac)

- NNUE format v2, 32-byte activation-aware header, FAIL-CLOSED (legacy
  CReLU-256 rejected exit 2; SCReLU-512 valid exit 0).
- Exact integer arithmetic
  (`clip -> square -> /QA -> bias -> *SCALE/(QA*QB)`, two divisions NOT merged)
  verified: Rust vs independent Python integer ref, 10,000/10,000 exact on raw
  accumulators AND final cp, plus boundary cases. Independently regenerated
  payload byte-identical to Bullet's champion `quantised.bin` (789,506
  meaningful bytes).
- `--no-nnue` no-op proof: byte-identical bestmove transcript vs pre-branch
  baseline.

### VALIDATION

- T1 SPRT vs PeSTO (Threads=1, book off): H1 accepted game 45, LLR `3.08 >
  2.94`, 36-0-9, `+381.7 Elo`.
- T1 ladder vs SF-1700 (100g): 81-13-6, 84.0%, `+288.1 Elo` -> `~1988 T1`
  (`~+267` over the `~1721` anchor).
- T1 style (101g binding): agg 76.2 / kz_sac 28.7 / sacs_pg 1.31 /
  kz_sacs_pg 0.41 — ALL floors held (kz_sac floor 26, agg 70, sacs_pg 1.05).
- T4 PRODUCTION (Threads=4, book ON, Syzygy ON, 100g): 57-10-33, 73.5%,
  `+177.2 Elo`, LOS 100%, 33% draws (book-expected). Style: agg 75.0 /
  kz_sac 29.0 / sacs_pg 1.26 — ALL floors held. CONFIRMED shippable.

### STATUS

Ship-eligible, NOT deployed. Live engine still PeSTO+Tal `--no-nnue`; both live
nets remain MD5 `23bfcd331411b8b9c6a05191d42caef5`. The live-net flip is a
separate explicit decision, not part of this record.

## Phase D DEPLOYED — SCReLU-512 becomes the live eval (July 26, 2026)

The separately authorized deployment completed the Phase D arc. The verified
inference branch `feat/screlu-512-inference` (`f7209ac`) was merged into main by
merge commit `85b4d66`; PeSTO+Tal and `--no-nnue` remain intact.

Before the flip, both identical legacy live nets were MD5
`23bfcd331411b8b9c6a05191d42caef5`. One canonical tracked revert artifact is
preserved at `engine/pyro_pesto_era_backup.nnue` with that exact MD5. The
deployed v2 net is installed at both live locations:

- `engine/pyro.nnue`
- `engine/target/release/pyro.nnue`
- bytes `789,538`
- MD5 `9f01010bfe8b41193f77a9fad88abd56`
- SHA-256 `a06cfebd7c22d0b45f08ba94a276fd2a7cf8b3cd76c54dd308b2eeaa1a579591`

The deployable payload is the format-v2 form generated from champion raw SHA-256
`50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184`.
Preflight re-proved valid-v2 exit 0 (`NNUE loaded`) and legacy-v1 rejection
exit 2. The release build passed, all 74 Rust test executions passed, and the
post-merge `--no-nnue` canonical transcript remained byte-identical to the
pre-merge binary (10/10 positions, transcript SHA-256
`6bb6f5a09d92e113969f85e44dff8c78159513b78bb89664e6dd369927d7d0dc`).

Production startup in `backend/app/engine/rust_engine.py` now launches
`pyro.exe` without `--no-nnue`, then sends `setoption name Threads value 4`.
`PYRO_NO_NNUE=1` appends `--no-nnue` as the explicit PeSTO+Tal
comparison/revert option. The on-wire app-path probe recorded:

```text
startup command  C:\Users\shami\OneDrive\Documents\torch\engine\target\release\pyro.exe
engine stderr    NNUE loaded
UCI startup      uci | setoption name Threads value 4 | isready
book probe       answered before Rust search
Syzygy probe     answered before Rust search, WDL +2
search probe     legal move from the Rust NNUE path
```

The reverse probe with `PYRO_NO_NNUE=1` recorded the `--no-nnue` command,
`NNUE disabled (--no-nnue), using PST + Tal`, Threads=4, and a legal move.
The real FastAPI lifespan started in Rust/SCReLU-512 mode and its health handler
returned `{"status": "ok"}`. A deterministic app-engine self-play at the
minimum shipped movetime (100 ms) ran from start position to checkmate in 126
plies (`0-1`, winner Black); result truth matched, 14 voice events fired, and
heat exercised every level 0-3. The backend suite passed 40/40, including the
P0 result, voice, heat, NNUE-default, and PeSTO-fallback tests.

Revert: restore `engine/pyro_pesto_era_backup.nnue` to both live `pyro.nnue`
locations and set `PYRO_NO_NNUE=1`.

## Production correctness fix: timed root-iteration completion (July 31, 2026)

### Incident

Lichess game `6Iy2yfnM` (TorchVision29 vs PyroBotTorch, 300+0) exposed a
genuine, reproducible production correctness failure. Playing Black, Pyro found
the forced mate after `18...Nh3+` and scored it `+499.95` (mate in three);
Stockfish 18 independently confirmed the line at depth 24. After White replied
`19.Kf1`, Pyro had two immediate mates, `Qg1#` and `Qf2#`, but instead played
`19...dxc4`, evaluated at approximately `+0.21`. Pyro eventually won with
`47...Qdd8#`, but that later result does not diminish the correctness failure
after `19.Kf1`.

The initial suspicion that the `+499.95` value itself was corrupt was wrong:
the mate score was correct. The forensic audit located the actual defect in
the root iterative-deepening loop's timed-exhaustion handling. Of the two
post-child budget checks, the pre-score check marked an interrupted iteration
incomplete only while `best.is_none()`, and the post-score check could break
without marking it incomplete at all. Once a completed child had populated
`best`, a later budget expiry could therefore leave the partial iteration
marked completed, allowing its `(bestmove, score, depth)` tuple to overwrite
the last fully completed tuple.

The failure was timing- and scheduling-dependent. At the exact post-`19.Kf1`
production clock, Threads=1 found the immediate mate 0/10 times and returned
`Nf2` paired with a false mate-range score in 9/10 runs. Threads=2 found the
mate 8/10 times. This distribution was consistent with interrupted root
iterations, not a deterministic chess-logic failure.

The audit ruled out the Lichess bridge and PGN conversion, Lazy SMP
score/move ownership (the result is published as one atomic tuple), and TT
mate-distance normalization (which round-trips correctly). A separate
cosmetic finding remains: Pyro emits mate-range values as raw UCI `score cp`
rather than `score mate N`, which is why the bridge displayed `499.95` rather
than `#5`. UCI score formatting was intentionally outside this fix.

### Fix

Commit `5469931e6653b58ddec8f068614ab42c4c9422ed` on
`fix/timed-root-completion`, titled
`fix(search): preserve completed result on timeout`, corrects only timed and
node-limited root-iteration completion semantics. Whenever either post-child
deadline/node-budget check expires, it now unconditionally sets
`completed = false` before breaking, regardless of whether `best` is already
populated. The engine therefore preserves the last fully completed
`(bestmove, score, depth)` tuple.

There is no mate-specific override, heuristic, evaluation, TT, SMP, search
strength, timing-policy, or UCI-format change. The production change is three
substantive lines: a loop-syntax adjustment needed to host the test hook and
the missing `completed = false` handling at the second exhaustion window.

### Verification and isolation audit

- A deterministic `#[cfg(test)]` abort-injection hook exercised 11 root
  interruption scenarios: first, second, later, and final root moves at the
  pre-score and post-score checkpoints, plus fail-high, fail-low, and a third
  full-window re-search. Every case returned the exact known-correct completed
  depth-1 move/score tuple.
- The first isolation audit caught a real test-support leak: `_move_index` and
  `.enumerate()` had been introduced into the production loop without
  `#[cfg(test)]`. Move-index tracking was moved to a fully test-gated counter.
  Binary-string scans then found zero hook identifiers in both debug and
  release production artifacts, while the debug test binary produced five
  positive-control hits, proving that the scanner was effective.
- `cargo test` in isolated debug and release targets passed 32 + 43 tests in
  both profiles.
- Perft remained exactly `20 / 400 / 8,902` in both profiles.
- At the exact production clock, the post-`19.Kf1` incident regression passed
  50/50 times at Threads=1 and 50/50 times at Threads=2. Every result was a
  legal immediate mate (`Qf2#` or `Qg1#`) with score `49999`; there were no
  non-mating or illegal results.
- The preceding `18...Nh3+` position was unaffected: fixed-depth and exact
  clock searches still returned `Nh3+` with score `49995`.
- Baseline-versus-candidate final transcripts on the canonical ten-position
  suite were byte-identical in both NNUE and `--no-nnue` modes.
- The existing no-op transcript remained byte-identical with SHA-256
  `6bb6f5a09d92e113969f85e44dff8c78159513b78bb89664e6dd369927d7d0dc`.
- The complete SCReLU-512 Rust/Python integer-equivalence suite remained
  10,000/10,000 exact with zero mismatches.

### Deployment

Deployment used an executable-only swap; neither live NNUE file was modified.
The first swap itself hash-matched, but the separate deployed-path Python
verifier failed before launching Pyro. Its dynamic import called
`module_from_spec()` and then `exec_module()` without first registering the
module in `sys.modules`, so `@dataclass` could not resolve postponed annotations
through its own module. Per the pre-committed rollback gate, no fix-forward or
same-attempt retry was made: the pre-fix executable was immediately restored
and verified at SHA-256
`3F09FC38D7B89DAA9B86FE965BEAAC511528D63E82FEEEE9F258CB11E03F03F7`.

The harness-only correction inserted
`sys.modules[spec.name] = module` between module creation and execution. It was
first re-verified end-to-end against the already-proven isolated candidate.
The complete deployment sequence was then repeated from a fresh isolated
build and succeeded.

The actual deployed executable, not merely the isolated candidate, passed all
four final probes:

- NNUE mode reported `NNUE loaded` and returned a legal move.
- `--no-nnue` reported the PeSTO+Tal fallback and returned a legal move.
- Threads=1 returned `Qf2#`, score `49999`, legal immediate mate, exit 0.
- Threads=2 returned `Qg1#`, score `49999`, legal immediate mate, exit 0.

Final live executable:

- bytes: `313,344`
- MD5: `275BCC9D86056839A35A71F4D39CDA14`
- SHA-256:
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`

Both live NNUE files remained unchanged at `engine/pyro.nnue` and
`engine/target/release/pyro.nnue`:

- MD5: `9F01010BFE8B41193F77A9FAD88ABD56`
- SHA-256:
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`

The PeSTO-era net backup remains MD5
`23BFCD331411B8B9C6A05191D42CAEF5`.

### Merge and status

Branch `fix/timed-root-completion` was pushed, then merged into `main` with
`git merge --no-ff` using the `ort` strategy. Merge commit
`203b60856fd0b651c73ce814926fb3266c31bf9d` moved `main` from
`b6c3277dd1f2ac7415f1a799756602f7b30a0839`. The merged code diff is exactly:

- `engine/src/search.rs` (`+407/-3`)
- `backend/scripts/verify_timed_root_completion.py` (`+476/-0`)

The fix is live, deployed, verified, merged into `main`, and pushed.
PyroBotTorch remains offline; restarting the bridge is a separate explicit
decision.

## First post-fix live Lichess shakedown passed (August 1, 2026)

PyroBotTorch's first independently audited live game after deployment of the
timed-root-completion fix passed end to end. In casual 5+0 standard Blitz game
[`SS1KiMLB`](https://lichess.org/SS1KiMLB), PyroBotTorch played White against
the allow-listed human account TorchVision29 from a Polish Opening and won
`1-0` by `39.Rxh7#` after 77 plies (39 Pyro moves).

The external lichess-bot bridge ran the deployed SCReLU-512 NNUE executable at
Threads=2. The GM opening book supplied Pyro's first two moves; Syzygy was
enabled but was not relevant. Independent python-chess parsing found 0 illegal
moves and 0 PGN errors, and classified the final position as checkmate. The
engine completed every move normally, delivered the mating move with about
1:19 remaining, exited cleanly after the game, and left no duplicate or
orphaned engine process. There was no engine or bridge crash, protocol error,
timeout, or timed-root-completion symptom. The bridge remained online and
returned to awaiting challenges.

Pinned live artifacts for the shakedown were:

- `engine/target/release/pyro.exe`: SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`
- `engine/target/release/pyro.nnue`: SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`

This game validates the deployed correctness fix through a complete real
Lichess lifecycle. It is correctness and operational evidence, not an Elo
measurement.

## Ticket #19 COMPLETE — deterministic search-throughput instrumentation (August 2, 2026)

Ticket #19 established the measurement layer required before attempting pure
search-throughput optimization. The reviewed Ticket #19 implementation added
aggregate search-call accounting across main-thread depth attempts, aspiration
re-searches, incomplete final iterations, and joined Lazy SMP helpers. Every
completed search now reports exactly one line in this form:

```text
info depth D score cp S nodes N time T nps P
```

It also adds deterministic `bench` v1: the canonical ten-position suite at
depth 8, forced Threads=1, with fresh search state per position and an
architecture-stable FNV-1a-64 checksum over deterministic result/work fields.
Elapsed time and NPS are deliberately excluded from the checksum.

The Python verification was hardened to reject identical or incorrectly pinned
baseline/candidate artifacts, incomplete or additional search transcript
output, malformed or missing metrics, incorrect NPS arithmetic, missing,
duplicated, reordered, or non-depth-8 benchmark rows, incorrect aggregate
nodes, and stale checksums. Python independently recomputes every benchmark
checksum. The final false-pass regression harness passed 26/26 cases.

Final independent Review Agent verdict: **VERIFIED SUCCESS**. The review found
no change to recursive node increments, node-budget or deadline behavior,
search policy, evaluation, move ordering, TT behavior, timing policy, or UCI
defaults. Principal validation results:

- fixed-depth baseline/candidate equivalence: 40/40 legal decision tuples;
- deterministic NNUE bench: 5,065,087 nodes, checksum `a8df66621c8eb452`;
- deterministic PeSTO bench: 4,900,866 nodes, checksum `18bd8f3c9614b0db`;
- debug tests: 32/32 + 46/46; release tests: 32/32 + 46/46;
- perft: `20 / 400 / 8,902`;
- SCReLU integer verification: 10,000/10,000 exact;
- retained timed-root campaign: 50/50 legal immediate mates at Threads=1 and
  50/50 at Threads=2, with zero illegal or non-mating results;
- fresh verifier-correction smokes passed at Threads=1 and Threads=2, and the
  preceding-position fixed-depth and production-clock checks passed.

The isolated candidate is 327,168 bytes with SHA-256
`906E06247DE3D68D80639E7CDF63519DFD7167D191BB1E401FC0D2CB551ABF00`.
Reports and immutable artifacts are retained under
`C:\torch_data\pyro_ticket19_20260801_46d8c36`.

The candidate was not deployed. The live executable remained SHA-256
`6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`,
and both live NNUE files remained SHA-256
`A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
Ticket #19 is instrumentation-only: it makes no Elo claim and no
speed-improvement claim. Benchmark wall-time outliers reflected host
contention and are not optimization evidence.

## Ticket #1 COMPLETE — incremental SCReLU-512 NNUE accumulators (August 2, 2026)

Ticket #1 replaced recursive full NNUE accumulator reconstruction with
incremental maintenance derived from authoritative parent/child piece
bitboards. The reviewed implementation centralizes the twelve feature planes,
clones the parent accumulator for each searched child, removes parent-only
features, adds child-only features, and updates both fixed perspectives. This
single delta mechanism covers quiet moves, captures, en passant, promotions
and underpromotions, castling, corner-rook captures, king moves, and rook moves
without duplicating move-flag decoding inside NNUE.

Each independent NNUE root constructs exactly one full accumulator. The main
search and every Lazy SMP helper then use private search-local stacks; helpers
receive independent root clones, PVS/LMR re-searches reuse the same child
accumulator, and null moves reuse unchanged raw lanes while changing the output
perspective. PeSTO retains a zero-sized path with no NNUE accumulator work. No
recursive production path rebuilds an accumulator with
`Accumulator::from_board`.

The final deterministic corpus used seed `20260802` and is retained at
`C:\torch_data\pyro_ticket1_20260802_1bf38f4\corpus\incremental_sequences_10000_exact_ep.tsv`.
It is 72,038 bytes with SHA-256
`3DD95476383233A63667C05FED8FBCD5702E3193266C971C99F2AAE2A17EC909`.
Its 246 cases contain 10,330 transitions: 10,202 legal non-null transitions,
10,107 canonical non-null positions, and 128 canonical null sources split
64/64 by side to move. Representative-FEN round-trip mismatches were zero.

Three-way comparison between Rust incremental evaluation, Rust full
reconstruction, and an independent Python full reconstruction was exact:
10,577,920 raw accumulator lanes, 21,155,840 raw-value comparisons, and 10,330
final-centipawn comparisons produced zero illegal transitions and zero
mismatches. The 84,850,685-byte raw evidence file is
`C:\torch_data\pyro_ticket1_20260802_1bf38f4\incremental_exactness\exact_ep_results.bin`,
SHA-256
`B5161B04F0ABFFE9B4DCDC88B01DFEAF64C3178B67AE90F773E38B83313B73CD`;
the JSON report SHA-256 is
`351E961EC77273098E39501864F3D4B0A09DA7E27BA91259826B9BF25C0A0716`.
The frozen SCReLU proof also remained 10,000/10,000 exact plus 8/8 synthetic
boundary cases.

Correctness validation passed debug and release suites (34 verifier tests + 49
engine tests in each mode), the release all-binaries build, perft
`20 / 400 / 8,902`, and 40/40 fixed-depth equivalence. Deterministic fixed work
remained exactly 5,065,087 nodes / `a8df66621c8eb452` for NNUE and 4,900,866
nodes / `18bd8f3c9614b0db` for PeSTO. The strict PeSTO no-op transcript proof,
preceding-position checks, and the timed-root incident gate all passed: 50/50
legal immediate mates at Threads=1 and 50/50 at Threads=2, with no illegal or
non-mating result. Final independent review found no issue.

On the controlled Ticket #19 fixed-work comparison, NNUE median elapsed time
fell from 18,945 ms to 10,711 ms, a **43.463%** improvement; median NPS rose
from 267,362 to 472,918.5, and the candidate won 10/10 paired comparisons. The
4.600% baseline three-MAD/median contamination measure cleared the
precommitted 5.406% acceptance threshold. Nodes, checksums, decisions, scores,
and depths remained exact. PeSTO moved from 7,858.5 ms to 7,653.5 ms median
(2.609% improvement) with no regression and unchanged fixed work.

The isolated candidate is 356,864 bytes, MD5
`0096EAFE3395EBB14A7AD543694651A0`, SHA-256
`D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`,
at `C:\torch_data\pyro_ticket1_20260802_1bf38f4\artifacts\candidate\pyro.exe`.
It was not deployed during validation. The live executable remained SHA-256
`6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`,
and both live NNUE files remained
`A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
Ticket #1 is a verified same-work NNUE throughput improvement, not an Elo
result: no chess gauntlet was run, higher NPS alone does not prove playing
strength, and deployment remains a separate decision.
