# Pyro concise handoff

Verified: August 3, 2026.

## Current state

- Repository: `C:\Users\shami\OneDrive\Documents\torch`. Ticket #1 was
  preserved as `0aee7d72f89027b14071c1ed90e9595bf5deb215` and merged through
  pull request #1 into `main` by
  `a3a997cb366ab95ae7b3926f7588fd41472e392e`. Check Git for current branch,
  HEAD, and preservation state rather than treating this snapshot as permanent.
- The deployed engine defaults to the style-gated SCReLU-512 NNUE. The
  application uses Threads=4; `PYRO_NO_NNUE=1` retains the protected
  PeSTO+Tal `--no-nnue` fallback.
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
preserved and is present in the Ticket #1 live executable described below.

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
deployed to `engine/target/release/pyro.exe`. The live executable is 356,864
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

## Immediate action and next planning item

Before Ticket #2 planning, confirm from Git whether this five-file
deployment-and-shakedown documentation update has been reviewed and preserved.
If it has not, preserve it first through user-controlled review, staging,
commit, and push.

Once preservation is confirmed, Ticket #2 — removing repeated move scoring
inside the sort comparator — is the sole next planning item. It must begin as a
separate Plan-mode task; implementation is not automatically authorized and has
not begun. Ticket #16 and every other strength change remain separate and
unauthorized.

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
