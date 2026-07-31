# Pyro concise handoff

Verified: August 1, 2026.

## Current state

- Repository: `C:\Users\shami\OneDrive\Documents\torch`, branch `main`,
  committed context baseline `1ecbc83842941e00c006f31fa718af97f618f6ac`.
- The deployed engine defaults to the style-gated SCReLU-512 NNUE. The
  application uses Threads=4; `PYRO_NO_NNUE=1` retains the protected
  PeSTO+Tal `--no-nnue` fallback.
- PyroBotTorch is online through the external native Python lichess-bot bridge
  at `C:\lichess-bot`. The bridge intentionally uses Threads=2, accepts one
  game at a time, and remains running while idle. No `pyro.exe` process is
  expected until an eligible game begins.
- There is no persistent watchdog or autostart. Sleep, logout, reboot, or a
  process failure will take the bot offline.

## Live correctness shakedown passed

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

## Next authorized engineering task

The sole authorized next task is `STRENGTH_AUDIT.md` ticket #19:

- deterministic `bench`;
- completed-search `info nodes ... nps ...` instrumentation;
- no intended search, evaluation, timing-policy, TT, move-ordering, or
  production-default change;
- exact decision-tuple equivalence and deterministic benchmark node
  count/checksum;
- mandatory timed-root regression at Threads=1 and Threads=2;
- no gauntlet unless behavior changes unexpectedly or an Elo claim is made.

Ticket #19 must remain instrumentation-only and must not be combined with an
optimization. This documentation update does not implement it.

Old merged branch references may be cleaned up later, but deletion is optional
and non-urgent. Bridge upstream updates, README corrections, persistent
autostart, and all other strength tickets remain separate decisions.

## Governing references

- Current truth: `docs/PROJECT_STATE.md`
- Operating rules: `AGENTS.md`
- Detailed history: `HISTORY.md`
- Strength audit and ticket definitions: `STRENGTH_AUDIT.md`
- Authorization-aware roadmap: `docs/ROADMAP.md`
- Timed-root verifier: `backend/scripts/verify_timed_root_completion.py`
