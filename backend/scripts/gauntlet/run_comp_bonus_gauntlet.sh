#!/usr/bin/env bash
# COMP_BONUS EXPERIMENT (July 2026) — Threads=1, TC 10+0.1, COMP_BONUS=100
# Pyro(--no-nnue, COMP_BONUS=100, DYNAMIC_BONUS unset) vs SF-1700 and SF-1900,
# 100 games each. Measure vs T1 anchor: 44.3% vs SF-1700, 33.8% vs SF-1900
# (~1721). Style clause measured with aggression_rate.py vs T1 style anchor
# (agg 77.2% / kz_sac 31.0% / sacs_pg 1.30 / kz_sacs_pg 0.35).
# Working rule 8: timestamped log names — a re-invocation never overwrites.

set -euo pipefail

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="/c/Users/shami/OneDrive/Documents/torch/engine/target/release/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"
OUTDIR="/c/Users/shami/OneDrive/Documents/torch/backend/scripts/gauntlet/results/comp_bonus_2026-07"
TC="10+0.1"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$OUTDIR"
RUNLOG="$OUTDIR/run_${STAMP}.log"
echo "=== COMP_BONUS=100 EXPERIMENT START $(date) ===" | tee -a "$RUNLOG"

echo "--- (1) Pyro(CB=100) vs SF-1700 : 100 games ---" | tee -a "$RUNLOG"
"$CUTECHESS" \
  -engine name="Pyro-CB100" cmd="$PYRO" arg="--no-nnue" option."COMP_BONUS"=100 \
  -engine name="SF-1700"    cmd="$STOCKFISH" \
    option."UCI_LimitStrength"=true option."UCI_Elo"=1700 \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 50 -games 2 -repeat -recover \
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

echo "=== COMP_BONUS=100 EXPERIMENT COMPLETE $(date) ===" | tee -a "$RUNLOG"
