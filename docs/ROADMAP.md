# Pyro authorization-aware roadmap

This file classifies existing plans; it does not authorize implementation.
Detailed technical rationale and estimates remain in `STRENGTH_AUDIT.md`.
Every future engine change remains subject to `AGENTS.md` and the mandatory
timed-root-completion regression gate.

## Authorized next work

The sole authorized next engineering task is `STRENGTH_AUDIT.md` ticket #19:

1. Add a deterministic `bench` command over a fixed internal position suite.
2. Add completed-search `info nodes ... nps ...` instrumentation.
3. Make no intended change to search decisions, evaluation, timing policy,
   transposition-table behavior, move ordering, or production defaults.
4. Require exact baseline/candidate decision-tuple equivalence in NNUE and
   `--no-nnue` modes.
5. Require repeated benchmark runs with an identical total node count and
   deterministic checksum; wall-clock NPS may vary.
6. Run the timed-root incident regression with fresh processes at Threads=1
   and Threads=2, with zero non-mating results.
7. Do not run a gauntlet unless behavior changes unexpectedly or an Elo claim
   is made.

Ticket #19 is instrumentation-only. It must not be bundled with incremental
NNUE, move-ordering, Zobrist, or any other optimization. This documentation
task records the authorization but does not implement ticket #19.

## Candidate future work

These are documented candidates, not approved tasks:

1. Incremental NNUE accumulator updates (#1), with 10000-position exact eval
   equivalence and timed-root regression.
2. Remove move-order scoring inside the sort comparator (#2), then incremental
   Zobrist (#16), each under controlled equivalence gates.
3. Search improvements in the documented dependency order: log LMR (#3), RFP
   (#4), dynamic-R NMP (#6), QS TT/delta/captures-only work (#5), gradual
   aspiration (#7), TT/Hash improvements (#11), continuation history (#8), SEE
   pruning (#9), and time-management work (#10).
4. Tier 2 speed infrastructure: SIMD NNUE (#14), magic bitboards (#15), staged
   MovePicker (#17), and TT prefetch (#18).
5. NNUE/data candidates: output buckets (#20), then a 150-300M corpus (#21),
   followed by architecture experiments only when their data gates are met.
6. Unscheduled product maintenance from `CLAUDE.md`: lazy/remove the unused
   Python NNUE import, server-side voice settings, and a careful
   `python-chess` upgrade.
7. Always-on hosting for the optional Lichess bot.

These candidates are not interchangeable with authorization. Each experiment
must isolate one conceptual variable, state a prediction, preserve fixed
comparison configuration, and use the existing game-count and style gates.

## Blocked work

- King buckets and horizontal mirroring (#22) are data-blocked until at least
  several hundred million positions exist.
- Deeper/bigger nets (#23) share the corpus and inference-speed gate.
- Reopening LMP/improving, IIR, or dependent-NMP work requires both the
  prerequisites in `STRENGTH_AUDIT.md` and explicit sign-off under
  `CLAUDE.md`.
- 24/7 hosting is blocked pending an explicitly chosen hosting/deployment
  plan and authorization.

Branch deletion, lichess-bot upstream updates, README corrections, persistent
autostart/watchdog work, and all candidate tickets above are outside ticket
#19 authorization.

## Closed, rejected, or completed work

- Completed and shipped: SCReLU-512 NNUE inference/deployment, protected PeSTO
  fallback, G2 Lazy SMP, and the timed-root-completion correctness fix. The
  fix also passed complete live Lichess shakedown game `SS1KiMLB` on August 1,
  2026; PyroBotTorch remains online through the external bridge.
- Rejected and closed: G9 sacrifice ordering bonus, DYNAMIC_BONUS, and
  COMP_BONUS as style mechanisms.
- Permanently closed by its second/final strike: WDL blending for the Phase D
  training line.
- Measured neutral or parked, not silently reopened: IID, LMP, and dependent
  NMP. Follow the blocked-work rule above.

## Standing release gates

- At least 100 games for a verdict and 150-200 for a baseline.
- Fixed-ladder comparisons for depth/SMP changes; preserve all non-variable
  configuration.
- No-op/equivalence proof where behavior should be unchanged.
- Strength gauntlet plus style floors where behavior may change.
- Exact incident clock at Threads=1 and Threads=2, minimum 10 fresh processes
  each and preferably 50, with zero non-mating results, for every change that
  can affect timing.
