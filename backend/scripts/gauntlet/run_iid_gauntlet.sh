#!/usr/bin/env bash
# IID RE-ADD EXPERIMENT — Threads=1, TC 10+0.1
# (A) SF-ladder:    Pyro(IID on) vs SF-1700, SF-1900 — 100 games each
# (B) Direct A/B:   Pyro(IID on) vs Pyro(IID off), same binary — 100 games
# Measure (A) against T1 anchor: 44.3% vs SF-1700, 33.8% vs SF-1900.
# (B) is corroborating signal only; SF-ladder is the primary verdict.

set -euo pipefail

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="/c/Users/shami/OneDrive/Documents/torch/engine/target/release/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"
OUTDIR="/c/Users/shami/OneDrive/Documents/torch/backend/scripts/gauntlet/results/iid_experiment"
TC="10+0.1"

mkdir -p "$OUTDIR"
LOG="$OUTDIR/run.log"
echo "=== IID EXPERIMENT START $(date) ===" | tee "$LOG"

# (A) SF-ladder: Pyro(IID on, Threads=1) vs SF-1700
echo "--- (A1) Pyro(IID on) vs SF-1700 : 100 games ---" | tee -a "$LOG"
"$CUTECHESS" \
  -engine name="Pyro-IID" cmd="$PYRO" arg="--no-nnue" option."IID_ENABLE"=true \
  -engine name="SF-1700"  cmd="$STOCKFISH" \
    option."UCI_LimitStrength"=true option."UCI_Elo"=1700 \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 50 -games 2 -repeat -recover \
  -ratinginterval 10 \
  -pgnout "$OUTDIR/iid_vs_sf1700.pgn" 2>&1 | tee "$OUTDIR/iid_vs_sf1700.log"

echo "--- (A2) Pyro(IID on) vs SF-1900 : 100 games ---" | tee -a "$LOG"
"$CUTECHESS" \
  -engine name="Pyro-IID" cmd="$PYRO" arg="--no-nnue" option."IID_ENABLE"=true \
  -engine name="SF-1900"  cmd="$STOCKFISH" \
    option."UCI_LimitStrength"=true option."UCI_Elo"=1900 \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 50 -games 2 -repeat -recover \
  -ratinginterval 10 \
  -pgnout "$OUTDIR/iid_vs_sf1900.pgn" 2>&1 | tee "$OUTDIR/iid_vs_sf1900.log"

# (B) Direct A/B: IID on vs IID off, same binary, 100 games
echo "--- (B) Pyro(IID on) vs Pyro(IID off) : 100 games ---" | tee -a "$LOG"
"$CUTECHESS" \
  -engine name="Pyro-IID-on"  cmd="$PYRO" arg="--no-nnue" option."IID_ENABLE"=true \
  -engine name="Pyro-IID-off" cmd="$PYRO" arg="--no-nnue" option."IID_ENABLE"=false \
  -each proto=uci tc="$TC" \
  -concurrency 1 -rounds 50 -games 2 -repeat -recover \
  -ratinginterval 10 \
  -pgnout "$OUTDIR/iid_ab_selfplay.pgn" 2>&1 | tee "$OUTDIR/iid_ab_selfplay.log"

echo "=== IID EXPERIMENT COMPLETE $(date) ===" | tee -a "$LOG"
