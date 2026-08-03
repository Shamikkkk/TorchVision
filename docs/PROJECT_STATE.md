# Pyro project state

Ticket #1 deployment and shakedown snapshot: **August 3, 2026**. Ticket #1 was
preserved as `0aee7d72f89027b14071c1ed90e9595bf5deb215` and merged through
pull request #1 into `main` by
`a3a997cb366ab95ae7b3926f7588fd41472e392e`. This records the verified
deployment-time state; current Git and runtime state must still be checked
rather than inferred from this snapshot.

Labels used below:

- **Verified current fact**: reproduced from the current repository,
  filesystem, report contents, hashes, or process table during this audit.
- **Historically reported fact**: preserved in committed history or the July
  31 handoff, but not independently replayed by this documentation-only audit.
- **Unavailable evidence**: the supporting event or system was not available
  for direct inspection.

## Repository

- **August 3, 2026 deployment-documentation fact:** repository
  `C:\Users\shami\OneDrive\Documents\torch` was on `main`; local `HEAD`, local
  `main`, and remote `origin/main` all matched merge commit
  `a3a997cb366ab95ae7b3926f7588fd41472e392e`. The complete worktree status was
  only the pre-existing lowercase ` m bullet`, with nothing staged, before this
  five-file documentation update. Current state must be checked from Git.
- **Verified fact:** Ticket #1 implementation commit
  `0aee7d72f89027b14071c1ed90e9595bf5deb215`, titled
  `feat(engine): add incremental SCReLU-512 accumulators`, was merged through
  pull request #1 by `a3a997c...`.
- **Verified current fact:** the relevant ancestry is
  `b6c3277dd1f2ac7415f1a799756602f7b30a0839` -> fix
  `5469931e6653b58ddec8f068614ab42c4c9422ed` -> merge
  `203b60856fd0b651c73ce814926fb3266c31bf9d` -> incident docs
  `181f679709c82625172355d1ef34f9d8685fb654` -> context baseline
  `1ecbc83842941e00c006f31fa718af97f618f6ac` -> live-shakedown docs
  `46d8c36c5d2a910b55e060db83c0cecedb8471a8` -> Ticket #19 preservation
  `1bf38f449b5efe1879818522a4a5771a10e8eb32`.
- **Verified current fact:** `203b608...` is a two-parent merge of
  `b6c3277...` and `5469931...`; therefore the timed-root fix is present in
  the feature branch's base history.
- **August 2, 2026 Ticket #1 pre-commit verification fact:** the worktree
  contained the eight reviewed Ticket #1 implementation/verification files,
  these five documentation updates, and the pre-existing ` m bullet`, with
  nothing staged. The parent
  index stores `bullet` as gitlink mode `160000` at
  `cebc78a093d92cbc87e56cfef049184c225270b0`;
  its nested HEAD is unchanged at that commit. The lowercase `m` means the
  nested worktree has modified tracked content. Porcelain v2 also reports
  untracked nested files. The checkout has its own `.git` directory but the
  parent has no `.gitmodules`, so it is a nested Git repository represented by
  a submodule-style gitlink, not an ordinary directory.
- **Verified current fact:** `AGENTS.md`, `docs/PROJECT_STATE.md`,
  `docs/HANDOFF.md`, and `docs/ROADMAP.md` are committed by the context-baseline
  commit `1ecbc838...`; they are no longer untracked review artifacts.

## Ticket #19 search-throughput instrumentation

- **Verified current fact:** Ticket #19 is complete and received the final
  independent Review Agent verdict **VERIFIED SUCCESS**.
- **Verified current fact:** the implementation adds aggregate search-call
  accounting across main-thread depth attempts, aspiration re-searches,
  incomplete final iterations, and joined Lazy SMP helpers. A completed search
  emits exactly one `info depth D score cp S nodes N time T nps P` line.
- **Verified current fact:** deterministic `bench` v1 uses the canonical ten
  positions at depth 8, forced Threads=1, fresh search state per position, and
  an FNV-1a-64 checksum that excludes elapsed time and NPS.
