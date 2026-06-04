#!/usr/bin/env bash
# G9 gauntlet: Pyro with SPEC_BONUS=2000 vs SF-1700 and SF-1900 at 10+0.1.
# 100 games each. Pyro side runs --no-nnue (HCE only, matches baseline protocol).

set -euo pipefail

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="$(cd "$(dirname "$0")/../../../engine/target/release" && pwd)/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"

GAMES="${1:-100}"
TC="${2:-10+0.1}"
SPEC_BONUS="${3:-2000}"

OPPONENTS=(1700 1900)
OUTDIR="$(cd "$(dirname "$0")" && pwd)/results"
mkdir -p "$OUTDIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TAG="g9_spec${SPEC_BONUS}"

echo "G9 Gauntlet"
echo "  Pyro:        $PYRO"
echo "  SPEC_BONUS:  $SPEC_BONUS"
echo "  TC:          $TC"
echo "  Games/opp:   $GAMES"
echo

for ELO in "${OPPONENTS[@]}"; do
    echo "=========================================="
    echo "Pyro-G9(SPEC=$SPEC_BONUS) vs SF-$ELO  $GAMES games  $TC"
    echo "=========================================="
    PGN_FILE="$OUTDIR/pyro_${TAG}_vs_sf${ELO}_${TIMESTAMP}.pgn"
    "$CUTECHESS" \
      -engine name="Pyro-G9" cmd="$PYRO" arg="--no-nnue" option."spec_bonus"=$SPEC_BONUS \
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

echo "G9 gauntlet complete."
