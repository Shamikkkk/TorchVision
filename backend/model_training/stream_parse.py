"""
Stream-parse a Lichess PGN database month directly into a labeled CSV.

The full pipeline runs without touching disk for PGN data:

    HTTP stream (zst) → zstd decompressor → TextIOWrapper
        → chess.pgn.read_game() → classical engine label → CSV row

Usage (from backend/):
    python -m model_training.stream_parse \\
        --year 2024 --month 1 \\
        --out data/positions.csv \\
        --limit 500000

Options:
    --year     Year of the Lichess database dump (e.g. 2024)
    --month    Month 1–12
    --out      Output CSV path  (default: data/positions.csv)
    --limit    Max positions to write  (default: 500,000)
    --min-elo  Minimum Elo for both players  (default: 2000)
    --depth    Labelling engine depth  (default: 2, ~1000 pos/s)
    --moves    Max opening moves per game  (default: 15)
"""

import argparse
import csv
import io
import sys
import time
from pathlib import Path

import chess
import chess.pgn
import requests
import zstandard as zstd

# Add backend/ to sys.path so `app` and `model_training` are both importable.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from model_training.engine_classical import best_move_with_eval  # noqa: E402

# Lichess database server — connect by IP and pass Host header so that
# DNS resolution is skipped (faster, works even without DNS).
_LICHESS_IP   = "141.95.66.62"
_LICHESS_HOST = "database.lichess.org"
_BASE_PATH    = "/standard"

REPORT_EVERY = 1_000   # print progress every N games processed


def _pgn_url(year: int, month: int) -> str:
    filename = f"lichess_db_standard_rated_{year}-{month:02d}.pgn.zst"
    return f"http://{_LICHESS_IP}{_BASE_PATH}/{filename}"


def _player_elo(game: chess.pgn.Game, color: str) -> int:
    try:
        return int(game.headers.get(color + "Elo", "0"))
    except ValueError:
        return 0


def stream_parse(
    year: int,
    month: int,
    out_path: Path,
    limit: int,
    min_elo: int,
    label_depth: int,
    max_moves: int,
) -> None:
    url = _pgn_url(year, month)
    print(f"[stream] Connecting → {url}")
    print(f"[stream] Output     → {out_path}")
    print(f"[stream] Limit      : {limit:,} positions  |  min Elo: {min_elo}  |  depth: {label_depth}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    dctx        = zstd.ZstdDecompressor()
    positions   = 0
    games_read  = 0
    games_used  = 0
    seen_fens: set[str] = set()
    t0 = time.monotonic()

    with requests.get(
        url,
        stream=True,
        timeout=60,
        headers={"Host": _LICHESS_HOST},
    ) as resp:
        resp.raise_for_status()

        with open(out_path, "w", newline="", encoding="utf-8") as csv_fh:
            writer = csv.writer(csv_fh)
            writer.writerow(["fen", "eval_cp", "best_move"])

            # Binary HTTP stream → zstd decompressor → UTF-8 text
            with dctx.stream_reader(resp.raw, read_size=1 << 16) as zst_reader:
                text_stream = io.TextIOWrapper(
                    zst_reader, encoding="utf-8", errors="replace"
                )

                while positions < limit:
                    try:
                        game = chess.pgn.read_game(text_stream)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[stream] Parse error (skipping game): {exc}", flush=True)
                        continue

                    if game is None:
                        print("[stream] End of stream reached.", flush=True)
                        break

                    games_read += 1

                    # Quality filter
                    if (_player_elo(game, "White") < min_elo or
                            _player_elo(game, "Black") < min_elo):
                        if games_read % REPORT_EVERY == 0:
                            _report(games_read, games_used, positions, limit, t0)
                        continue

                    games_used += 1
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
                        positions += 1

                    if games_read % REPORT_EVERY == 0:
                        _report(games_read, games_used, positions, limit, t0)

    elapsed = time.monotonic() - t0
    print(
        f"\n[stream] Done."
        f"  {positions:,} positions"
        f"  |  {games_used:,}/{games_read:,} games used"
        f"  |  {elapsed / 60:.1f} min"
        f"  →  {out_path}"
    )


def _report(games_read: int, games_used: int, positions: int, limit: int, t0: float) -> None:
    elapsed = time.monotonic() - t0
    rate    = positions / elapsed if elapsed > 0 else 0
    eta_min = (limit - positions) / rate / 60 if rate > 0 else float("inf")
    print(
        f"[stream] {games_read:>7,} games  |  {positions:>8,} positions  |  "
        f"{rate:>6.0f} pos/s  |  ~{eta_min:.1f} min left",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream a Lichess PGN month → labeled CSV (no PGN written to disk)."
    )
    parser.add_argument("--year",    type=int, required=True, help="e.g. 2024")
    parser.add_argument("--month",   type=int, required=True, help="1–12")
    parser.add_argument("--out",     type=Path, default=Path("data/positions.csv"))
    parser.add_argument("--limit",   type=int,  default=500_000,
                        help="Max positions to write (default 500,000)")
    parser.add_argument("--min-elo", type=int,  default=2000, dest="min_elo",
                        help="Minimum Elo for both players (default 2000)")
    parser.add_argument("--depth",   type=int,  default=2,
                        help="Labelling engine depth (default 2, ~1000 pos/s)")
    parser.add_argument("--moves",   type=int,  default=15,
                        help="Max opening moves per game (default 15)")
    args = parser.parse_args()

    stream_parse(
        year=args.year,
        month=args.month,
        out_path=args.out,
        limit=args.limit,
        min_elo=args.min_elo,
        label_depth=args.depth,
        max_moves=args.moves,
    )


if __name__ == "__main__":
    main()
