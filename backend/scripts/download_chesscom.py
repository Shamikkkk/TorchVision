"""
Download Chess.com games and convert them to NNUE training positions.

Fetches the last 6 months of games for a set of players, filters by time
control and game length, replays each game with python-chess, labels every
other position with Stockfish depth-8, and writes:

    backend/data/chesscom_positions.csv   (fen, eval_cp)

Resume support: positions already in the CSV are skipped on restart.
Checkpoint: CSV is flushed every 1,000 new positions.

Usage (from backend/):
    python scripts/download_chesscom.py
    python scripts/download_chesscom.py --out data/my_out.csv --depth 10
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import chess
import chess.engine
import chess.pgn
import io
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USERNAMES: list[str] = [
    "TorchVision_15",
    "hikaru",
    "magnuscarlsen",
    "firouzja2003",
    "mishanick",
    "gothamchess",
    "penguingm1",
]

MONTHS_BACK        = 6
MIN_MOVES          = 20          # plies (half-moves) — skip blitz blunders
SAMPLE_EVERY       = 2           # extract a position every N plies
MAX_WIN_PROB       = 0.80        # skip positions already decided (|eval| too large)
SF_DEPTH           = 8
CHECKPOINT_EVERY   = 1_000       # flush CSV every N positions
API_SLEEP          = 1.0         # seconds between Chess.com API calls
RETRY_COUNT        = 3
RETRY_BASE_SLEEP   = 2.0         # seconds; doubles each retry

# Centipawn threshold corresponding to ~0.80 win probability (logistic)
# P = 1 / (1 + exp(-cp/400))  →  cp = 400 * ln(0.80/0.20) ≈ 557
_MAX_CP = 557

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _BACKEND / "data" / "chesscom_positions.csv"
_SF_ENV_KEY  = "STOCKFISH_PATH"


def _stockfish_path() -> str:
    """Resolve Stockfish binary: env var → .env file → PATH."""
    # Try environment first
    sf = os.environ.get(_SF_ENV_KEY)
    if sf and Path(sf).exists():
        return sf

    # Try backend/.env
    env_file = _BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(_SF_ENV_KEY + "="):
                sf = line.split("=", 1)[1].strip()
                if Path(sf).exists():
                    return sf

    # Fall back to PATH
    import shutil
    sf = shutil.which("stockfish")
    if sf:
        return sf

    raise FileNotFoundError(
        "Stockfish not found. Set STOCKFISH_PATH in backend/.env or add it to PATH."
    )


def _months_to_fetch(n: int) -> list[tuple[int, int]]:
    """Return the last *n* (year, month) pairs, most-recent first."""
    result = []
    d = date.today().replace(day=1)
    for _ in range(n):
        result.append((d.year, d.month))
        d = (d - timedelta(days=1)).replace(day=1)
    return result


def _fetch_with_retry(url: str) -> dict | None:
    """GET *url* with retry + exponential back-off. Returns parsed JSON or None."""
    headers = {"User-Agent": "TorchChess-downloader/1.0 (github.com/torch)"}
    sleep = RETRY_BASE_SLEEP
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 404:
                return None          # player has no games that month
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == RETRY_COUNT:
                print(f"  [warn] Failed after {RETRY_COUNT} attempts: {url} — {exc}")
                return None
            print(f"  [warn] Attempt {attempt} failed ({exc}); retrying in {sleep:.0f}s…")
            time.sleep(sleep)
            sleep *= 2
    return None


def _is_classical_enough(time_class: str, time_control: str) -> bool:
    """
    Accept standard / rapid / blitz; reject bullet (< 60 s base time).
    time_control is Chess.com's "base+increment" string, e.g. "180+2".
    """
    if time_class in ("bullet", "ultraBullet"):
        return False
    if time_class in ("rapid", "standard", "daily"):
        return True
    # blitz: check base time
    if time_class == "blitz":
        try:
            base = int(time_control.split("+")[0])
            return base >= 60
        except (ValueError, IndexError):
            return True
    return True


def fetch_games(username: str, months: list[tuple[int, int]]) -> list[str]:
    """
    Return a list of PGN strings for *username* across *months*.
    Applies time-control and minimum-move filters.
    """
    all_pgns: list[str] = []
    for year, month in months:
        url = f"https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}"
        time.sleep(API_SLEEP)
        data = _fetch_with_retry(url)
        if data is None:
            continue
        games = data.get("games", [])
        for g in games:
            tc_class   = g.get("time_class", "")
            tc_control = g.get("time_control", "0")
            if not _is_classical_enough(tc_class, tc_control):
                continue
            pgn = g.get("pgn", "")
            if not pgn:
                continue
            # Quick move-count filter before full parse
            if pgn.count("...") + pgn.count(". ") < MIN_MOVES // 2:
                continue
            all_pgns.append(pgn)
    return all_pgns


def positions_from_pgn(pgn_text: str) -> Iterator[str]:
    """
    Yield FEN strings sampled every SAMPLE_EVERY plies, stopping before
    the game is decided (|eval| not checked here — done after SF labelling).
    Only games with >= MIN_MOVES half-moves are emitted.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return

    board = game.board()
    moves = list(game.mainline_moves())
    if len(moves) < MIN_MOVES:
        return

    for i, move in enumerate(moves):
        board.push(move)
        if board.is_game_over():
            break
        if i % SAMPLE_EVERY == 0:
            yield board.fen()


