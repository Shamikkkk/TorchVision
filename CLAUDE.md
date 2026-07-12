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