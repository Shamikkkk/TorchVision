# Pyro authorization-aware roadmap

This file classifies existing plans; it does not authorize implementation.
Detailed technical rationale and estimates remain in `STRENGTH_AUDIT.md`.
Every future engine change remains subject to `AGENTS.md` and the mandatory
timed-root-completion regression gate.

## Next planning item after Ticket #1 closure

The sole next planning candidate is Ticket #2: remove repeated move-order
scoring inside the sort comparator. Ticket #1 implementation, independent
review, Git preservation, merge, controlled deployment, deterministic
post-deployment validation, and real-world shakedown gates are complete.
Planning may begin only after this deployment-and-shakedown documentation is
independently reviewed and preserved. Implementation is not automatically
authorized and must not begin from this roadmap entry.

Ticket #2 must be a one-variable change. Its plan and any later implementation
must remain isolated from incremental Zobrist (#16), pruning, LMR, SIMD, NNUE
changes, move-generation work, or any other optimization. Required proof must
preserve exact fixed-work decisions, scores, completed depths, node totals, and
checksums in both NNUE and PeSTO modes; preserve strict PeSTO transcript
behavior; pass the timed-root incident gate at Threads=1 and Threads=2; and
retain the standing style safeguards for any subsequent game validation.

Ticket #16 and every later change remain separate. No strength implementation
or deployment is authorized.

## Candidate future work

These are documented candidates, not approved tasks:

1. Incremental Zobrist (#16), only after Ticket #2 is separately planned,
   implemented, reviewed, and preserved; it requires its own controlled
   equivalence gates.
2. Search improvements in the documented dependency order: log LMR (#3), RFP
   (#4), dynamic-R NMP (#6), QS TT/delta/captures-only work (#5), gradual
   aspiration (#7), TT/Hash improvements (#11), continuation history (#8), SEE
   pruning (#9), and time-management work (#10).
3. Tier 2 speed infrastructure: SIMD NNUE (#14), magic bitboards (#15), staged
   MovePicker (#17), and TT prefetch (#18).
4. NNUE/data candidates: output buckets (#20), then a 150-300M corpus (#21),
   followed by architecture experiments only when their data gates are met.
5. Unscheduled product maintenance from `CLAUDE.md`: lazy/remove the unused
   Python NNUE import, server-side voice settings, and a careful
   `python-chess` upgrade.
6. Always-on hosting for the optional Lichess bot.

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
autostart/watchdog work, deployment, and all candidate tickets above remain
outside the current authorization.

## Closed, rejected, or completed work

- Completed and shipped: SCReLU-512 NNUE inference/deployment, protected PeSTO
  fallback, G2 Lazy SMP, and the timed-root-completion correctness fix. The
  fix also passed complete live Lichess shakedown game `SS1KiMLB` on August 1,
  2026; PyroBotTorch remains online through the external bridge.
- Completed and independently reviewed: Ticket #19 deterministic `bench` v1,
  aggregate node accounting, completed-search `nodes/time/nps` reporting, and
  strict throughput verification. Its current Git preservation status must be
  checked from the repository; the candidate was not deployed during
  validation. Fixed-work anchors are NNUE 5,065,087 / `a8df66621c8eb452` and
  PeSTO 4,900,866 / `18bd8f3c9614b0db`. Ticket #19 makes no Elo or
  speed-improvement claim.
- Ticket #1 incremental SCReLU-512 accumulators is operationally closed:
  implementation and final independent review completed; commit
  `0aee7d72f89027b14071c1ed90e9595bf5deb215` was preserved; pull request #1
  merged it into `main` as
  `a3a997cb366ab95ae7b3926f7588fd41472e392e`; the reviewed executable was
  deployed; exact NNUE and PeSTO anchors passed after deployment; and casual
  5+0 shakedown game [`cP0rHVcl`](https://lichess.org/cP0rHVcl) completed with
  25/25 legal plies, `13.Qf6#`, clean engine exit, bridge recovery, and no
  process leak. Parent/child deltas preserved exact evaluation, and paired NNUE
  median elapsed time improved 43.463% with 10/10 wins at identical work. This
  is a throughput and operational-correctness result, not an Elo claim; no
  chess gauntlet was run.
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
- Pure-throughput work must preserve deterministic per-position decisions,
  nodes, and checksum, then use paired elapsed-time/NPS comparisons.
- Strength gauntlet plus style floors where behavior may change.
- Exact incident clock at Threads=1 and Threads=2, minimum 10 fresh processes
  each and preferably 50, with zero non-mating results, for every change that
  can affect timing.
