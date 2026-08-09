# Pyro concise handoff

Verified: August 9, 2026.

## Current state

- Repository: `C:\Users\shami\OneDrive\Documents\torch`. Ticket #2 was
  preserved as `ce1aa5aaeb7c9d57dd2a8a37c1546f5213d097e6` and merged into
  `main` by `876632c875338a89a013d380f7fb7c3f5de958f5`. At this verification
  snapshot, `main`, `HEAD`, and `origin/main` matched that merge and the only
  worktree dirt was the pre-existing lowercase ` m bullet`, with nothing
  staged. Check Git rather than treating this snapshot as permanent, and keep
  `bullet` excluded from unrelated work.
- The deployed engine defaults to the style-gated SCReLU-512 NNUE. The
  application uses Threads=4; `PYRO_NO_NNUE=1` retains the protected
  PeSTO+Tal `--no-nnue` fallback.
- The live Ticket #2 executable is 354,816 bytes, MD5
  `62D0D6F024CFFF580538E174BB8BA779`, SHA-256
  `B3E075A46DA72335F40E822A9EAA65B9219D20F7FDA8269B9A619D588F26AA40`.
  Both live NNUE files remain SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
- PyroBotTorch is online through the external native Python lichess-bot bridge
  at `C:\lichess-bot`. The bridge intentionally uses Threads=2, accepts one
  game at a time, and remains running while idle. No `pyro.exe` process is
  expected until an eligible game begins.
- There is no persistent watchdog or autostart. Sleep, logout, reboot, or a
  process failure will take the bot offline.

## Timed-root live correctness shakedown passed

