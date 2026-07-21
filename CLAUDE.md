# CLAUDE.md

Guidance for Claude Code in this repo. AI chess app ("Torch"/"Pyro"): React frontend,
FastAPI backend, hand-built Rust engine (PeSTO+Tal eval). Full development history and
resolved investigations live in HISTORY.md — read it only when you need the "why" behind
a past decision. This file is the live operating context.

---

## CURRENT GOAL (reset June 5, 2026)

Pyro plays **beautiful, sensible, dynamic, powerful chess** on the PeSTO+Tal
hand-crafted-eval base, finished with Syzygy-perfect endgames. NOT a max-Elo race.

**DESIGN PRINCIPLE** — every change is measured against this:
Pyro plays beautiful chess by calculating deeply and accurately, then — among moves the
search rates near-equal — preferring the more dynamic, aggressive one. Aesthetics are a
TIEBREAK, never an override. Sound sacrifices EMERGE from deeper search; they are never
forced by a move-ordering thumb.

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
6. MEASURE VS A FIXED LADDER, NOT SELF-PLAY, for depth/SMP changes — self-play
   understates them (both sides gain the ply). Self-play IS valid for fixed-thread
   ordering/eval changes.
7. RUN-TO-RUN VARIANCE IS REAL: identical-config 100-game runs have landed 14pp
   (~97 Elo) apart. A single leg never overrides pooled multi-instrument evidence.
8. VERIFY THE PREMISE, NOT JUST THE INSTRUCTION. If a task's stated assumption looks
   wrong on inspection, check before executing (this has saved data twice).
9. "KILLED"/"COMPLETED" NOTIFICATIONS ARE UNRELIABLE on Windows. Verify process state
   (Get-Process) and file mtimes before acting on any death/completion claim.
10. The live engine runs PeSTO+Tal via `--no-nnue`. Do not ship NNUE as eval.

---

## VERIFIED BASELINE (June 2026) — measure everything against this

Anchor: commit `b8e25f0` · binary md5 `587567f2bbd5ce54e40481b7cc9ccea6` · `--no-nnue`
· TC 10+0.1 · concurrency=1 · no book · 600 games · 0 disconnects.

- **T1 (engineering baseline — reference for "did a code change help"):**
  44.3% vs SF-1700 (−40±47), 33.8% vs SF-1900 (−117±49) → implied **~1721**.
- **T4 (production / what ships; rust_engine.py sends Threads 4):**
  61.0% vs SF-1700 (+78±64), 44.5% vs SF-1900 (−38±68) → implied **~1820**.
- **Style anchor (T1):** agg 77.2% / kz_sac 31.0% / sacs_pg 1.30 / kz_sacs_pg 0.35.
- The old "1835" was a Threads=4 number all along (≈ this T4), not fiction.
- Raw data: `backend/scripts/gauntlet/results/baseline_2026-06/`.

---

## ENGINE WORK — ALL CLOSED (June–July 2026)

| Experiment | Verdict |
|---|---|
| G2 Lazy SMP | ✅ VALIDATED +80-118 Elo on SF-ladder. Ships at Threads=4 (~1820). |
| G9 ordering-bonus sacs | ❌ REJECTED −362 Elo. Wrong instrument. SPEC_BONUS dormant at 0. |
| IID re-add (+SE-gate fix) | ❌ NEUTRAL over 600 games. IID_ENABLE dormant at false. |
| LMP / dep-NMP | PARKED (predicted to fail without IID; off-mission to chase). |
| DYNAMIC_BONUS=20 (eval tiebreak) | ❌ Clause 1 FAIL: Elo held (~+44 nominal) but kz_sac DROPPED 31.0→20.5%. Rewards *standing* attackers; sacrificing removes them. Dormant at 0. |
| COMP_BONUS=100 (compensation-gated) | ❌ Clause 1 FAIL: Elo held (~1748), kz_sac FLAT 32.7% vs 31.0% (needed 35%). Dormant at 0. |