- **Verified fact:** these five implementation files passed final review
  together and retained their reviewed hashes through documentation validation;
  their current Git preservation status must be checked from the repository:
  - `engine/src/search.rs`
  - `engine/src/main.rs`
  - `engine/src/bench.rs`
  - `backend/scripts/verify_search_throughput.py`
  - `backend/scripts/verify_timed_root_completion.py`
- **Verified current fact:** fixed-depth equivalence passed 40/40 legal decision
  tuples. Benchmark totals were deterministic at 5,065,087 nodes / checksum
  `a8df66621c8eb452` for NNUE and 4,900,866 nodes / checksum
  `18bd8f3c9614b0db` for PeSTO.
- **Verified current fact:** the hardened false-pass harness passed 26/26 cases;
  debug and release tests each passed 32/32 + 46/46; perft remained
  `20 / 400 / 8,902`; SCReLU verification remained 10,000/10,000 exact; and
  retained timed-root results remained 50/50 legal immediate mates at each of
  Threads=1 and Threads=2.
- **Verified current fact:** reports and immutable candidate artifacts are under
  `C:\torch_data\pyro_ticket19_20260801_46d8c36`. The isolated candidate is
  327,168 bytes, SHA-256
  `906E06247DE3D68D80639E7CDF63519DFD7167D191BB1E401FC0D2CB551ABF00`.
  It has not been deployed. Ticket #19 makes no Elo or speed-improvement claim.

## Ticket #1 incremental SCReLU-512 accumulators

- **Verified current fact:** Ticket #1 is complete and final independent review
  found no issue in the complete thirteen-file implementation and
  documentation set. It was preserved, merged, deployed, and operationally
  verified; current preservation must still be checked from Git rather than
  assumed from this snapshot.
- **Verified current fact:** incremental state is derived from authoritative
  parent/child piece-bitboard differences across the centralized twelve NNUE
  planes. A searched child clones its parent accumulator, removes parent-only
  features, adds child-only features, and updates both fixed perspectives.
  Private per-thread search stacks provide one full construction per independent
  NNUE root, independent Lazy SMP helper roots/stacks, reused child state across
  PVS/LMR re-searches, and unchanged raw lanes for null moves. PeSTO has no NNUE
  accumulator work, and recursive production evaluation performs no full
  reconstruction.
- **Verified current fact:** the seed-`20260802` corpus at
  `C:\torch_data\pyro_ticket1_20260802_1bf38f4\corpus\incremental_sequences_10000_exact_ep.tsv`
  is 72,038 bytes, SHA-256
  `3DD95476383233A63667C05FED8FBCD5702E3193266C971C99F2AAE2A17EC909`.
  It contains 10,330 transitions, 10,107 canonical non-null positions, and 128
  canonical null sources split 64/64 by side to move, with zero representative-
  FEN round-trip mismatch.
- **Verified current fact:** Rust incremental, Rust full, and independent Python
  full reconstruction agreed exactly on 10,577,920 raw lanes, 21,155,840 raw
  comparisons, and 10,330 final-cp comparisons, with zero illegal transition or
  mismatch. Frozen SCReLU verification remained 10,000/10,000 exact plus 8/8
  boundary cases.
- **Verified current fact:** debug and release tests each passed 34 verifier +
  49 engine tests; release binaries built; perft remained `20 / 400 / 8,902`;
  fixed-depth equivalence passed 40/40; and deterministic work remained NNUE
  5,065,087 / `a8df66621c8eb452` and PeSTO 4,900,866 /
  `18bd8f3c9614b0db`. Strict PeSTO no-op, preceding-position checks, and the
  timed-root gate (50/50 at Threads=1 and 50/50 at Threads=2) all passed.
- **Verified current fact:** controlled identical-work NNUE timing improved
  from 18,945 ms to 10,711 ms median (**43.463%**), with median NPS increasing
  from 267,362 to 472,918.5 and 10/10 paired wins. The result cleared the
  precommitted timing-noise threshold. PeSTO improved 2.609% with no regression.
  Decisions, scores, depths, nodes, and checksums remained exact.