def label_positions(
    fens: list[str],
    engine: chess.engine.SimpleEngine,
    depth: int,
) -> list[tuple[str, int]]:
    """
    Return ``[(fen, eval_cp), …]`` for *fens*, using Stockfish at *depth*.
    Skips positions where |eval_cp| > _MAX_CP (already decided).
    eval_cp is White-positive centipawns.
    """
    results: list[tuple[str, int]] = []
    for fen in fens:
        board = chess.Board(fen)
        try:
            info = engine.analyse(board, chess.engine.Limit(depth=depth))
        except Exception as exc:
            print(f"  [warn] SF analyse failed for {fen[:30]}…: {exc}")
            continue

        score = info["score"].white()
        if score.is_mate():
            continue                  # skip forced mates — not useful for regression

        cp = score.score()
        if cp is None:
            continue
        if abs(cp) > _MAX_CP:
            continue                  # position already decided

        results.append((fen, cp))
    return results


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def _load_existing_fens(csv_path: Path) -> set[str]:
    """Return the set of FENs already in *csv_path* (for resume)."""
    if not csv_path.exists():
        return set()
    seen: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)           # skip header
        for row in reader:
            if row:
                seen.add(row[0])
    return seen


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(out_path: Path, depth: int, limit: int) -> None:
    months = _months_to_fetch(MONTHS_BACK)
    sf_bin  = _stockfish_path()

    print(f"Stockfish: {sf_bin}")
    print(f"Output:    {out_path}")
    print(f"Months:    {months[-1][0]}-{months[-1][1]:02d} → {months[0][0]}-{months[0][1]:02d}")
    print()

    # Resume: load FENs already written
    seen_fens = _load_existing_fens(out_path)
    if seen_fens:
        print(f"[resume] {len(seen_fens):,} positions already in CSV — skipping duplicates\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    file_existed = out_path.exists()

    total_written = 0

    with (
        chess.engine.SimpleEngine.popen_uci(sf_bin) as engine,
        open(out_path, "a", newline="", encoding="utf-8") as csv_fh,
    ):
        writer = csv.writer(csv_fh)
        if not file_existed:
            writer.writerow(["fen", "eval_cp"])

        for username in USERNAMES:
            if total_written >= limit:
                break

            print(f"Fetching {username} games…", flush=True)
            pgns = fetch_games(username, months)
            print(f"  {len(pgns):,} games found", flush=True)

            for game_idx, pgn_text in enumerate(pgns, 1):
                if total_written >= limit:
                    break

                if game_idx % 50 == 0 or game_idx == 1:
                    print(
                        f"  Processing game {game_idx}/{len(pgns)}  "
                        f"(total positions so far: {total_written:,})",
                        flush=True,
                    )

                raw_fens = [f for f in positions_from_pgn(pgn_text) if f not in seen_fens]
                if not raw_fens:
                    continue

                labeled = label_positions(raw_fens, engine, depth)
                for fen, cp in labeled:
                    if total_written >= limit:
                        break
                    if fen in seen_fens:
                        continue
                    seen_fens.add(fen)
                    writer.writerow([fen, cp])
                    total_written += 1

                    if total_written % CHECKPOINT_EVERY == 0:
                        csv_fh.flush()
                        print(
                            f"  [checkpoint] {total_written:,} positions written → {out_path.name}",
                            flush=True,
                        )

            print(f"  Done with {username}. Total: {total_written:,}\n", flush=True)

    print(f"\nFinished. {total_written:,} new positions → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Chess.com games → NNUE training CSV"
    )
    parser.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT,
        help=f"Output CSV (default: {_DEFAULT_OUT.relative_to(_BACKEND)})",
    )
    parser.add_argument(
        "--depth", type=int, default=SF_DEPTH,
        help=f"Stockfish analysis depth (default {SF_DEPTH})",
    )
    parser.add_argument(
        "--limit", type=int, default=200_000,
        help="Max new positions to write (default 200,000)",
    )
    args = parser.parse_args()
    run(args.out, args.depth, args.limit)


if __name__ == "__main__":
    main()
