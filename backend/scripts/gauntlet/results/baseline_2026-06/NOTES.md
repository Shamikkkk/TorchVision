# VERIFIED BASELINE (June 2026) — session notes

## Pre-flight (Step 0)
- Commit: b8e25f0b3aea5acc3960794d0046cbf7dcbc8e45  "docs: record G2 validation results and search regression findings"
- git status: only `m bullet` (clean)
- Binary md5: 587567f2bbd5ce54e40481b7cc9ccea6  (engine/target/release/pyro.exe)
- UCI sanity: Threads default=1 confirmed; go wtime 10000 → bestmove b1c3 (legal)
- cutechess + SF18 paths verified

## Prediction (Step 1 — written before any games)
- RUN 1 (Threads=1): ~50% vs SF-1700, ~30-35% vs SF-1900 → implied ~1690-1720.
- RUN 2 (Threads=4): within ±25 Elo of RUN 1 (June 5 self-play said SMP ≈ neutral).

## Results (Step 5)

Anchor: commit b8e25f0b3aea5acc3960794d0046cbf7dcbc8e45, binary md5 587567f2bbd5ce54e40481b7cc9ccea6, --no-nnue, TC 10+0.1, concurrency=1, no opening book.

### RUN 1 — Threads=1 (canonical anchor, 200 games/opp)
| Opponent | W-L-D     | Score% | Elo diff ±CI    | Implied Pyro |
|----------|-----------|--------|-----------------|--------------|
| SF-1700  | 80-103-17 | 44.3%  | -40.1 ± 46.6    | ~1660        |
| SF-1900  | 60-125-15 | 33.8%  | -117.2 ± 49.1   | ~1783        |
| **avg**  |           |        |                 | **~1721**    |

### RUN 2 — Threads=4 (production config, 100 games/opp)
| Opponent | W-L-D    | Score% | Elo diff ±CI   | Implied Pyro |
|----------|----------|--------|----------------|--------------|
| SF-1700  | 53-31-16 | 61.0%  | +77.7 ± 64.4   | ~1778        |
| SF-1900  | 42-53-5  | 44.5%  | -38.4 ± 67.5   | ~1862        |
| **avg**  |          |        |                | **~1820**    |

### SMP verdict (T4 vs T1 at the SF-ladder)
- vs SF-1700: +117.8 Elo (T4 +77.7 vs T1 -40.1). CIs do NOT overlap → SIGNIFICANT.
- vs SF-1900: +78.8 Elo (T4 -38.4 vs T1 -117.2). CIs overlap slightly → suggestive.
- VERDICT: SMP is POSITIVE on the SF-ladder (~+80-118 Elo), NOT neutral.
  CONTRADICTS June-5 self-play (T4 vs T1 = 49%) and my RUN 2 prediction (±25 Elo).
  Likely cause: self-play A/B understates SMP; extra ply only shows vs a fixed external ladder.
  NOTE: T4 ~1820 is close to the retired "1835" figure → the old number was probably a Threads=4 measurement.

### Style (Step 4)
| Run | aggression_rate | kz_sac_rate | sacs/game | kz_sacs/game |
|-----|-----------------|-------------|-----------|--------------|
| RUN 1 (T1, 400g) | 77.2% | 31.0% | 1.30 | 0.35 |
| RUN 2 (T4, 200g) | 71.0% | 38.0% | 1.20 | 0.42 |

### Predictions held?
- RUN 1: MOSTLY HELD. SF-1900 33.8% (predicted 30-35% ✓), implied ~1721 (predicted 1690-1720, top edge ✓), SF-1700 44.3% (predicted ~50%, slightly under).
- RUN 2: FAILED. Predicted T4 within ±25 Elo of T1; actual T4 is +80-118 Elo stronger.

### Crashes/disconnects
None. All 600 games completed; cutechess exit code 0. -recover never needed to substitute.