- **Verified current fact:** the 356,864-byte isolated candidate at
  `C:\torch_data\pyro_ticket1_20260802_1bf38f4\artifacts\candidate\pyro.exe`
  has MD5 `0096EAFE3395EBB14A7AD543694651A0` and SHA-256
  `D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`.
  It was not deployed during validation; the byte-identical artifact was later
  deployed through a separately authorized operation. This is a verified
  same-work NNUE throughput improvement, not an Elo result; no chess gauntlet
  was run.

## Timed-root-completion fix

- **Verified current fact:** commit
  `5469931e6653b58ddec8f068614ab42c4c9422ed`,
  `fix(search): preserve completed result on timeout`, changes exactly:
  - `engine/src/search.rs` (`404` insertions, `3` deletions; diffstat
    `+407/-3`), adding test-only interruption scaffolding and making both
    post-child budget windows mark a root iteration incomplete before break.
  - `backend/scripts/verify_timed_root_completion.py` (`476` insertions), a
    fresh-process verifier for fixed-depth transcripts, the incident position,
    repeated Threads=1/2 production-clock runs, and the preceding `Nh3+`
    position.
- **Verified current fact:** the production path no longer conditions the
  pre-score incomplete marker on `best.is_none()`, and the post-score expiry
  now sets `completed = false`. The last fully completed
  `(bestmove, score, depth)` tuple is preserved.
- **Verified current fact:** documentation commit
  `181f679709c82625172355d1ef34f9d8685fb654` changes only `CLAUDE.md`,
  `HISTORY.md`, and `STRENGTH_AUDIT.md`; it changes no engine code.
- **Historically reported fact:** the Lichess `6Iy2yfnM` forensic narrative,
  initial 0/10 versus 8/10 reproduction, Stockfish 18 depth-24 confirmation,
  deterministic hook isolation audit, and first deployment rollback are
  recorded in `HISTORY.md`. They were not rerun by this audit.

## Deployment and NNUE

- **August 3, 2026 deployment fact:** live executable
  `engine/target/release/pyro.exe` is 356,864 bytes, MD5
  `0096EAFE3395EBB14A7AD543694651A0`, SHA-256
  `D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`.
- **Verified deployment fact:** the preceding live executable is preserved at
  `C:\torch_data\pyro_deploy_backups\pyro_before_ticket1_20260803_013913.exe`
  and
  `engine/target/release/pyro.before_ticket1.20260803_014815.replace-backup.exe`.
  Both rollback copies have SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.
- **Verified deployment fact:** the live executable passed exit-0 UCI startup
  with `uciok`, `readyok`, and `NNUE loaded`; no residual engine process
  remained. At Threads=1, deployment validation reproduced NNUE 5,065,087
  nodes / `a8df66621c8eb452` and PeSTO 4,900,866 nodes /
  `18bd8f3c9614b0db`. The observed 10,674 ms / 474,525 NPS for NNUE and
  7,554 ms / 648,777 NPS for PeSTO are run-specific observations, not new
  baselines. The PeSTO fallback message was also confirmed.
- **Verified historical artifact:** the surviving timed-root candidate at
  `C:\torch_data\pyro_timed_root_redeploy_20260731_5469931_r2\target\release\pyro.exe`
  is 313,344 bytes, MD5 `275BCC9D86056839A35A71F4D39CDA14`, SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.
- **Verified current fact:** the earlier isolated candidate used by
  `harness_fix_isolation.json` still exists at
  `C:\torch_data\pyro_timed_root_deploy_20260731_5469931\target\release\pyro.exe`;
  it is `313344` bytes, MD5 `360CA70477FCE0D6F85B9FC7D969CB04`, SHA-256
  `3EE18F89B6E29958919BDB777590A54556B36AA1D8E98DAB3BFC73A2256025A5`.
- **Verified current fact:** rollback executable
  `C:\torch_data\pyro_deploy_backups\pyro_before_timed_root_redeploy_20260731_5469931_r2.exe`
  is `313344` bytes with SHA-256
  `3F09FC38D7B89DAA9B86FE965BEAAC511528D63E82FEEEE9F258CB11E03F03F7`.
- **Verified current fact:** both `engine/pyro.nnue` and
  `engine/target/release/pyro.nnue` are byte-identical, `789538` bytes, MD5
  `9F01010BFE8B41193F77A9FAD88ABD56`, SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