**EVAL-SIDE BEAUTY IS CLOSED.** Two opposite incentive designs (presence-reward,
compensation-reward) both failed → sacrifices come from *search resolving attacks*, not
from leaf bonuses. A capped eval term cannot move them. Do not reopen without sign-off.
Side-finding: capped attack terms are Elo-neutral-to-positive (DB +44, CB +27 nominal) —
an SPSA pass over {G8v2 cap, DYNAMIC_BONUS, COMP_BONUS} is a low-risk *Elo* ticket if
ever wanted. Off-mission today.

---

## APP / PRODUCT — SHIPPED (July 2026)

- **G13 voice**: `backend/app/engine/pyro_voice.py` — event detection (sac, king-hunt,
  blunder, crushing, game-end…), priority + 4-ply cooldown, no line repeats per game,
  fail-open. Frontend speech bubble, flame toggle.
- **G15 heat**: heat 0-3 from king-zone attackers + eval, CSS-only board glow,
  respects prefers-reduced-motion.
- **Coach gate**: EvalBar + EnginePanel + the `/api/suggest` call itself are gated
  behind a session-only Coach toggle, default OFF — a Play-mode win is provably
  unassisted at the network level.
- **P0 FIXED — result truth**: backend only set `winner` on timeout, so *every*
  checkmate and resignation had always displayed as ½–½. `result_of()` in
  chess_utils/board.py is now the single source; handler, voice, and modal all read it.
  Regression test: no checkmate is ever winner-less.
- **Game persistence**: completed games append to `backend/data/local_games/YYYY-MM.pgn`
  (+ `GET /api/local-games`). Fail-open.
- **Responsive layout** (71e0065): board scales to viewport (780px on 1080p, was fixed
  520px), 320px side column, stacks below 900px.
- Difficulty ladder = Pyro's mood: Sleeping 0.1s / Playful 0.5s / Awake 2s / Hunting 5s
  / **Feral** (full clock-based TC, the ~1820 config).

---

## GPU TRAINING — UNLOCKED (July 12, 2026)

The CUDA/cudarc blocker is **gone**: upstream bullet removed cudarc entirely and links
CUDA directly. Bullet pinned to `cebc78a0`; GeForce driver updated to **610.62 (CUDA
13.3)** after the smoke test hit the predicted `UNSUPPORTED_PTX_VERSION`.

- **Measured: 58 min → 6 min 6 s for a full SB30 run (9.5×)**, RTX 3050 at 98% util.
- Trainer port is durable in **`backend/scripts/bullet_port/`** (pyro.rs, smoke variant,
  Cargo snippet, README with the restore procedure). Bullet working-tree copies are
  build inputs only — the parent repo is the backup.
- Training runs are now cheap: iterate freely, gate hard.

---

## PHASE D (NNUE) — REOPENED, DATA-BOUND

