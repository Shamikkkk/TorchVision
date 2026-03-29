"""
Parse a Lichess PGN file into a CSV of (fen, eval_cp, best_move) rows.

Accepts both plain .pgn files and compressed .pgn.zst files.
When given a .zst file the decompressor streams on the fly — the full
decompressed PGN is never written to disk.

For each game:
  - Skip if either player's rating < MIN_ELO (default 2000)
  - Replay the first MAX_OPENING_MOVES moves (default 15)
  - Label each unique FEN with the classical engine at LABEL_DEPTH (default 2)
  - Write to CSV: fen, eval_cp, best_move

Usage (from backend/):
    # Plain PGN:
    python -m model_training.parse --pgn data/lichess.pgn --out data/positions.csv

    # Compressed (stream-decompressed, no disk writes):
    python -m model_training.parse --pgn data/lichess_db_standard_rated_2024-01.pgn.zst \\
        --out data/positions.csv --limit 1000
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

from .engine_classical import best_move_with_eval

MIN_ELO           = 2000
MAX_OPENING_MOVES = 15
LABEL_DEPTH       = 2       # depth-2 ≈ 1000 positions/sec in Python
TARGET_POSITIONS  = 500_000
REPORT_EVERY      = 100     # print progress every N positions


def _player_elo(game: chess.pgn.Game, color: str) -> int:
    try:
        return int(game.headers.get(color + "Elo", "0"))
    except ValueError:
        return 0


def _open_pgn_stream(pgn_path: Path) -> io.TextIOBase:
    """Return a text-mode stream for *pgn_path*, decompressing .zst on the fly."""
    if pgn_path.suffix == ".zst":
        raw = open(pgn_path, "rb")
        dctx = zstd.ZstdDecompressor()
        zst_reader = dctx.stream_reader(raw, read_size=1 << 16, closefd=True)
        return io.TextIOWrapper(zst_reader, encoding="utf-8", errors="replace")
    return open(pgn_path, encoding="utf-8", errors="replace")


def parse(
    pgn_path: Path,
    out_path: Path,
    limit: int,
    min_elo: int = MIN_ELO,
    no_elo_filter: bool = False,
    label_depth: int = LABEL_DEPTH,
    max_moves: int = MAX_OPENING_MOVES,
) -> None:
    seen_fens: set[str] = set()
    positions = 0
    games_read = 0
    t0 = time.monotonic()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with _open_pgn_stream(pgn_path) as pgn_fh, \
         open(out_path, "w", newline="", encoding="utf-8") as csv_fh:

        writer = csv.writer(csv_fh)
        writer.writerow(["fen", "eval_cp", "best_move"])

        while positions < limit:
            game = chess.pgn.read_game(pgn_fh)
            if game is None:
                break
            games_read += 1

            if (not no_elo_filter and
                    (_player_elo(game, "White") < min_elo or
                     _player_elo(game, "Black") < min_elo)):
                continue

            board = game.board()
            moves_played = 0

            for move in game.mainline_moves():
                if moves_played >= max_moves or positions >= limit:
                    break
                board.push(move)
                moves_played += 1

                if board.is_game_over():
                    break

                fen = board.fen()
                if fen in seen_fens:
                    continue
                seen_fens.add(fen)

                uci, score = best_move_with_eval(fen, depth=label_depth)
                writer.writerow([fen, f"{score:.1f}", uci])
                csv_fh.flush()
                positions += 1

                if positions % REPORT_EVERY == 0:
                    elapsed = time.monotonic() - t0
                    rate = positions / elapsed if elapsed > 0 else 0
                    remaining = (limit - positions) / rate if rate > 0 else float("inf")
                    print(
                        f"[parse] {positions:,} positions | {games_read:,} games | "
                        f"{rate:.0f} pos/s | ~{remaining / 60:.1f} min remaining",
                        flush=True,
                    )

    elapsed = time.monotonic() - t0
    print(
        f"[parse] Done. {positions:,} positions from {games_read:,} games "
        f"in {elapsed / 60:.1f} min → {out_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Label chess positions from a PGN file (.pgn or .pgn.zst)."
    )
    parser.add_argument("--pgn",          type=Path, required=True,
                        help="Input PGN file (.pgn or .pgn.zst)")
    parser.add_argument("--out",          type=Path, default=Path("data/positions.csv"),
                        help="Output CSV path")
    parser.add_argument("--limit",        type=int,  default=TARGET_POSITIONS,
                        help=f"Max positions to label (default {TARGET_POSITIONS:,})")
    parser.add_argument("--min-elo",      type=int,  default=MIN_ELO, dest="min_elo",
                        help=f"Minimum Elo for both players (default {MIN_ELO})")
    parser.add_argument("--no-elo-filter", action="store_true", dest="no_elo_filter",
                        help="Disable Elo filter entirely")
    parser.add_argument("--depth",        type=int,  default=LABEL_DEPTH,
                        help=f"Labelling engine depth (default {LABEL_DEPTH})")
    parser.add_argument("--moves",        type=int,  default=MAX_OPENING_MOVES,
                        help=f"Max opening moves per game (default {MAX_OPENING_MOVES})")
    args = parser.parse_args()

    if not args.pgn.exists():
        print(f"[parse] ERROR: file not found: {args.pgn}", file=sys.stderr)
        sys.exit(1)

    parse(
        args.pgn,
        args.out,
        args.limit,
        min_elo=args.min_elo,
        no_elo_filter=args.no_elo_filter,
        label_depth=args.depth,
        max_moves=args.moves,
    )


if __name__ == "__main__":
    main()
