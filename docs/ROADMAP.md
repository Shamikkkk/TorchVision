# Pyro authorization-aware roadmap

This file classifies existing plans; it does not authorize implementation.
Detailed technical rationale and estimates remain in `STRENGTH_AUDIT.md`.
Every future engine change remains subject to `AGENTS.md` and the mandatory
timed-root-completion regression gate.

## Authorized next work

No Codex implementation or operational work is authorized. The only pending
action is user review of the four untracked context documents and, if accepted,
preservation through the user's own Git workflow. This review does not
authorize an engine change, experiment, deployment, Docker start, or bot
restart.

## Candidate future work

These are documented candidates, not approved tasks:

1. Add `bench` and `info nodes nps` instrumentation (#19).
2. Incremental NNUE accumulator updates (#1), with 10000-position exact eval
   equivalence and timed-root regression.
3. Remove move-order scoring inside the sort comparator (#2), then incremental
   Zobrist (#16), each under controlled equivalence gates.
4. Search improvements in the documented dependency order: log LMR (#3), RFP
   (#4), dynamic-R NMP (#6), QS TT/delta/captures-only work (#5), gradual
   aspiration (#7), TT/Hash improvements (#11), continuation history (#8), SEE
   pruning (#9), and time-management work (#10).
5. Tier 2 speed infrastructure: SIMD NNUE (#14), magic bitboards (#15), staged
   MovePicker (#17), and TT prefetch (#18).
6. NNUE/data candidates: output buckets (#20), then a 150-300M corpus (#21),
   followed by architecture experiments only when their data gates are met.
7. Unscheduled product maintenance from `CLAUDE.md`: lazy/remove the unused
   Python NNUE import, server-side voice settings, and a careful
   `python-chess` upgrade.
8. Always-on hosting for the optional Lichess bot.

These candidates are not interchangeable with authorization. Each experiment
must isolate one conceptual variable, state a prediction, preserve fixed
comparison configuration, and use the existing game-count and style gates.

## Blocked work

- Restarting PyroBotTorch is blocked pending explicit user approval.
- King buckets and horizontal mirroring (#22) are data-blocked until at least
  several hundred million positions exist.
- Deeper/bigger nets (#23) share the corpus and inference-speed gate.
- Reopening LMP/improving, IIR, or dependent-NMP work requires both the
  prerequisites in `STRENGTH_AUDIT.md` and explicit sign-off under
  `CLAUDE.md`.
- 24/7 hosting is blocked pending an explicitly chosen hosting/deployment
  plan and authorization.

## Closed, rejected, or completed work

- Completed and shipped: SCReLU-512 NNUE inference/deployment, protected PeSTO
  fallback, G2 Lazy SMP, and the timed-root-completion correctness fix.
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
