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
