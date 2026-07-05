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
