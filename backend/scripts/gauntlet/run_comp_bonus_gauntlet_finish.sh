#!/usr/bin/env bash
# COMP_BONUS EXPERIMENT — clean completion after the contaminated_run1
# incident (see results/comp_bonus_2026-07/contaminated_run1/NOTE.md).
# 82 clean SF-1700 games are already in cb100_vs_sf1700.pgn; this appends the
# remaining 18, then runs the SF-1900 leg fresh (its PGN was quarantined).
# Guard: refuse to start if any cutechess/pyro/stockfish process is running.

set -euo pipefail

if tasklist //FO CSV 2>/dev/null | grep -qiE 'cutechess|pyro\.exe|stockfish'; then
  echo "FATAL: engine/match process already running — refusing to start." >&2
  exit 1
fi

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="/c/Users/shami/OneDrive/Documents/torch/engine/target/release/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"
OUTDIR="/c/Users/shami/OneDrive/Documents/torch/backend/scripts/gauntlet/results/comp_bonus_2026-07"
TC="10+0.1"
STAMP="$(date +%Y%m%d_%H%M%S)"

RUNLOG="$OUTDIR/run_${STAMP}.log"
echo "=== COMP_BONUS=100 CLEAN COMPLETION START $(date) ===" | tee -a "$RUNLOG"

echo "--- (1b) Pyro(CB=100) vs SF-1700 : 18 games (82 clean already banked) ---" | tee -a "$RUNLOG"
"$CUTECHESS" \
  -engine name="Pyro-CB100" cmd="$PYRO" arg="--no-nnue" option."COMP_BONUS"=100 \
  -engine name="SF-1700"    cmd="$STOCKFISH" \
    option."UCI_LimitStrength"=true option."UCI_Elo"=1700 \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 9 -games 2 -repeat -recover \
  -ratinginterval 10 \
  -pgnout "$OUTDIR/cb100_vs_sf1700.pgn" 2>&1 | tee -a "$OUTDIR/cb100_vs_sf1700_${STAMP}.log"

echo "--- (2) Pyro(CB=100) vs SF-1900 : 100 games ---" | tee -a "$RUNLOG"
"$CUTECHESS" \
  -engine name="Pyro-CB100" cmd="$PYRO" arg="--no-nnue" option."COMP_BONUS"=100 \
  -engine name="SF-1900"    cmd="$STOCKFISH" \
    option."UCI_LimitStrength"=true option."UCI_Elo"=1900 \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 50 -games 2 -repeat -recover \
  -ratinginterval 10 \
  -pgnout "$OUTDIR/cb100_vs_sf1900.pgn" 2>&1 | tee -a "$OUTDIR/cb100_vs_sf1900_${STAMP}.log"

echo "=== COMP_BONUS=100 CLEAN COMPLETION COMPLETE $(date) ===" | tee -a "$RUNLOG"
