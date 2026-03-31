"""
Self-play data generator for Phase B NNUE training.

Pyro plays itself (both sides use the same engine) at 0.1 s/move.
Every position after the first 5 full moves (10 half-moves) is saved
with the final game result as the training label.

Output CSV format:
    fen,result
    result: 1.0 = White won, 0.5 = draw, 0.0 = Black won

Run from backend/:
    python scripts/generate_selfplay.py --games 500
    python scripts/generate_selfplay.py --games 500 --output data/selfplay_positions.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import chess

# Add backend/ to sys.path so that `app` and `model_training` are importable.
# When run as `python scripts/generate_selfplay.py`, Python puts backend/scripts/
# on sys.path, not backend/ itself.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Patch _TIME_LIMIT *before* any engine code runs.
# search.best_move() computes `deadline = start + _TIME_LIMIT` on every call,
# so patching the module attribute here takes effect for all subsequent calls.
from app.engine import search as _search_module  # noqa: E402
_search_module._TIME_LIMIT = 0.1

from app.engine.model import PyroEngine  # noqa: E402

_MAX_HALF_MOVES  = 150   # 75 full moves; declare draw if exceeded
_SKIP_HALF_MOVES = 10    # skip first 5 full moves — pure opening, less informative


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_existing(path: Path) -> int:
    """Return the number of data rows already in the CSV (header not counted)."""
    if not path.exists():
        return 0
    with path.open() as f:
        return max(0, sum(1 for line in f if line.strip()) - 1)


def _result_label(result: float) -> str:
    if result == 1.0:
        return "White wins"
    if result == 0.0:
        return "Black wins"
    return "Draw"


def _eta_str(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------

def play_game(engine: PyroEngine) -> tuple[list[str], float]:
    """
    Play one self-play game; both sides use the same engine.

    Positions are recorded *before* each move is played so the FEN represents
    the position the network will be asked to evaluate.  The opening
    (first _SKIP_HALF_MOVES half-moves) is excluded — it is dominated by book
    moves and contains little positional signal.

    Returns:
        fens   — list of FEN strings to save
        result — 1.0 White won, 0.5 draw, 0.0 Black won
    """
    board = chess.Board()
    fens: list[str] = []

    for half_move in range(_MAX_HALF_MOVES):
        if board.is_game_over():
            break

        fen = board.fen()

        # Record position (skip opening)
        if half_move >= _SKIP_HALF_MOVES:
            fens.append(fen)

        uci = engine.best_move(fen)
        if not uci:
            break  # no legal moves (game_over should have caught this)

        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            break  # engine returned an illegal move — abort and discard game

        board.push(move)

    # Determine result from White's perspective
    if board.is_checkmate():
        # The side to move has been mated — they lost
        result = 0.0 if board.turn == chess.WHITE else 1.0
    else:
        # Stalemate, repetition, 50-move rule, insufficient material, or move cap
        result = 0.5

    return fens, result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Pyro self-play positions for NNUE training."
    )
    parser.add_argument(
        "--games", type=int, default=500,
        help="Number of games to play (default: 500)",
    )
    parser.add_argument(
        "--output", default="data/selfplay_positions.csv",
        help="Output CSV path relative to backend/ (default: data/selfplay_positions.csv)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support: count rows already in the file
    existing_positions = _count_existing(output_path)
    is_new_file = not output_path.exists()

    if existing_positions:
        print(f"Resuming — {existing_positions:,} positions already in {output_path}")
    else:
        print(f"Starting fresh — output: {output_path}")

    # Open for append; write header only when creating a new file
    csv_file = output_path.open("a", newline="")
    writer = csv.writer(csv_file)
    if is_new_file:
        writer.writerow(["fen", "result"])

    # Initialise engine (Stockfish path is irrelevant for self-play)
    print("Initialising Pyro engine…")
    engine = PyroEngine(stockfish_path="")
    print(f"Engine ready.  Playing {args.games} games at 0.1 s/move.\n")

    total_positions = existing_positions
    game_times: list[float] = []
    results = {"White wins": 0, "Draw": 0, "Black wins": 0}

    for game_num in range(1, args.games + 1):
        t0 = time.monotonic()
        fens, result = play_game(engine)
        elapsed = time.monotonic() - t0
        game_times.append(elapsed)

        for fen in fens:
            writer.writerow([fen, result])
        csv_file.flush()

        total_positions += len(fens)
        label = _result_label(result)
        results[label] += 1

        avg_time = sum(game_times) / len(game_times)
        eta = _eta_str(avg_time * (args.games - game_num))

        print(
            f"Game {game_num}/{args.games}: {label}"
            f" — positions this game: {len(fens)}, total: {total_positions:,}"
            f" | avg {avg_time:.1f}s/game, ETA {eta}"
        )

    csv_file.close()

    print(f"\n{'─' * 60}")
    print(f"Done.  {total_positions:,} positions saved to {output_path}")
    print(f"Results: White wins {results['White wins']} | "
          f"Draws {results['Draw']} | "
          f"Black wins {results['Black wins']}")
    print(f"Average game length: {sum(game_times)/len(game_times):.1f}s")


if __name__ == "__main__":
    main()
