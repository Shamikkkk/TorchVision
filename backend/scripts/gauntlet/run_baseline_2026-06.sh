#!/usr/bin/env bash
# VERIFIED BASELINE (June 2026) — measurement-only anchor run.
# RUN 1: Threads=1 (canonical anchor), 200 games each vs SF-1700 and SF-1900.
# RUN 2: Threads=4 (production config), 100 games each vs SF-1700 and SF-1900.
# Pyro: --no-nnue, TC 10+0.1, concurrency=1, color-paired (-repeat -games 2).
# NO code changes. NO opening book (matches established gauntlet protocol).

set -euo pipefail

CUTECHESS="/c/tools/cutechess/cutechess-1.3.1-win64/cutechess-cli.exe"
PYRO="/c/Users/shami/OneDrive/Documents/torch/engine/target/release/pyro.exe"
STOCKFISH="C:/Users/shami/Downloads/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"
OUTDIR="/c/Users/shami/OneDrive/Documents/torch/backend/scripts/gauntlet/results/baseline_2026-06"
TC="10+0.1"

mkdir -p "$OUTDIR"
MASTER_LOG="$OUTDIR/run.log"
echo "=== BASELINE 2026-06 START $(date) ===" | tee "$MASTER_LOG"

run_match () {
    local tag="$1"      # T1 or T4
    local elo="$2"      # 1700 or 1900
    local games="$3"    # 200 or 100
    local threads="$4"  # 1 or 4
    local pgn="$OUTDIR/pyro_${tag}_vs_sf${elo}.pgn"
    local log="$OUTDIR/pyro_${tag}_vs_sf${elo}.log"
    local rounds=$((games / 2))

    echo "----------------------------------------" | tee -a "$MASTER_LOG"
    echo "RUN $tag : Pyro(Threads=$threads) vs SF-$elo : $games games : $TC" | tee -a "$MASTER_LOG"
    echo "PGN: $pgn" | tee -a "$MASTER_LOG"
    echo "start $(date)" | tee -a "$MASTER_LOG"

    if [ "$threads" = "1" ]; then
        "$CUTECHESS" \
          -engine name="Pyro-$tag" cmd="$PYRO" arg="--no-nnue" \
          -engine name="SF-$elo" cmd="$STOCKFISH" \
            option."UCI_LimitStrength"=true option."UCI_Elo"=$elo \
          -each proto=uci tc="$TC" \
          -concurrency 1 -rounds $rounds -games 2 -repeat -recover \
          -ratinginterval 10 -pgnout "$pgn" 2>&1 | tee "$log"
    else
        "$CUTECHESS" \
          -engine name="Pyro-$tag" cmd="$PYRO" arg="--no-nnue" option."Threads"=$threads \
          -engine name="SF-$elo" cmd="$STOCKFISH" \
            option."UCI_LimitStrength"=true option."UCI_Elo"=$elo \
          -each proto=uci tc="$TC" \
          -concurrency 1 -rounds $rounds -games 2 -repeat -recover \
          -ratinginterval 10 -pgnout "$pgn" 2>&1 | tee "$log"
    fi

    echo "done $(date)" | tee -a "$MASTER_LOG"
}

# RUN 1 — canonical baseline (Threads=1), 200 games per opponent
run_match T1 1700 200 1
run_match T1 1900 200 1

# RUN 2 — production config (Threads=4), 100 games per opponent
run_match T4 1700 100 4
run_match T4 1900 100 4

echo "=== BASELINE 2026-06 COMPLETE $(date) ===" | tee -a "$MASTER_LOG"