**Session 1 (capacity ladder, old 20M corpus):** 512-wide made move-ranking WORSE
(rho +0.045 vs 256's +0.125). **SCReLU is the new base activation (+0.213).** All
candidates hit *identical* loss floors ⇒ the ceiling was the DATA, not the architecture.

**Session 2a (WDL ladder, old corpus):** every WDL weight hurt (0.1→+0.199, 0.3→+0.117,
0.5→+0.008; CReLU control +0.085). Mechanism: the old corpus was 48% draws (ply-cap
non-conversions) with a 51% black bias. WDL earns exactly ONE retry on clean data.

**Stage 0 autopsy — the root cause of everything:** the v1 20M corpus was
**~30 distinct games replayed ~10,000× each** (37-pair fixed book × deterministic
engine). Every Phase D ceiling traces here.

**Gate bar for any new net:** Spearman rho vs SF18 ≥ 0.3 earns an SPRT.
Reference: expE +0.155, GPU-parity +0.125, SCReLU +0.213. Gate is deterministic (±0.000).

---

## SESSION 2b — THE v2 DATA CAMPAIGN

**STAGE 2 COMPLETE (July 20, 03:20): `50,000,415` positions on disk (wc -l ground
truth; worker stats read 50,000,083 at the final flush).**
`C:/torch_data/selfplay_v2.shard*.plain` — 1,055,338 games (~944k distinct pre-dedup),
nodes=4000, seed 20260716, generator `backend/scripts/generate_selfplay_v2.py`.

Recipe: 4-8 uniformly-random legal plies screened to |eval| ≤ 150cp; global stem
partition by crc32(epd) % workers; **every stem played twice, color-mirrored** (balance
by construction); Syzygy ≤6 adjudication; resign at ±900cp × 4 plies; first 8 plies not
recorded.

Mini-audits (10M / 20M, 2M-line samples) — zero drift on any axis:
draws 21.3% (gate <25%) · color z −0.35/+1.20 (gate |z|<2) · variety 0.988-0.990 ·
fake-draw flagged 17.9-18.1% (the nodes=4000 deciding gate — held exactly) ·
cap games ~0 · end reasons 67.8% resign / 18.8% rules-draw / 10.1% Syzygy / 3.4% mate.
(No 30M audit exists — that watcher fired as worker-loss during the OOM instead.)

**Final 50M audit — two findings the samples couldn't see** (full record in HISTORY.md):
- Variety 0.894 full-corpus: ~6 restart boundaries with seen-set amnesia replayed
  111,749 games (10.6%, max replay 12). Stage 3's dedup pass removes replays entirely
  (byte-identical lines); the sidecar stem file now persists dedup memory going forward.
- Color z = +8.60 is large-n statistics on a 0.5pp effect (white 50.5% of 831k decisive)
  — chess-plausible first-move edge, a label characteristic, not a defect (v1's bug was
  51% *black*).

### ⏳ STAGE 3 — PENDING, PRE-STAGED, AWAITING GO
Sequence (assets all written and verified; `stage3_resume.cmd` guards on stockfish.exe
and refuses to run before the dedup output exists):
1. `dedup_plain.py` over the shards → `selfplay_v2_dedup.plain` (~10 min; gate: ~11-13%
   dropped per the final audit's replay count — expect ~43.5-44.5M kept; pilot
   single-segment measured 2.07%).
2. Launcher swap: `torch_stage3_resume.vbs` → Startup (campaign's already removed).
3. `reeval_with_sf18.py --workers 10 --depth 12` detached (~1-1.3 days, est. 450-600
   pos/s). **Depth 12 is mandatory** — it matches the old corpus's labels, so new-vs-old
   comparisons stay one-variable.
4. `filter_wdl_clean.py` → WDL-clean subset (drop draw-labeled |SF18| ≥ 400; gate 2-6%).
5. `convert_plain_to_bullet.py` on BOTH .plains (~2h each) → full + WDL-clean `.data`.
6. Final audit + 200-record STM spot-check + corpus card. STOP for sign-off.

Verification chain: dedup kept+dropped == shard total; relabel written == kept − errors
(<0.1%); .data size == 32 × records. Peak disk ~17GB (verified to fit).
Note: SF18 evals carry warm-TT jitter (p50 14cp between runs) — a property of the
labels, on the card, not a defect.

### ▶ AFTER STAGE 3 — the training ladder (the payoff)
Base: SCReLU, HIDDEN=256, stock loss, SB30, new corpus. One variable each, 6 min/run:
(a) baseline on new data vs old-data reference; (b) **512 re-test** — its failure is
only proven on the starved corpus; (c) WDL retry on the clean subset (the one earned
retry); (d) further capacity/data-mix if warranted.
rho ≥ 0.3 → SPRT vs PeSTO. A SCReLU net needs an inference change in `engine/src/nnue.rs`
first (square the clipped accumulator, /QA renormalize) — branch-scoped, verified, before
any SPRT is trustworthy. HIDDEN_SIZE is a compile-time const (nnue.rs:12): width changes
need a rebuild.
**Deployment stays gated on STYLE, not just Elo** — a winning net ships only if it keeps
the fire.

---

## KEY PATHS

- Engine: `engine/target/release/pyro.exe` (loads `pyro.nnue` beside it unless `--no-nnue`)
- Campaign engine copy (outside OneDrive): `C:/torch_data/pyro_campaign.exe`
- Engine src: `engine/src/{search.rs, main.rs, movegen.rs, board.rs, nnue.rs}`
- UCI wrapper: `backend/app/engine/rust_engine.py` (sends `Threads 4` + `--no-nnue`)
- Voice: `backend/app/engine/pyro_voice.py` · results: `chess_utils/board.py::result_of`
- Data campaign: `backend/scripts/{generate_selfplay_v2,audit_selfplay_corpus,dedup_plain,filter_wdl_clean,reeval_with_sf18}.py`
- GPU trainer port: `backend/scripts/bullet_port/` (README = restore procedure)
- Gates: `backend/scripts/{gate_ladder,spearman_check,validate_nnue_rust}.py`
- Ops (unsynced): `C:/torch_data/{campaign_watchdog.py, campaign_heartbeat.ps1, stage3_resume.cmd, check_running.ps1, *.log}`
- Syzygy: `backend/data/syzygy/` · SF18 + cutechess: see HISTORY.md
- Corpora: `C:/torch_data/selfplay_v2.shard*.plain` (new, 50M) ·
  `selfplay_sf18_d12.{plain,data}` (old 20M anchor — NEVER modify or delete)

---

## COMMANDS

```bash
cd engine && cargo build --release
echo -e "uci\nisready\nposition startpos\ngo depth 8\nquit" | ./target/release/pyro.exe --no-nnue
cd backend && source venv/Scripts/activate && uvicorn app.main:app --port 8000
cd frontend && npm run dev
# GPU training (from bullet/, port restored per bullet_port/README):
cargo build --release --package bullet_lib --example pyro --features cuda
```

Windows: Git Bash or PowerShell, not CMD. venv is `venv/`. Don't `taskkill` uvicorn.

---

## STANDING CONTEXT

- **Hardware:** Windows 11, 12 cores, **16GB RAM**, RTX 3050 Laptop 4GB — **GPU now
  USABLE** (driver 610.62 / CUDA 13.3 + CUDA 13.2 toolkit).
- **Workflow:** chat-Claude plans, Claude Code executes, user relays and runs git.
  Long jobs must be **detached** (Start-Process), resumable, and never block on
  permissions.
- **OPS LESSONS (hard-won, apply to every long job):** processes need
  (1) SIGINT immunity when headless — phantom console events kill detached runs;
  (2) EcoQoS-off + `ES_SYSTEM_REQUIRED` keep-awake — Windows idle-throttling cost 8h at
  ~18 pos/s; (3) a memory guard — **OneDrive leaked 52GB and OOM-killed a spawn**
  (keep OneDrive QUIT during campaigns); (4) worker-death tolerance + spawn retry;
  (5) resume guards keyed on *command line*, not process name (a rename blinded the
  watchdog; a name-only guard double-launched the campaign); (6) resurrection at logon
  via Startup .vbs (schtasks needs elevation we don't have).
- **Git:** branches `feat/`/`fix/`/`chore/`; imperative commits. `git status` should show
  only `m bullet` (+ intentional strays). Never stage the submodule except the one
  sanctioned pin (`cd1dc8c`).
- **Engine features live:** alpha-beta + PVS + aspiration + NMP + LMR + killers +
  countermove + qsearch + SEE + singular extensions + full UCI time mgmt + Lazy SMP +
  31-GM opening book (159,260 positions) + Syzygy.
  Dormant at default-off: IID_ENABLE, SPEC_BONUS, DYNAMIC_BONUS, COMP_BONUS.

---

## OPEN TICKETS (small, unscheduled)

- `backend/app/engine/nnue.py` loads `models/nnue.pt` at import with **no live caller** —
  dead PyTorch load on every app startup. Make lazy or remove.
- `voice_enabled` is client-side only; needs a settings route for multi-client/spectator
  correctness.
- venv `python-chess` is **0.31.4** (predates `Board.outcome()`); upgrade carefully —
  the voice module depends on it.
- CLAUDE.md previously said 8GB RAM; corrected to 16GB above.

---

## DO-NOTS

- Don't reopen eval-side sacrifice incentives (DYNAMIC/COMP) — measured closed.
- Don't reopen IID/LMP/dep-NMP without sign-off.
- Don't ship NNUE as eval; a net must win an SPRT **and** keep the style.
- Don't modify or delete the old 20M anchor corpus, or `pyro-expE*` checkpoints.
- Don't relabel at any depth but 12 (breaks the anchor comparison).
- Don't make code decisions on <100-game samples; don't use self-play for depth changes.
- Don't run `uvicorn --workers >1`; don't import chess.js in backend or python-chess in
  frontend; don't bundle two changes into one experiment.
