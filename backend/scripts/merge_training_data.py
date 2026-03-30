"""
Merge all training CSVs into one deduplicated, shuffled dataset.

Priority order (highest label quality first):
  1. positions_sf_deep.csv    — 497,998 positions, Stockfish depth-12
  2. positions_combined.csv   — positions from GM PGNs, Stockfish depth-8

When the same FEN appears in multiple sources the first-seen version is
kept, so higher-quality labels win.

Output: backend/data/positions_final.csv  (fen, eval_cp)

Usage (from backend/):
    python scripts/merge_training_data.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

_BACKEND  = Path(__file__).resolve().parent.parent
_DATA_DIR = _BACKEND / "data"

SOURCES = [
    _DATA_DIR / "positions_sf_deep.csv",    # depth-12, highest quality → load first
    _DATA_DIR / "positions_combined.csv",   # depth-8, load second (duplicates skipped)
]
OUTPUT = _DATA_DIR / "positions_final.csv"
SEED   = 42


def load_csv(path: Path, seen: set[str]) -> list[tuple[str, str]]:
    """
    Read *path* and return rows whose FEN is not already in *seen*.
    Adds each accepted FEN to *seen* in-place.
    Returns list of (fen, eval_cp) string pairs.
    """
    if not path.exists():
        print(f"  [skip] {path.name} not found")
        return []

    rows: list[tuple[str, str]] = []
    skipped = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)          # skip header
        for row in reader:
            if len(row) < 2:
                continue
            fen = row[0]
            if fen in seen:
                skipped += 1
                continue
            seen.add(fen)
            rows.append((fen, row[1]))

    print(f"  {path.name}: {len(rows):>9,} accepted  {skipped:>7,} duplicates skipped")
    return rows


def run() -> None:
    seen: set[str]             = set()
    per_source: list[int]      = []
    all_rows: list[tuple[str, str]] = []

    print("Loading sources (highest quality first)…")
    for source in SOURCES:
        rows = load_csv(source, seen)
        per_source.append(len(rows))
        all_rows.extend(rows)

    if not all_rows:
        print("No data loaded — check that source CSVs exist in backend/data/")
        return

    print(f"\nShuffling {len(all_rows):,} positions…")
    random.seed(SEED)
    random.shuffle(all_rows)

    print(f"Writing {OUTPUT.name}…")
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fen", "eval_cp"])
        writer.writerows(all_rows)

    # Summary
    source_counts = "  +  ".join(
        f"{n:,} from {SOURCES[i].name}" for i, n in enumerate(per_source)
    )
    print(f"\nFinal dataset: {len(all_rows):,} positions  ({source_counts})")
    print(f"Output: {OUTPUT}")
    print()
    print("Next step — retrain NNUE:")
    print(f"  python -m model_training.train --csv {OUTPUT.relative_to(_BACKEND)}")


if __name__ == "__main__":
    run()
