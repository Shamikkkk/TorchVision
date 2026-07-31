# Pyro project state

Verification snapshot: **July 31, 2026** at
`181f679709c82625172355d1ef34f9d8685fb654`.

Labels used below:

- **Verified current fact**: reproduced from the current repository,
  filesystem, report contents, hashes, or process table during this audit.
- **Historically reported fact**: preserved in committed history or the July
  31 handoff, but not independently replayed by this documentation-only audit.
- **Unavailable evidence**: the supporting event or system was not available
  for direct inspection.

## Repository

- **Verified current fact:** repository
  `C:\Users\shami\OneDrive\Documents\torch` is on branch `main` at
  `181f679709c82625172355d1ef34f9d8685fb654`.
- **Verified current fact:** local `origin/main` points to the same commit;
  `HEAD...origin/main` is `0 0`. No fetch was performed, so this describes the
  local remote-tracking ref rather than a fresh query of the server.
- **Verified current fact:** the exact ancestry is
  `b6c3277dd1f2ac7415f1a799756602f7b30a0839` -> fix
  `5469931e6653b58ddec8f068614ab42c4c9422ed` -> merge
  `203b60856fd0b651c73ce814926fb3266c31bf9d` -> docs
  `181f679709c82625172355d1ef34f9d8685fb654`.
- **Verified current fact:** `203b608...` is a two-parent merge of
  `b6c3277...` and `5469931...`; therefore the timed-root fix is present in
  current `main`.
- **Verified current fact:** the worktree began this audit with exactly
  ` m bullet` and nothing staged. The parent index stores `bullet` as gitlink
  mode `160000` at `cebc78a093d92cbc87e56cfef049184c225270b0`; its nested HEAD
  is unchanged at that commit. The lowercase `m` means the nested worktree has
  modified tracked content. Porcelain v2 also reports untracked nested files.
  The checkout has its own `.git` directory but the parent has no
  `.gitmodules`, so it is a nested Git repository represented by a
  submodule-style gitlink, not an ordinary directory.
- **Verified current fact:** this reconciliation intentionally adds untracked
  `AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/HANDOFF.md`, and
  `docs/ROADMAP.md`. Nothing is staged; Git history and refs are unchanged by
  this task.

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

- **Verified current fact:** live executable
  `engine/target/release/pyro.exe` is `313344` bytes, MD5
  `275BCC9D86056839A35A71F4D39CDA14`, SHA-256
  `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.
- **Verified current fact:** the surviving fresh candidate at
  `C:\torch_data\pyro_timed_root_redeploy_20260731_5469931_r2\target\release\pyro.exe`
  has identical size, MD5, and SHA-256.
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

- **Verified current fact:** no `pyro.exe`, native lichess-bot, or
  PyroBotTorch process is running. Docker is stopped/unavailable, with no
  running related container. PyroBotTorch is offline.
- **Verified current fact:** `README.md` describes the deployed Lichess-bot
  capability and also says it is online only while the bridge runs. Its
  checked roadmap item is not evidence that the bridge is currently running;
  the process audit is authoritative for current availability.
- **Verified current fact:** the latest committed task is the July 31
  timed-root-completion historical record and standing regression gate at
  `181f679...`. This reconciliation adds only uncommitted context documents.
- **Verified current fact:** open, unscheduled product issues remain in
  `CLAUDE.md`: eager loading of an unused Python NNUE model, client-only voice
  state, and the old `python-chess` dependency.
- **Historically reported fact:** Pyro still emits mate-range UCI scores as
  centipawns rather than `score mate N`; this cosmetic issue was outside the
  timed-root fix.
- **Candidate, not authorized:** the strength and data work in
  `STRENGTH_AUDIT.md` and `docs/ROADMAP.md` is planning material, not an active
  implementation mandate.

## Next decision

- **Immediate pending decision:** the user reviews and either accepts or rejects
  the four untracked context documents. If accepted, only the user may preserve
  them through the user's Git workflow; no agent Git action is authorized.
- **Separate blocked operational decision:** PyroBotTorch remains offline unless
  the user explicitly authorizes restarting the external lichess-bot bridge.
  Accepting these documents does not authorize a bot restart, deployment, or
  engine experiment.
