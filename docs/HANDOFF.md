# Pyro concise handoff

Verified: August 2, 2026.

## Current state

- Repository: `C:\Users\shami\OneDrive\Documents\torch`. At the August 2
  pre-commit baseline it was on branch `main` at
  `46d8c36c5d2a910b55e060db83c0cecedb8471a8`; check Git for the current branch,
  HEAD, and Ticket #19 preservation status.
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
It was not deployed during validation, and deployment remains a separate
explicit action. The live executable remained SHA-256
`6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.

## Immediate action and next planning item

If the complete reviewed Ticket #19 implementation and documentation set has
not yet been committed and pushed, preserve it first through user-controlled
review, staging, commit, and push. Confirm preservation from Git rather than
assuming the August 2 pre-commit snapshot is still current.

Once Ticket #19 preservation is confirmed, Ticket #1 — incremental SCReLU-512
NNUE accumulator integration — is the sole next planning item. It must begin as
a separate planning task; implementation is not automatically authorized and
has not begun. No other strength ticket is authorized.

Old merged branch references, bridge upstream updates, README corrections,
persistent autostart, and deployment remain separate decisions.

## Governing references

- Current truth: `docs/PROJECT_STATE.md`
- Operating rules: `AGENTS.md`
- Detailed history: `HISTORY.md`
- Strength audit and ticket definitions: `STRENGTH_AUDIT.md`
- Authorization-aware roadmap: `docs/ROADMAP.md`
- Timed-root verifier: `backend/scripts/verify_timed_root_completion.py`
