"""Check 4: classify 100 sampled positions as quiet vs tactical
using Stockfish 18 best-move queries.

Tactical = in check OR best move is a capture.
Quiet    = otherwise.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import chess


SF_PATH = r"C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"


def stockfish_bestmove(proc, fen: str, depth: int = 12) -> str | None:
    proc.stdin.write(f"position fen {fen}\n")
    proc.stdin.write(f"go depth {depth}\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if line.startswith("bestmove"):
            parts = line.split()
            if len(parts) >= 2 and parts[1] != "(none)":
                return parts[1]
            return None


def classify(fen: str, bestmove_uci: str | None) -> tuple[str, str]:
    """Returns (category, reason). category in {'quiet', 'tactical', 'unknown'}."""
    board = chess.Board(fen)
    if board.is_check():
        return "tactical", "in_check"
    if bestmove_uci is None:
        return "unknown", "no_bestmove"
    try:
        mv = chess.Move.from_uci(bestmove_uci)
    except ValueError:
        return "unknown", "bad_uci"
    if mv not in board.legal_moves:
        return "unknown", "illegal"
    if board.is_capture(mv):
        return "tactical", "best_is_capture"
    return "quiet", "ok"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input",  default="C:/torch_data/diag_sample100.txt")
    p.add_argument("--depth",  type=int, default=12)
    args = p.parse_args()

    sample_path = Path(args.input)
    if not sample_path.exists():
        sys.exit(f"sample not found: {sample_path}")

    lines = [l.strip() for l in sample_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"Sample: {len(lines)} positions; SF18 depth {args.depth}")

    t0 = time.time()
    proc = subprocess.Popen(
        [SF_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    proc.stdin.write("uci\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if "uciok" in line:
            break
    proc.stdin.write("isready\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if "readyok" in line:
            break

    quiet = 0
    tactical = 0
    unknown = 0
    in_check = 0
    cap_best = 0

    details = []
    for i, line in enumerate(lines, 1):
        fen = line.split("|")[0].strip()
        try:
            bm = stockfish_bestmove(proc, fen, depth=args.depth)
        except Exception as e:
            bm = None
        cat, reason = classify(fen, bm)
        if cat == "quiet":
            quiet += 1
        elif cat == "tactical":
            tactical += 1
            if reason == "in_check":
                in_check += 1
            elif reason == "best_is_capture":
                cap_best += 1
        else:
            unknown += 1
        details.append((cat, reason, bm or "-", fen))
        if i % 20 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(lines)}  ({el:.1f}s)", flush=True)

    proc.stdin.write("quit\n")
    proc.stdin.flush()
    proc.wait(timeout=5)

    elapsed = time.time() - t0
    n = len(lines)
    print()
    print(f"=== CHECK 4 — Quiet vs Tactical (n={n}, SF18 depth={args.depth}, elapsed {elapsed:.0f}s) ===")
    print(f"  Quiet     : {quiet:>4}  ({100*quiet/n:.1f}%)")
    print(f"  Tactical  : {tactical:>4}  ({100*tactical/n:.1f}%)")
    print(f"    in check          : {in_check}")
    print(f"    best is capture   : {cap_best}")
    print(f"  Unknown   : {unknown:>4}  ({100*unknown/n:.1f}%)")

    # Dump details
    out = sample_path.parent / "diag_check4_details.txt"
    with open(out, "w", encoding="utf-8") as f:
        for cat, reason, bm, fen in details:
            f.write(f"{cat}\t{reason}\t{bm}\t{fen}\n")
    print(f"\nDetails: {out}")


if __name__ == "__main__":
    main()
