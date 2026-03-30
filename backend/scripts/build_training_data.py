"""
Combine all PGN files in backend/data/ into one large NNUE training CSV.

Pipeline:
  1. Glob backend/data/*.pgn
  2. Skip files < MIN_GAMES_IN_FILE games
  3. Replay each game with python-chess; sample every SAMPLE_EVERY plies
     starting after SKIP_OPENING_MOVES
  4. Label each sampled position with Stockfish depth-8
  5. Deduplicate against existing positions (positions_sf_deep.csv + output CSV)
  6. Append to backend/data/positions_combined.csv
  7. Track completed PGN files in .processed_pgns.txt for resume

Usage (from backend/):
    python scripts/build_training_data.py
    python scripts/build_training_data.py --depth 10 --limit 600000
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import io

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BACKEND  = Path(__file__).resolve().parent.parent
_DATA_DIR = _BACKEND / "data"

EXISTING_CSV     = _DATA_DIR / "positions_sf_deep.csv"
OUTPUT_CSV       = _DATA_DIR / "positions_combined.csv"
PROCESSED_LOG    = _DATA_DIR / ".processed_pgns.txt"

MIN_GAMES_IN_FILE  = 10
MIN_MOVES_IN_GAME  = 20     # half-moves; skip very short games
SKIP_OPENING_MOVES = 5      # skip first N plies (both colours' first 2-3 moves)
SAMPLE_EVERY       = 3      # label every Nth ply
MAX_CP             = 600    # skip positions already decided (|eval| > this)
SF_DEPTH           = 8
CHECKPOINT_EVERY   = 5_000  # flush CSV every N new positions
REPORT_EVERY       = 5_000  # print progress every N new positions

_SF_ENV_KEY = "STOCKFISH_PATH"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stockfish_path() -> str:
    sf = os.environ.get(_SF_ENV_KEY)
    if sf and Path(sf).exists():
        return sf
    env_file = _BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(_SF_ENV_KEY + "="):
                sf = line.split("=", 1)[1].strip()
                if Path(sf).exists():
                    return sf
    import shutil
    sf = shutil.which("stockfish")
    if sf:
        return sf
    raise FileNotFoundError(
        "Stockfish not found. Set STOCKFISH_PATH in backend/.env or add it to PATH."
    )


def _count_games_in_file(path: Path) -> int:
    count = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("[Event "):
                count += 1
    return count


def _load_existing_fens(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    seen: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if row:
                seen.add(row[0])
    print(f"  Loaded {len(seen):,} FENs from {csv_path.name}")
    return seen


def _load_processed_log() -> set[str]:
    if not PROCESSED_LOG.exists():
        return set()
    return set(PROCESSED_LOG.read_text(encoding="utf-8").splitlines())


def _mark_processed(pgn_name: str) -> None:
    with open(PROCESSED_LOG, "a", encoding="utf-8") as f:
        f.write(pgn_name + "\n")


def _pgn_files() -> list[Path]:
    """Return all *.pgn paths in DATA_DIR, sorted by size descending (largest first)."""
    paths = sorted(_DATA_DIR.glob("*.pgn"), key=lambda p: p.stat().st_size, reverse=True)
    return paths


def _sample_fens_from_pgn(path: Path) -> list[str]:
    """
    Stream *path* game-by-game and return sampled FEN strings.
    Applies SKIP_OPENING_MOVES, SAMPLE_EVERY, and MIN_MOVES_IN_GAME filters.
    Does NOT deduplicate — caller handles that with the global seen set.
    """
    fens: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break

            board  = game.board()
            moves  = list(game.mainline_moves())
            if len(moves) < MIN_MOVES_IN_GAME:
                continue

            for ply, move in enumerate(moves):
                board.push(move)
                if board.is_game_over():
                    break
                if ply < SKIP_OPENING_MOVES:
                    continue
                if (ply - SKIP_OPENING_MOVES) % SAMPLE_EVERY == 0:
                    fens.append(board.fen())
    return fens


class _LabelStats:
    __slots__ = ("skip_seen", "skip_mate", "skip_max_cp", "sf_fail", "kept")
    def __init__(self) -> None:
        self.skip_seen  = 0
        self.skip_mate  = 0
        self.skip_max_cp = 0
        self.sf_fail    = 0
        self.kept       = 0

    def summary(self) -> str:
        return (
            f"kept={self.kept}  skip_seen={self.skip_seen}  "
            f"skip_mate={self.skip_mate}  skip_max_cp={self.skip_max_cp}  "
            f"sf_fail={self.sf_fail}"
        )


def _label_fens(
    fens: list[str],
    engine: chess.engine.SimpleEngine,
    depth: int,
    seen: set[str],
) -> tuple[list[tuple[str, int]], _LabelStats]:
    """
    Label *fens* with Stockfish at *depth*.
    Skips FENs already in *seen* and positions with |eval| > MAX_CP.
    Returns (results, stats) where results are White-positive centipawn evals.
    """
    results: list[tuple[str, int]] = []
    stats = _LabelStats()

    for fen in fens:
        if fen in seen:
            stats.skip_seen += 1
            continue
        board = chess.Board(fen)
        try:
            info = engine.analyse(board, chess.engine.Limit(depth=depth))
        except Exception as exc:
            stats.sf_fail += 1
            print(f"  [warn] SF failed ({exc.__class__.__name__}: {exc}) for {fen[:50]}")
            continue

        score = info["score"].white()
        if score.is_mate():
            stats.skip_mate += 1
            continue
        cp = score.score()
        if cp is None or abs(cp) > MAX_CP:
            stats.skip_max_cp += 1
            continue

        results.append((fen, cp))
        stats.kept += 1

    return results, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(depth: int, limit: int) -> None:
    sf_bin = _stockfish_path()
    print(f"Stockfish : {sf_bin}")
    print(f"Output    : {OUTPUT_CSV}")
    print(f"Depth     : {depth}  |  Limit: {limit:,}")
    print()

    # Build dedupe set from existing CSVs
    print("Loading existing positions for deduplication…")
    seen: set[str] = set()
    seen |= _load_existing_fens(EXISTING_CSV)
    seen |= _load_existing_fens(OUTPUT_CSV)
    existing_count = len(seen)
    print(f"  {existing_count:,} total existing positions\n")

    # PGN inventory
    all_pgns = _pgn_files()
    if not all_pgns:
        print(f"No .pgn files found in {_DATA_DIR}")
        return

    processed = _load_processed_log()
    print(f"PGN files found: {len(all_pgns)}")
    eligible: list[tuple[Path, int]] = []
    for p in all_pgns:
        games = _count_games_in_file(p)
        if games < MIN_GAMES_IN_FILE:
            print(f"  [skip] {p.name} — only {games} games")
            continue
        status = "[done] " if p.name in processed else "       "
        print(f"  {status}{p.name:40s}  {games:>6,} games")
        if p.name not in processed:
            eligible.append((p, games))
    print()

    if not eligible:
        print("All PGNs already processed. Delete .processed_pgns.txt to rerun.")
        return

    # Prepare output CSV
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_existed = OUTPUT_CSV.exists()
    new_positions = 0
    t0 = time.monotonic()

    with (
        chess.engine.SimpleEngine.popen_uci(sf_bin) as engine,
        open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as csv_fh,
    ):
        writer = csv.writer(csv_fh)
        if not file_existed:
            writer.writerow(["fen", "eval_cp"])

        for pgn_path, game_count in eligible:
            if new_positions >= limit:
                break

            print(
                f"Processing {pgn_path.name} ({game_count:,} games)…",
                flush=True,
            )
            pgn_t0   = time.monotonic()
            pgn_new  = 0

            raw_fens = _sample_fens_from_pgn(pgn_path)
            print(f"  Sampled {len(raw_fens):,} raw FENs from PGN", flush=True)

            labeled, stats = _label_fens(raw_fens, engine, depth, seen)
            print(f"  SF labelling: {stats.summary()}", flush=True)

            for fen, cp in labeled:
                if new_positions >= limit:
                    break
                seen.add(fen)
                writer.writerow([fen, cp])
                new_positions += 1
                pgn_new       += 1

                if new_positions % CHECKPOINT_EVERY == 0:
                    csv_fh.flush()

                if new_positions % REPORT_EVERY == 0:
                    elapsed = time.monotonic() - t0
                    rate    = new_positions / elapsed if elapsed > 0 else 0
                    eta_min = (limit - new_positions) / rate / 60 if rate > 0 else float("inf")
                    print(
                        f"  [progress] {new_positions:,} new positions | "
                        f"{rate:.0f} pos/s | ETA ~{eta_min:.1f} min",
                        flush=True,
                    )

            csv_fh.flush()
            elapsed_pgn = time.monotonic() - pgn_t0
            if pgn_new == 0 and raw_fens:
                print(
                    f"  → 0 new positions in {elapsed_pgn:.1f}s "
                    f"(all {len(raw_fens):,} FENs filtered — see SF labelling stats above)",
                    flush=True,
                )
            else:
                print(
                    f"  → {pgn_new:,} new positions in {elapsed_pgn:.1f}s "
                    f"(total new: {new_positions:,})",
                    flush=True,
                )
            # Mark processed even on 0 new: FENs are already covered by the
            # output CSV from a prior run; re-processing would always yield 0.
            _mark_processed(pgn_path.name)

    total = existing_count + new_positions
    print()
    print(f"Total positions: {total:,}  ({new_positions:,} new + {existing_count:,} existing)")
    print(f"Output: {OUTPUT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build combined NNUE training CSV from all PGNs in backend/data/"
    )
    parser.add_argument(
        "--depth", type=int, default=SF_DEPTH,
        help=f"Stockfish analysis depth (default {SF_DEPTH})",
    )
    parser.add_argument(
        "--limit", type=int, default=500_000,
        help="Max new positions to add (default 500,000)",
    )
    args = parser.parse_args()
    run(args.depth, args.limit)


if __name__ == "__main__":
    main()