- **Verified current fact:** `engine/pyro_pesto_era_backup.nnue` remains MD5
  `23BFCD331411B8B9C6A05191D42CAEF5`.
- **Verified current fact:** `backend/app/engine/rust_engine.py` launches the
  SCReLU-512 NNUE path by default and adds `--no-nnue` only when
  `PYRO_NO_NNUE=1`; it configures Threads=4. Older documents describing live
  PeSTO nets are historical and superseded by the July 26 deployment record.
- **Deployment-time observation:** lichess-bot remained on launcher PID 42132
  and interpreter PID 9600; no restart was required. These PIDs are not durable
  identifiers and must be rechecked before future operational work.

## Live Lichess state and shakedown

- **Verified current fact:** PyroBotTorch is online through the external native
  Python lichess-bot bridge at `C:\lichess-bot`. Windows represents the one
  logical bridge as a venv-launcher/interpreter process chain. There is no
  persistent watchdog or autostart; sleep, logout, reboot, or process failure
  will take the bot offline.
- **Verified current fact:** the bridge uses the same deployed SCReLU-512 NNUE
  executable but configures Threads=2. This is intentional and separate from
  the application's Threads=4 default. While waiting for challenges, no
  `pyro.exe` process is expected; the bridge creates one game-engine process
  for the single active game and releases it afterward.
