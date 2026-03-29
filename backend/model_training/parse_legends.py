"""
Fast parser for legend PGN files (Tal, Fischer, Kasparov, etc.).

Instead of running minimax search per position, this script:
  - Evaluates each position with tal_style_eval() — a pure static eval, no search
  - Records the actual move the legend played (UCI) as best_move
  - Flushes after every row for real-time progress on disk

Result: ~500–1000 positions/second instead of ~1000/minute.

Accepts both plain .pgn and compressed .pgn.zst files.

Usage (from backend/):
    python -m model_training.parse_legends --pgn data/Tal.pgn --out data/tal_positions.csv
    python -m model_training.parse_legends --pgn data/Tal.pgn --out data/tal_positions.csv --limit 5000
    python -m model_training.parse_legends --pgn data/lichess.pgn.zst --out data/positions.csv
    python -m model_training.parse_legends --pgn data/Fischer.pgn --out data/positions.csv --append
"""

import argparse
import csv
import io
import sys
import time
from pathlib import Path

import chess
import chess.pgn
import zstandard as zstd

from app.engine.evaluate import tal_style_eval

REPORT_EVERY = 100   # print progress every N positions


def _open_pgn_stream(pgn_path: Path) -> io.TextIOBase:
    """Return a text-mode stream for *pgn_path*, decompressing .zst on the fly."""
    if pgn_path.suffix == ".zst":
        raw = open(pgn_path, "rb")
        dctx = zstd.ZstdDecompressor()
        zst_reader = dctx.stream_reader(raw, read_size=1 << 16, closefd=True)
        return io.TextIOWrapper(zst_reader, encoding="utf-8", errors="replace")
    return open(pgn_path, encoding="utf-8", errors="replace")


def _load_existing_fens(out_path: Path) -> set[str]:
    """Read the FEN column from an existing CSV and return as a set."""
    seen: set[str] = set()
    with open(out_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if row:
                seen.add(row[0])
    print(f"[parse_legends] Loaded {len(seen):,} existing FENs from {out_path}", flush=True)
    return seen


def parse_legends(
    pgn_path: Path,
    out_path: Path,
    limit: int,
    append: bool = False,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if append and out_path.exists():
        seen_fens = _load_existing_fens(out_path)
        file_mode = "a"
        write_header = False
    else:
        seen_fens = set()
        file_mode = "w"
        write_header = True

    positions = 0
    games_read = 0
    games_skipped = 0
    t0 = time.monotonic()

    with _open_pgn_stream(pgn_path) as pgn_fh, \
         open(out_path, file_mode, newline="", encoding="utf-8") as csv_fh:

        writer = csv.writer(csv_fh)
        if write_header:
            writer.writerow(["fen", "eval_cp", "best_move"])
            csv_fh.flush()

        while positions < limit:
            game = chess.pgn.read_game(pgn_fh)
            if game is None:
                break
            games_read += 1

            try:
                board = game.board()

                for move in game.mainline_moves():
                    if positions >= limit:
                        break

                    fen = board.fen()
                    if fen not in seen_fens:
                        seen_fens.add(fen)

                        score = tal_style_eval(board)
                        uci = move.uci()

                        writer.writerow([fen, f"{score:.1f}", uci])
                        csv_fh.flush()
                        positions += 1

                        if positions % REPORT_EVERY == 0:
                            elapsed = time.monotonic() - t0
                            rate = positions / elapsed if elapsed > 0 else 0
                            remaining = (limit - positions) / rate if rate > 0 else float("inf")
                            print(
                                f"[parse_legends] {positions:,} positions | {games_read:,} games | "
                                f"{rate:.0f} pos/s | ~{remaining / 60:.1f} min remaining",
                                flush=True,
                            )

                    board.push(move)

            except Exception as exc:
                games_skipped += 1
                print(
                    f"[parse_legends] Skipping game {games_read} ({type(exc).__name__}: {exc})",
                    flush=True,
                )

    elapsed = time.monotonic() - t0
    rate = positions / elapsed if elapsed > 0 else 0
    print(
        f"[parse_legends] Done. {positions:,} positions from {games_read:,} games "
        f"({games_skipped:,} skipped) in {elapsed:.1f}s ({rate:.0f} pos/s) → {out_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fast legend-game parser: static eval + actual move played."
    )
    parser.add_argument("--pgn",   type=Path, required=True,
                        help="Input PGN file (.pgn or .pgn.zst)")
    parser.add_argument("--out",   type=Path, default=Path("data/positions.csv"),
                        help="Output CSV path (default: data/positions.csv)")
    parser.add_argument("--limit", type=int,  default=10_000_000,
                        help="Max positions to write (default: no limit)")
    parser.add_argument("--append", action="store_true",
                        help="Append to existing CSV; skip duplicate FENs")
    args = parser.parse_args()

    if not args.pgn.exists():
        print(f"[parse_legends] ERROR: file not found: {args.pgn}", file=sys.stderr)
        sys.exit(1)

    parse_legends(args.pgn, args.out, args.limit, append=args.append)


if __name__ == "__main__":
    main()
