"""
Re-label positions.csv with accurate Stockfish evaluations.

Reads data/positions.csv (fen, eval_cp, best_move), queries Stockfish at
depth 12 for each FEN, and writes data/positions_sf.csv with Stockfish
ground-truth evals and best moves.

Mate scores are skipped — they are not useful centipawn training targets.

Usage (from backend/):
    # Full run
    python -m model_training.stockfish_label

    # Smoke test — first 500 rows
    python -m model_training.stockfish_label --limit 500

    # Resume after interruption (appends to existing output file)
    python -m model_training.stockfish_label --append
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from stockfish import Stockfish, StockfishException

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).resolve().parent.parent
_IN      = _BACKEND / "data" / "positions.csv"
_OUT     = _BACKEND / "data" / "positions_sf.csv"

_SF_PATH = (
    r"C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)
_SF_DEPTH      = 12
_SF_THREADS    = 4
_PROGRESS_EVERY = 1_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stockfish(depth: int) -> Stockfish:
    return Stockfish(
        path=_SF_PATH,
        depth=depth,
        parameters={"Threads": _SF_THREADS},
    )


def _already_done(out_path: Path) -> set[str]:
    """Return the set of FENs already written to the output file."""
    if not out_path.exists():
        return set()
    done: set[str] = set()
    with open(out_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fen = row.get("fen", "").strip()
            if fen:
                done.add(fen)
    return done


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _run(limit: int | None, append: bool, depth: int, out_path: Path) -> None:
    # --- Validate input ---
    if not _IN.exists():
        print(f"[sf] ERROR: input file not found: {_IN}", file=sys.stderr)
        sys.exit(1)

    # --- Read all source rows ---
    with open(_IN, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit is not None:
        rows = rows[:limit]
    total = len(rows)
    print(f"[sf] Input : {_IN}  ({total:,} rows)")

    # --- Determine already-processed FENs when resuming ---
    done_fens: set[str] = set()
    if append and out_path.exists():
        done_fens = _already_done(out_path)
        print(f"[sf] Append mode — {len(done_fens):,} FENs already in output, skipping")

    # --- Open output ---
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_mode = "a" if append else "w"
    out_f = open(out_path, write_mode, newline="", encoding="utf-8")
    writer = csv.writer(out_f)
    if not append or not out_path.exists() or out_path.stat().st_size == 0:
        writer.writerow(["fen", "eval_cp", "best_move"])

    # --- Init Stockfish ---
    print(f"[sf] Stockfish depth={depth}  threads={_SF_THREADS}")
    try:
        sf = _make_stockfish(depth)
    except (StockfishException, FileNotFoundError, OSError) as exc:
        print(f"[sf] ERROR: could not start Stockfish — {exc}", file=sys.stderr)
        out_f.close()
        sys.exit(1)

    # --- Label loop ---
    written = 0
    skipped_mate = 0
    skipped_dup = 0
    t_start = time.monotonic()
    t_batch = t_start

    for i, row in enumerate(rows):
        fen = row.get("fen", "").strip()
        if not fen:
            continue

        # Skip if already present in output (append / resume mode)
        if fen in done_fens:
            skipped_dup += 1
            continue

        try:
            sf.set_fen_position(fen)
            evaluation = sf.get_evaluation()   # {"type": "cp"/"mate", "value": int}
            best_move  = sf.get_best_move()
        except StockfishException:
            # Stockfish process died; restart and retry once
            try:
                sf = _make_stockfish(depth)
                sf.set_fen_position(fen)
                evaluation = sf.get_evaluation()
                best_move  = sf.get_best_move()
            except StockfishException as exc:
                print(f"[sf] WARNING: Stockfish error at row {i} ({exc}) — skipping")
                continue

        # Skip mate scores — not useful as centipawn training targets
        if evaluation.get("type") == "mate":
            skipped_mate += 1
            continue

        eval_cp   = int(evaluation["value"])
        best_move = best_move or ""

        writer.writerow([fen, eval_cp, best_move])
        written += 1

        # Progress report every N positions
        if written % _PROGRESS_EVERY == 0:
            elapsed_batch = time.monotonic() - t_batch
            elapsed_total = time.monotonic() - t_start
            rate = _PROGRESS_EVERY / elapsed_batch if elapsed_batch > 0 else 0
            pct  = (i + 1) / total * 100
            print(
                f"[sf] {written:>7,} written"
                f"  |  {pct:5.1f}% ({i+1:,}/{total:,})"
                f"  |  {rate:,.0f} pos/s"
                f"  |  {elapsed_total/60:.1f} min elapsed"
            )
            out_f.flush()
            t_batch = time.monotonic()

    out_f.close()

    elapsed = time.monotonic() - t_start
    print(
        f"\n[sf] Done."
        f"  written={written:,}"
        f"  skipped_mate={skipped_mate:,}"
        f"  skipped_dup={skipped_dup:,}"
        f"  elapsed={elapsed/60:.1f} min"
        f"  →  {out_path}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Re-label positions.csv with Stockfish evaluations"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only the first N rows (default: all)",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to existing output file instead of overwriting (resume mode)",
    )
    parser.add_argument(
        "--depth", type=int, default=_SF_DEPTH,
        help=f"Stockfish search depth (default: {_SF_DEPTH})",
    )
    parser.add_argument(
        "--out", default=str(_OUT),
        help=f"Output CSV path (default: {_OUT})",
    )
    args = parser.parse_args()
    _run(
        limit=args.limit,
        append=args.append,
        depth=args.depth,
        out_path=Path(args.out),
    )