The first complete post-fix live shakedown passed in casual 5+0 standard Blitz
game [`SS1KiMLB`](https://lichess.org/SS1KiMLB) against the allow-listed human
TorchVision29. PyroBotTorch played White and won `1-0` by `39.Rxh7#` after 77
plies. The GM book supplied Pyro's first two moves; Syzygy was enabled but not
relevant.

Independent python-chess validation found all 77 plies legal, all 39 Pyro
moves legal, zero PGN parser errors, and a checkmated final position. There was
no engine or bridge crash, protocol error, timeout, timed-root-completion
symptom, duplicate engine, or orphaned engine. The game process exited cleanly,
and the bridge returned to awaiting challenges.

Pinned shakedown artifacts:

- `engine/target/release/pyro.exe`: SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`
- `engine/target/release/pyro.nnue`: SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`

The timed-root fix is commit
`5469931e6653b58ddec8f068614ab42c4c9422ed`, merged into `main` by
`203b60856fd0b651c73ce814926fb3266c31bf9d`. It is now validated through a
complete real Lichess game, not only harnesses and local probes. No engine or
bridge defect was observed.

## Ticket #19 completed and reviewed

Ticket #19 passed final independent review with verdict **VERIFIED SUCCESS**.
The reviewed implementation added aggregate main/helper search-node
accounting, one completed-search `nodes/time/nps` report, deterministic depth-8
`bench` v1, and strict baseline/candidate verification. Independent review
confirmed no search-policy, evaluation, ordering, TT, budget/deadline,
timing-policy, or UCI-default change.

Deterministic fixed-work anchors:

- NNUE: 5,065,087 nodes, checksum `a8df66621c8eb452`;
- PeSTO: 4,900,866 nodes, checksum `18bd8f3c9614b0db`.

The isolated candidate is 327,168 bytes, SHA-256
`906E06247DE3D68D80639E7CDF63519DFD7167D191BB1E401FC0D2CB551ABF00`.
It was not deployed during Ticket #19 validation. Its instrumentation was later
preserved, entered the live line with Ticket #1, and remains in the current
Ticket #2 executable.

## Ticket #1 completed, deployed, and shakedown-verified

Ticket #1 passed final independent review with no findings. The implementation
maintains SCReLU-512 accumulators from authoritative parent/child piece-bitboard
differences: each searched child clones its parent, removes parent-only
features, adds child-only features, and updates both fixed perspectives. There
is one full construction per independent NNUE root, private stacks for the main
search and every Lazy SMP helper, child reuse across PVS/LMR re-searches, and
raw-lane reuse across null moves. PeSTO performs no NNUE accumulator work, and
recursive production evaluation performs no full reconstruction.

Three-way Rust-incremental/Rust-full/independent-Python verification was exact
over 10,577,920 raw lanes and 10,330 final-cp comparisons. Fixed-work anchors
remained unchanged:

- NNUE: 5,065,087 nodes, checksum `a8df66621c8eb452`;
- PeSTO: 4,900,866 nodes, checksum `18bd8f3c9614b0db`.

Across ten paired identical-work NNUE runs, median elapsed time improved from
18,945 ms to 10,711 ms (**43.463%**), median NPS rose from 267,362 to
472,918.5, and the candidate won 10/10 comparisons. PeSTO showed no regression.
All fixed decisions, scores, depths, nodes, and checksums remained exact; the
full timed-root gate passed 50/50 at Threads=1 and 50/50 at Threads=2.

This is a verified throughput result, not an Elo result. No chess gauntlet was
run. After validation, the reviewed artifact was preserved, merged, and
deployed to `engine/target/release/pyro.exe`. The then-live Ticket #1 executable
was 356,864
bytes, MD5 `0096EAFE3395EBB14A7AD543694651A0`, SHA-256
`D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`.
Both live NNUE files remain SHA-256
`A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.

The preceding executable remains available for rollback at:

- `C:\torch_data\pyro_deploy_backups\pyro_before_ticket1_20260803_013913.exe`;
- `engine/target/release/pyro.before_ticket1.20260803_014815.replace-backup.exe`.

Both backups have SHA-256
`6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.
Post-deployment UCI startup passed with `uciok`, `readyok`, and `NNUE loaded`.
The deployed executable reproduced the exact fixed-work anchors above. The
deployment run observed 10,674 ms / 474,525 NPS for NNUE and 7,554 ms /
648,777 NPS for PeSTO; these are observations, not new timing baselines.

The real-world shakedown passed in casual 5+0 Blitz game
[`cP0rHVcl`](https://lichess.org/cP0rHVcl). PyroBotTorch played White against
TorchVision29 and won `1-0` by `13.Qf6#` after 25 legal plies. The bridge used
Threads=2 and concurrency one; five moves came from the book and eight from
search. All thirteen move submissions returned HTTP 200, every search returned
one `info` and one `bestmove`, and the engine exited 0 after orderly
`isready`/`readyok`/`quit`. The bridge recorded `Game over` and
`Process Freed. Count: 0`, remained online, and left no orphaned engine.

The bridge log names the configured executable path but contains neither a
per-process launch hash nor the stderr-only `NNUE loaded` line. Attribution is
the strong evidence-based conclusion from the pinned pre-game deployment, the
logged path, and unchanged post-game artifact—not a directly captured launch
hash. Ticket #1 is operationally closed. This one game is operational evidence,
not an Elo result or controlled benchmark.

## Ticket #2 completed, deployed, and shakedown-verified

Ticket #2 caches move-order scores once per sort in a private sparse-row
`(from_sq, to_sq)` cache while preserving the original move collection,
`sort_unstable_by`, descending relation, ordering formulas, and quiescence
capture/SEE filter. Promotion variants sharing endpoints are protected by
equality checks, and each sort owns fresh state, so Lazy SMP stays thread-local.
No search policy, evaluation, timing, node accounting, UCI, or benchmark
definition changed.

Implementation commit `ce1aa5aaeb7c9d57dd2a8a37c1546f5213d097e6`
(`perf(search): cache move ordering scores`) passed final independent review
with verdict **VERIFIED SUCCESS** and no findings, then merged into `main` as
`876632c875338a89a013d380f7fb7c3f5de958f5`. The canonical fixed-work proof
matched 40/40 rows, focused/debug/release/perft and Ticket #1 protection gates
passed, and five repeated runs retained the exact anchors:

- NNUE: 5,065,087 nodes, checksum `a8df66621c8eb452`;
- PeSTO: 4,900,866 nodes, checksum `18bd8f3c9614b0db`.

The complete timed-root gate passed: exact strict transcripts, depths 1-12,
50/50 Threads=1 incident processes, 50/50 Threads=2 incident processes, and
both preceding-position checks. An earlier isolated fixed-work timeout was
classified **TIMEOUT NOT REPRODUCED** after it did not recur across diagnostic,
canonical, timed-root, or binding performance runs.

The binding thresholds were frozen from A/A noise before candidate execution:
4.892464430694045% required NNUE improvement and 5.3297336690075525% maximum
PeSTO regression. In ten predeclared B-C-C-B pairs at identical work, NNUE
median elapsed time improved from 21,322.5 ms to 17,789.5 ms
(**16.5693516238715%**) with 10/10 pair wins. PeSTO improved from 12,456.5 ms
to 8,754.5 ms, passing its protection gate. Independent review retained the
late common-mode PeSTO timing drift. Final experimental verdict: **TICKET #2
THROUGHPUT ACCEPTED**. This is throughput evidence, not an Elo or measured
playing-strength result.

The fresh merged-main release was deployed atomically and reproduced both
deterministic anchors after deployment. The previous Ticket #1 executable,
SHA-256
`D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`,
remains available at:

- `C:\torch_data\pyro_deploy_backups\pyro_before_ticket2_20260809_092641.exe`;
- `engine/target/release/pyro.before_ticket2.20260809_092641.replace-backup.exe`.

No rollback or bridge restart was required.

The live operational shakedown passed in casual 3+2 Standard Blitz game
[`0B5jsiKu`](https://lichess.org/0B5jsiKu). PyroBotTorch played White against
TorchVision29 and won `1-0` by `37.e8=Q#` after 73/73 legal plies. Two Pyro
moves came from the book and 35 from search; all 35 searches produced results.
The engine exited 0, the bridge logged `Game over` and
`Process Freed. Count: 0`, and no timeout, illegal response, failed submission,
API error, missing/duplicate response, or orphan remained.

The launch log identifies the configured path but does not directly capture
PID 8912's binary hash or a game-specific literal `NNUE loaded` line. The game
therefore has strong evidence-based attribution to the deployed Ticket #2
artifact, and NNUE use is strongly inferred from normal launch plus the pinned
sibling net and default configuration. This game is operational-health
evidence, not benchmark or Elo evidence. **TICKET #2 OPERATIONALLY CLOSED.**
No further Ticket #2 engine work or rollback is pending.

## Next planning boundary

Ticket #2 is finished. No next engine ticket is selected or authorized by this
handoff. Any further engine change requires a separate planning task and
explicit implementation authorization; Ticket #16 and every other roadmap
candidate remain separate and unauthorized.

Verify live hashes, rollback copies, bridge state, and active engine processes
before future operational work. Old merged branch references, bridge upstream
updates, README corrections, persistent autostart, and future deployments
remain separate decisions.

## Governing references

- Current truth: `docs/PROJECT_STATE.md`
- Operating rules: `AGENTS.md`
- Detailed history: `HISTORY.md`
- Strength audit and ticket definitions: `STRENGTH_AUDIT.md`
- Authorization-aware roadmap: `docs/ROADMAP.md`
- Timed-root verifier: `backend/scripts/verify_timed_root_completion.py`
