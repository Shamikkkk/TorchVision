# Pyro concise handoff

Verified: July 31, 2026.

## Current objective

Maintain the deployed timed-root-completion fix and repository-backed context
without changing engine/runtime state. No strength experiment is currently
authorized.

## Latest completed work

- Timed-root fix `5469931e6653b58ddec8f068614ab42c4c9422ed` preserves the last
  fully completed root result when deadline/node budget expires.
- It entered `main` through merge
  `203b60856fd0b651c73ce814926fb3266c31bf9d`.
- Documentation commit
  `181f679709c82625172355d1ef34f9d8685fb654` recorded the incident,
  verification, deployment, and mandatory standing regression gate.

## Verified evidence

- Git: `main` and local `origin/main` are both `181f679...`; tracking count
  `0 0`. Current worktree: the pre-existing ` m bullet` plus untracked
  `AGENTS.md` and `docs/`; nothing is staged and no ref was changed.
- `bullet` is a nested repository stored as gitlink `cebc78a...`; its HEAD is
  unchanged while its nested worktree contains one tracked modification and
  untracked trainer examples. Do not touch it.
- Live `pyro.exe`: 313344 bytes, MD5 `275BCC9D86056839A35A71F4D39CDA14`,
  SHA-256 `6966D4B7A9715FA14C3DA4B67AB2187FC0BDEA956A7786E93D89AF3B076EB56B`.
- Both live NNUEs: SHA-256
  `A06CFEBD7C22D0B45F08BA94A276FD2A7CF8B3CD76C54DD308B2EEAA1A579591`.
- Runtime reports preserve 50/50 passing incident runs at Threads=1 and 50/50
  at Threads=2; deployed smoke returns `Qf2#`/`Qg1#`, score `49999`.
- App default is SCReLU-512 NNUE at Threads=4. `PYRO_NO_NNUE=1` selects the
  protected PeSTO+Tal `--no-nnue` fallback.
- No Pyro/lichess-bot process is running; Docker is stopped. PyroBotTorch is
  offline.

## Historical or unavailable evidence

- `HISTORY.md` is the authoritative historical account of game `6Iy2yfnM`,
  the pre-fix reproduction, the test-hook isolation correction, and the first
  deployment rollback. This documentation-only reconciliation did not replay
  those events.
- The exact first-attempt failure transcript was not present among the three
  referenced deployment JSON files; the corrected harness report and verified
  rollback artifacts do exist.
- Local `origin/main` was inspected without fetching; no fresh remote-server
  query was performed.

## Relevant files

- Current truth: `docs/PROJECT_STATE.md`
- Operating rules: `AGENTS.md`
- Detailed history: `HISTORY.md`
- Live context: `CLAUDE.md`
- Candidate roadmap and standing gates: `STRENGTH_AUDIT.md`, `docs/ROADMAP.md`
- Verifier: `backend/scripts/verify_timed_root_completion.py`
- Deployment reports:
  `C:\torch_data\pyro_timed_root_redeploy_20260731_5469931_r2\reports`
- Full 50+50 reports:
  `C:\torch_data\pyro_root_fix_20260730_9d61d3f2\reports\timed_runtime_final`

## One decision requiring approval

Review and either accept or reject the four untracked context documents. If
accepted, the user may preserve them through the user's own Git workflow; no
Codex Git operation is authorized.

Restarting PyroBotTorch remains a separate blocked operational action. No
engine change, strength experiment, deployment, or service restart is
currently authorized.
