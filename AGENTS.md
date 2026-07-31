# Pyro repository operating rules

These rules apply to the entire repository. Detailed history belongs in
`HISTORY.md`; current verified state belongs in `docs/PROJECT_STATE.md`.

## Evidence and scope

- Verify repository-dependent premises before editing. Inspect the worktree,
  relevant source, artifacts, processes, and Git graph as appropriate.
- Repository and runtime evidence outrank prompt assumptions. Report and
  reconcile a disagreement; do not silently encode a stale premise.
- Distinguish verified evidence, historical reports, interpretation, and
  recommendation. Never promote an unverified report to current fact.
- Stop when a mandatory correctness, isolation, or methodology gate fails.
  Do not repair an audit discrepancy unless the user separately authorizes it.
- Make only changes required by the task. Do not perform unrelated cleanup,
  including cleanup inside the dirty `bullet` gitlink checkout.

## Git custody

- Do not stage, commit, push, pull, fetch, merge, rebase, reset, stash, clean,
  switch branches, update submodules, or otherwise alter Git history or refs.
- The user controls Git operations. Read-only Git inspection is allowed when
  needed to verify a task.

## Engine experiment methodology

- Change one conceptual variable per experiment. If that variable cannot be
  named precisely, stop and ask.
- State a falsifiable prediction before measuring and record whether it held.
- When production behavior should be unchanged, require a no-op proof. A new
  UCI option must default off/zero and be byte-identical at its default before
  any gauntlet.
- Gauntlet results are ground truth for strength decisions; depth, NPS,
  training loss, and correlation gates are supporting evidence, not strength
  verdicts.
- Use at least 100 games for a verdict and 150-200 games to establish a
  baseline. Never make a code decision from a 20-30 game match.
- Preserve the fixed binary/net, opponent ladder, time control, threads,
  concurrency, book, Syzygy, and other configuration for controlled
  comparisons. For depth/SMP changes, use the fixed ladder rather than
  self-play; self-play is acceptable for fixed-thread ordering/eval changes.
- Account for run-to-run variance. A single 100-game leg does not override
  pooled multi-instrument evidence.
- Any change that can affect search timing must run
  `backend/scripts/verify_timed_root_completion.py` at the exact incident
  clock with fresh processes at Threads=1 and Threads=2: at least 10
  repetitions each, preferably 50, with zero non-mating results.

## Live runtime and operations

- The verified live application default is SCReLU-512 NNUE. PeSTO+Tal via
  `--no-nnue` (or `PYRO_NO_NNUE=1` through the app) is the protected fallback.
  Verify the actual startup command whenever evaluation mode matters.
- Do not deploy binaries or nets, alter bridge configuration, start Docker,
  restart services, or bring PyroBotTorch online without explicit authority.
- Preserve the PeSTO fallback and `engine/pyro_pesto_era_backup.nnue`.
- Long jobs must be detached, resumable, observable through durable logs or
  checkpoints, and non-blocking. On Windows, verify process command lines and
  file timestamps rather than trusting completion notifications; include
  keep-awake, memory, worker-death, and duplicate-launch guards appropriate to
  the job.

## Reporting

- Record exact paths, commits, hashes, configurations, commands, exit codes,
  and relevant output for verification work.
- Keep recommendation separate from execution. Do not perform the recommended
  next action unless the user authorizes it.
