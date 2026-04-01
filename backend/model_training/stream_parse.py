"""
Stream-parse a Lichess PGN database month directly into a labeled CSV.

Evals are extracted from the [%eval] comments that Lichess embeds in every
move annotation — no local Stockfish calls needed.  Positions without an
eval comment (or with a mate score) are skipped.

Lichess PGN eval format:
    1. e4 { [%eval 0.17] [%clk 0:05:00] } e5 { [%eval 0.19] }

The full pipeline runs without touching disk for PGN data:

    HTTP stream (zst) → zstd decompressor → TextIOWrapper
        → chess.pgn.read_game() → [%eval] extraction → CSV row

Throughput: ~1000+ pos/s (pure text parsing, no engine).

Auto-resume: on connection drop the script reconnects with an HTTP Range
header to continue from the last received byte.  If the server doesn't
honour Range (or the zstd frame boundary doesn't align), it falls back to
a full restart with a fast-forward skip past already-processed games.

Usage (from backend/):
    python -m model_training.stream_parse \\
        --year 2024 --month 1 \\
        --out data/positions.csv \\
        --limit 500000

    # Resume a previous run without losing existing rows:
    python -m model_training.stream_parse \\
        --year 2024 --month 1 \\
        --out data/positions.csv \\
        --limit 500000 --append

Options:
    --year          Year of the Lichess database dump (e.g. 2024)
    --month         Month 1–12
    --out           Output CSV path  (default: data/positions.csv)
    --limit         Max positions to write  (default: 500,000)
    --min-elo       Minimum Elo for both players  (default: 2000)
    --no-elo-filter Disable Elo filter entirely (useful for small datasets)
    --moves         Max moves per game to extract  (default: 15)
    --append        Append to existing CSV instead of overwriting
"""

import argparse
import csv
import http.client
import io
import re
import sys
import time
from pathlib import Path

import chess
import chess.pgn
import requests
import zstandard as zstd

_LICHESS_IP   = "141.95.66.62"
_LICHESS_HOST = "database.lichess.org"
_BASE_PATH    = "/standard"

_GAME_REPORT_EVERY = 100    # verbose progress line every N games
_SKIP_REPORT_EVERY = 1_000  # low-Elo skip notice every N skips
_MAX_RETRIES       = 10
_RETRY_DELAY_S     = 5

# Matches [%eval 0.17], [%eval -1.35], but NOT [%eval #3] (mate scores).
# Lichess always uses this exact format inside move comments.
_EVAL_RE = re.compile(r'\[%eval\s+([+-]?\d+\.?\d*)\]')


def _parse_eval(comment: str) -> float | None:
    """
    Extract a centipawn evaluation from a Lichess PGN move comment.

    Returns centipawns (White-positive) or None if no numeric eval is present.
    Mate scores ([%eval #N]) are intentionally skipped — they sit far outside
    the normal cp range and would distort MSE training.

    Examples:
        "[%eval 0.17] [%clk 0:05:00]"  →  17.0
        "[%eval -1.35]"                 → -135.0
        "[%eval #3]"                    →  None  (skipped)
        ""                              →  None  (no annotation)
    """
    m = _EVAL_RE.search(comment)
    if m is None:
        return None
    return float(m.group(1)) * 100.0   # pawns → centipawns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pgn_url(year: int, month: int) -> str:
    filename = f"lichess_db_standard_rated_{year}-{month:02d}.pgn.zst"
    return f"http://{_LICHESS_IP}{_BASE_PATH}/{filename}"


def _player_elo(game: chess.pgn.Game, color: str) -> int:
    try:
        return int(game.headers.get(color + "Elo", "0"))
    except ValueError:
        return 0


class _ByteCounter:
    """Wraps a response raw stream and counts every byte read by zstd."""

    def __init__(self, raw: object) -> None:
        self._raw  = raw
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self.count += len(data)
        return data


