#!/usr/bin/env bash
# Pyro Elo gauntlet via cutechess-cli.
# Plays Pyro vs Stockfish at multiple UCI_Elo levels.
# Usage: ./run_gauntlet.sh [games_per_opponent] [tc]
#   games_per_opponent: default 10 (use 100-200 for real measurement)
#   tc: default "10+0.1" (use "60+0.6" or "120+1" for accurate Elo)

set -euo pipefail

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="$(cd "$(dirname "$0")/../../../engine/target/release" && pwd)/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"

GAMES="${1:-10}"
TC="${2:-10+0.1}"

OPPONENTS=(1500 1700 1900 2100)

OUTDIR="$(cd "$(dirname "$0")" && pwd)/results"
mkdir -p "$OUTDIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "Pyro Gauntlet"
echo "  Pyro:      $PYRO"
echo "  Stockfish: $STOCKFISH"
echo "  Games per opponent: $GAMES"
echo "  Time control: $TC"
echo "  Results dir: $OUTDIR"
echo

for ELO in "${OPPONENTS[@]}"; do
    echo "=========================================="
    echo "Pyro vs Stockfish-$ELO ($GAMES games, $TC)"
    echo "=========================================="

    PGN_FILE="$OUTDIR/pyro_vs_sf${ELO}_${TIMESTAMP}.pgn"

    "$CUTECHESS" \
      -engine name="Pyro" cmd="$PYRO" arg="--no-nnue" \
      -engine name="SF-$ELO" cmd="$STOCKFISH" \
        option."UCI_LimitStrength"=true \
        option."UCI_Elo"=$ELO \
      -each proto=uci tc="$TC" \
      -rounds $((GAMES / 2)) \
      -games 2 \
      -repeat \
      -recover \
      -pgnout "$PGN_FILE" \
      -ratinginterval 1

    echo
    echo "PGN saved to: $PGN_FILE"
    echo
done

echo "Gauntlet complete. PGN files in: $OUTDIR"
echo "To compute Elo from PGNs, use bayeselo or ordo on the combined PGN."
