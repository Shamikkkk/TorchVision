# Pyro Elo Gauntlet

Measures Pyro's strength against Stockfish at calibrated UCI_Elo
levels (anchored to CCRL Blitz at 120+1 time control).

## Quick test (10 games per opponent, fast TC)
    bash run_gauntlet.sh 10 10+0.1
    # ~10 min per opponent, 4 opponents = ~40 min total
    # Confidence intervals are wide; result is directional only

## Real measurement (200 games per opponent, calibrated TC)
    bash run_gauntlet.sh 200 60+0.6
    # ~3-4 hours per opponent, 4 opponents = overnight run
    # CI ~ ±50 Elo per matchup

## Results
PGN files saved to ./results/pyro_vs_sfNNNN_TIMESTAMP.pgn
Use ordo or bayeselo to compute Elo from PGN.

## Opponent ladder
- SF-1500: weak amateur
- SF-1700: club player (target zone for current Pyro)
- SF-1900: strong club player
- SF-2100: expert (target zone for Phase G complete)

## Interpreting results
Pyro's Elo = SF opponent's Elo + (Pyro's score% - 50%) * ~7
So Pyro scoring 60% vs SF-1700 implies Pyro ~ 1770.
For a real number, run all 4 opponents and average.