- **Verified current fact:** the first post-fix live shakedown passed in casual
  5+0 standard Blitz game [`SS1KiMLB`](https://lichess.org/SS1KiMLB) against
  the allow-listed human TorchVision29. PyroBotTorch played White and won
  `1-0` by `39.Rxh7#` after 77 plies. The GM book supplied Pyro's first two
  moves; Syzygy was enabled but not relevant.
- **Verified current fact:** independent python-chess validation found all 77
  plies legal, 39 legal Pyro moves, zero parser errors, and a checkmated final
  position. There was no engine or bridge crash, illegal move, protocol error,
  timeout, timed-root-completion symptom, duplicate engine, or orphan after
  completion. The engine exited cleanly and the bridge returned to awaiting
  challenges.
- **Verified current fact:** the shakedown used executable SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`
  and NNUE SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
  The live game is correctness and operational evidence, not an Elo result.
- **August 3, 2026 Ticket #1 shakedown fact:** casual 5+0 Blitz game
  [`cP0rHVcl`](https://lichess.org/cP0rHVcl) completed successfully against
  TorchVision29. PyroBotTorch played White and won `1-0` by `13.Qf6#` after 25
  legal plies. Independent python-chess parsing found no errors and confirmed
  the final checkmate at
  `r7/pppq1p1p/3bkQ2/3Np3/4P3/8/PPP2PPP/R1B1K2R b KQ - 4 13`.
- **Verified lifecycle fact:** the bridge launched the configured live path at
  Threads=2 under concurrency one. Five Pyro moves came from the opening book
  and eight from search; all thirteen submissions returned HTTP 200, every
  searched `go` returned one `info` and one `bestmove`, and search times ranged
  from 7,610 to 9,890 ms. The process exited 0 after `isready`/`readyok`/`quit`,
  logs recorded `Game over` and `Process Freed. Count: 0`, no `pyro.exe`
  remained, and the bridge stayed online and idle. There was no timeout,
  illegal move, crash, failed submission, missing response, or process leak.
- **Attribution boundary:** the bridge log records the configured executable
  path but no per-process launch hash and no stderr-only literal `NNUE loaded`
  line. Ticket #1 attribution is the strong evidence-based conclusion from the
  pre-game deployed identity, logged path, and unchanged post-game artifact—not
  a directly captured launch hash.

## Verification evidence

- **Verified current fact:** all three referenced deployment JSON reports
  exist and are readable:
  - `C:\torch_data\pyro_timed_root_deploy_20260731_5469931\reports\harness_fix_isolation.json`
    (SHA-256
    `157E7933A8BBEC5F177DEA28D9F6E2EEB5B0BBAAA725D2F268F4AAA543720072`)
  - `C:\torch_data\pyro_timed_root_redeploy_20260731_5469931_r2\reports\candidate_smoke.json`
    (SHA-256
    `8FF0A19F4EB59F2E5CC7DE06C03A49BDBBDFB4C2CB24F130E577D7E20674A6F9`)
  - `C:\torch_data\pyro_timed_root_redeploy_20260731_5469931_r2\reports\deployed_smoke.json`
    (SHA-256
    `8069E2E3659D344D537AF4B4582932E0CFD568C2D39331E1B1F6347D11B29724`)
  `candidate_smoke.json` and `deployed_smoke.json` each contain NNUE and
  PeSTO legal startup moves plus `Qf2#` at Threads=1 and `Qg1#` at Threads=2,
  score `49999`, legal immediate mate, exit 0. The deployed report names the
  actual live executable path.
- **Verified current fact:** preserved final runtime tables under
  `C:\torch_data\pyro_root_fix_20260730_9d61d3f2\reports\timed_runtime_final`
  contain 50 Threads=1 and 50 Threads=2 incident rows, with zero failing rows
  and only score `49999`. The preceding position returns `Nh3+`, score `49995`,
  at fixed depth and original clock.
- **Verified current fact:** the saved no-op report records byte-identical
  ten-position `--no-nnue` transcripts at SHA-256
  `6BB6F5A09D92E113969F85E44DFF8C78159513B78BB89664E6DD369927D7D0DC`.
- **Verified current fact:** the saved SCReLU report records 10000/10000 exact
  cases and zero mismatches. The positions TSV is LF in Git and CRLF in this
  Windows worktree: LF SHA-256
  `BB6CD52322D47369BD35926CFE4BD7D2DAC8412E349207F91D5089D2C8115CD3`,
  worktree SHA-256
  `532A6E34583F50EE9338D334D31694F1792AADAE1BE88EE7B3CC2C6EA8B897FB`.
  Normalizing CRLF to LF reproduces the documented LF hash exactly.
- **Historically reported fact:** the exact sequence and cause of deployment
  attempt 1's dynamic-import failure and rollback is documented in
  `HISTORY.md`; no standalone failure transcript was among the three referenced
  JSON reports. The post-fix harness report and both rollback binaries survive.

## Current status and unresolved items

- **Verified current fact:** the native lichess-bot bridge is running and
  PyroBotTorch is online. No game-engine `pyro.exe` is expected while the bot
  is idle. Docker remains unused for this deployment.
- **August 3, 2026 deployment-documentation fact:** Ticket #1 is implemented,
  independently reviewed, preserved, merged into `main`, deployed, and
  operationally verified. Its live executable SHA-256 is
  `D9B378DFCD61225311C94FB481E7FC8FB9582D9F3AE358892B812E222E009119`.
  Ticket #1 is operationally closed; current Git and runtime state must still
  be checked before future work.
- **Verified current fact:** deterministic search-throughput measurement is now
  available for future exact-work comparisons.
- **Verified current fact:** Ticket #1 produced a 43.463% median NNUE
  elapsed-time improvement without changing fixed work. This is a throughput
  result only. Neither deployment validation nor the successful one-game
  shakedown adds an Elo claim, and no chess gauntlet has established a
  playing-strength increase.
- **Verified current fact:** open, unscheduled product issues remain in
  `CLAUDE.md`: eager loading of an unused Python NNUE model, client-only voice
  state, and the old `python-chess` dependency.
- **Historically reported fact:** Pyro still emits mate-range UCI scores as
  centipawns rather than `score mate N`; this cosmetic issue was outside the
  timed-root fix.
- **Not started:** Ticket #2, removing repeated move scoring inside the sort
  comparator. It is the sole next separate Plan-mode investigation after this
  deployment documentation is reviewed and preserved. Planning does not
  authorize implementation.

## Next decision

- **Immediate check:** confirm from Git whether this five-file Ticket #1
  deployment and shakedown documentation update has been reviewed and
  preserved. If it has not, preserve it first through user-controlled review,
  staging, commit, and push.
- **Once preservation is confirmed:** the next engineering phase is a separate
  Plan-mode investigation for Ticket #2. Planning does not authorize
  implementation, and the ordering-cost change has not begun.
- Branch cleanup, lichess-bot upstream updates, README corrections, persistent
  autostart/watchdog work, and all other roadmap items remain separate,
  non-authorized decisions.