def _load_existing_fens(csv_path: Path) -> tuple[set[str], int]:
    """Return (seen_fens, row_count) from an existing CSV (skips header)."""
    fens: set[str] = set()
    with open(csv_path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # skip header
        for row in reader:
            if row:
                fens.add(row[0])
    return fens, len(fens)


def _fast_forward(text_stream: io.TextIOWrapper, n_games: int) -> int:
    """Skip *n_games* games without any engine evaluation.

    Returns the number of games actually skipped (may be less if stream ends).
    """
    skipped = 0
    t0 = time.monotonic()
    while skipped < n_games:
        try:
            g = chess.pgn.read_game(text_stream)
        except Exception:  # noqa: BLE001
            continue
        if g is None:
            break
        skipped += 1
        if skipped % 10_000 == 0:
            print(
                f"[stream] Fast-forwarding… {skipped:,}/{n_games:,}"
                f"  ({time.monotonic() - t0:.0f}s)",
                flush=True,
            )
    print(f"[stream] Fast-forward done: skipped {skipped:,} games", flush=True)
    return skipped


def _report(
    games_read: int,
    games_used: int,
    positions: int,
    limit: int,
    t0: float,
) -> None:
    elapsed = time.monotonic() - t0
    rate    = positions / elapsed if elapsed > 0 else 0
    eta     = (limit - positions) / rate / 60 if rate > 0 else float("inf")
    suffix  = f" | {rate:.0f} pos/s | ~{eta:.1f} min left" if rate > 0 else ""
    print(
        f"[stream] Games read: {games_read:,} | qualified: {games_used:,}"
        f" | positions: {positions:,}{suffix}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def stream_parse(
    year: int,
    month: int,
    out_path: Path,
    limit: int,
    min_elo: int,
    no_elo_filter: bool,
    max_moves: int,
    append: bool,
) -> None:
    url      = _pgn_url(year, month)
    elo_desc = "disabled" if no_elo_filter else f">= {min_elo}"
    print(f"[stream] Connecting → {url}")
    print(f"[stream] Output     → {out_path}")
    print(
        f"[stream] Limit: {limit:,} positions"
        f"  |  Elo filter: {elo_desc}"
        f"  |  eval: from [%eval] comments (no local engine)"
        f"  |  append: {append}"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --append: reload existing FENs so we never write duplicates.
    seen_fens:  set[str] = set()
    positions   = 0
    csv_mode    = "w"
    write_header = True

    if append and out_path.exists() and out_path.stat().st_size > 0:
        print(f"[stream] --append: scanning existing CSV…", flush=True)
        seen_fens, positions = _load_existing_fens(out_path)
        print(f"[stream] --append: {positions:,} existing positions loaded", flush=True)
        csv_mode     = "a"
        write_header = False

    dctx           = zstd.ZstdDecompressor()
    games_read     = 0   # unique games processed (not counting fast-forward)
    games_used     = 0
    elo_skips      = 0
    bytes_received = 0   # compressed bytes confirmed received across all attempts
    attempt        = 0
    t0             = time.monotonic()

    with open(out_path, csv_mode, newline="", encoding="utf-8") as csv_fh:
        writer = csv.writer(csv_fh)
        if write_header:
            writer.writerow(["fen", "eval_cp"])

        while positions < limit:
            if attempt > _MAX_RETRIES:
                print(
                    f"[stream] ERROR: max reconnect attempts ({_MAX_RETRIES}) exceeded.",
                    flush=True,
                )
                break

            # Build request headers — add Range if we have a byte offset to resume from.
            req_headers: dict[str, str] = {"Host": _LICHESS_HOST}
            if bytes_received > 0:
                req_headers["Range"] = f"bytes={bytes_received}-"
                print(
                    f"[stream] Connection dropped, resuming from"
                    f" {bytes_received / (1 << 20):.1f} MB"
                    f" (attempt {attempt}/{_MAX_RETRIES})…",
                    flush=True,
                )
                time.sleep(_RETRY_DELAY_S)

            counter = _ByteCounter(None)  # initialised properly inside the try block

            try:
                with requests.get(
                    url, stream=True, timeout=60, headers=req_headers
                ) as resp:
                    # 206 = Range honoured; 200 = server ignored Range → full restart.
                    need_fastforward = 0
                    if resp.status_code == 200 and bytes_received > 0:
                        print(
                            f"[stream] Server returned 200 (Range not supported);"
                            f" will fast-forward past {games_read:,} games…",
                            flush=True,
                        )
                        need_fastforward = games_read
                        bytes_received   = 0

                    resp.raise_for_status()

                    counter = _ByteCounter(resp.raw)

                    try:
                        with dctx.stream_reader(counter, read_size=1 << 16) as zst_reader:
                            text_stream = io.TextIOWrapper(
                                zst_reader, encoding="utf-8", errors="replace"
                            )

                            if attempt == 0:
                                print(
                                    "[stream] Connected! First bytes received,"
                                    " starting parse…",
                                    flush=True,
                                )
                            elif need_fastforward == 0:
                                print(
                                    f"[stream] Resumed at"
                                    f" {bytes_received / (1 << 20):.1f} MB",
                                    flush=True,
                                )

                            # Skip already-processed games on a full restart.
                            if need_fastforward > 0:
                                _fast_forward(text_stream, need_fastforward)

                            # ── Main parse loop ──────────────────────────────────
                            while positions < limit:
                                try:
                                    game = chess.pgn.read_game(text_stream)
                                except Exception as exc:  # noqa: BLE001
                                    print(
                                        f"[stream] Parse error (skipping): {exc}",
                                        flush=True,
                                    )
                                    continue

                                if game is None:
                                    print(
                                        "[stream] End of stream reached.",
                                        flush=True,
                                    )
                                    positions = limit  # exit outer while cleanly
                                    break

                                games_read += 1

                                # Elo filter
                                if (not no_elo_filter and
                                        (_player_elo(game, "White") < min_elo or
                                         _player_elo(game, "Black") < min_elo)):
                                    elo_skips += 1
                                    if elo_skips % _SKIP_REPORT_EVERY == 0:
                                        print(
                                            f"[stream] Skipped {elo_skips:,}"
                                            f" low-Elo games…",
                                            flush=True,
                                        )
                                    if games_read % _GAME_REPORT_EVERY == 0:
                                        _report(games_read, games_used, positions, limit, t0)
                                    continue

                                games_used += 1
                                board        = game.board()
                                moves_played = 0

                                # game.mainline() yields GameNode objects; each
                                # node carries the move (.move) and the comment
                                # that Lichess places after it (.comment), which
                                # contains [%eval X.XX] for annotated games.
                                for node in game.mainline():
                                    if moves_played >= max_moves or positions >= limit:
                                        break
                                    board.push(node.move)
                                    moves_played += 1

                                    if board.is_game_over():
                                        break

                                    eval_cp = _parse_eval(node.comment)
                                    if eval_cp is None:
                                        continue  # no [%eval] in this comment

                                    fen = board.fen()
                                    if fen in seen_fens:
                                        continue
                                    seen_fens.add(fen)

                                    writer.writerow([fen, f"{eval_cp:.1f}"])
                                    positions += 1

                                if games_read % _GAME_REPORT_EVERY == 0:
                                    _report(games_read, games_used, positions, limit, t0)

                            # Clean exit from the inner loop — no error occurred.
                            attempt = _MAX_RETRIES + 1  # break outer while
                            break

                    except zstd.ZstdError as exc:
                        # Range reconnect landed mid-zstd-frame; fall back to
                        # full restart with fast-forward.
                        print(
                            f"[stream] Decompression error after Range resume: {exc}",
                            flush=True,
                        )
                        print(
                            f"[stream] Falling back to byte-0 restart;"
                            f" will fast-forward {games_read:,} games…",
                            flush=True,
                        )
                        bytes_received = 0
                        attempt += 1

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ReadTimeout,
                http.client.IncompleteRead,
                ConnectionError,
                OSError,
            ) as exc:
                bytes_received += counter.count
                attempt        += 1
                print(
                    f"[stream] Network error (attempt {attempt}/{_MAX_RETRIES}):"
                    f" {exc}",
                    flush=True,
                )

    elapsed = time.monotonic() - t0
    # Correct positions count if we exited via end-of-stream sentinel
    real_positions = len(seen_fens) - (len(seen_fens) - positions if append else 0)
    print(
        f"\n[stream] Done."
        f"  {positions:,} positions written"
        f"  |  {games_used:,}/{games_read:,} games used"
        f"  |  {elo_skips:,} low-Elo skipped"
        f"  |  {elapsed / 60:.1f} min"
        f"  →  {out_path}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream a Lichess PGN month → labeled CSV (no PGN written to disk)."
    )
    parser.add_argument("--year",          type=int,  required=True, help="e.g. 2024")
    parser.add_argument("--month",         type=int,  required=True, help="1–12")
    parser.add_argument("--out",           type=Path, default=Path("data/positions.csv"))
    parser.add_argument("--limit",         type=int,  default=500_000,
                        help="Max positions to write (default 500,000)")
    parser.add_argument("--min-elo",       type=int,  default=2000, dest="min_elo",
                        help="Minimum Elo for both players (default 2000)")
    parser.add_argument("--no-elo-filter", action="store_true", dest="no_elo_filter",
                        help="Disable Elo filter entirely (useful for small datasets)")
    parser.add_argument("--moves",         type=int,  default=15,
                        help="Max opening moves per game (default 15)")
    parser.add_argument("--append",        action="store_true",
                        help="Append to existing CSV instead of overwriting")
    args = parser.parse_args()

    stream_parse(
        year=args.year,
        month=args.month,
        out_path=args.out,
        limit=args.limit,
        min_elo=args.min_elo,
        no_elo_filter=args.no_elo_filter,
        max_moves=args.moves,
        append=args.append,
    )


if __name__ == "__main__":
    main()
