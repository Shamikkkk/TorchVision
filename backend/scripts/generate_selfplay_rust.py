"""Generate self-play training data using the Rust Pyro engine.

Output format (one line per quiet position):
    <FEN> | <eval_cp_stm> | <result_white>

    eval_cp_stm  = centipawns from side-to-move perspective
    result_white = 1.0 (white wins) / 0.5 (draw) / 0.0 (black wins)

Quiet position filter (all must be true to record):
    - Best move is not a capture
    - Side to move is not in check
    - |eval_cp| <= 3000

Usage:
    python -m scripts.generate_selfplay_rust --depth 8 --target 100_000_000
    python -m scripts.generate_selfplay_rust --depth 8 --target 100_000_000 --resume
    python -m scripts.generate_selfplay_rust --nodes 5000 --target 5_000_000  # fast/shallow
"""

import argparse
import os
import random
import subprocess
import sys
import time

import chess


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "engine", "target", "release", "pyro.exe")
)
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "..", "data", "selfplay_rust.plain")

MAX_GAME_PLIES = 400
SKIP_PLIES = 8
EVAL_CLIP = 3000

OPENING_PAIRS = [
    ("e2e4", ["e7e5", "c7c5", "e7e6", "c7c6", "d7d5", "g8f6", "d7d6", "g7g6"]),
    ("d2d4", ["d7d5", "g8f6", "e7e6", "c7c5", "f7f5", "g7g6", "d7d6"]),
    ("c2c4", ["e7e5", "g8f6", "c7c5", "e7e6", "g7g6"]),
    ("g1f3", ["d7d5", "g8f6", "c7c5", "g7g6"]),
    ("b1c3", ["d7d5", "g8f6", "e7e5"]),
    ("g2g3", ["d7d5", "g8f6", "e7e5", "g7g6"]),
    ("f2f4", ["d7d5", "e7e5", "g8f6"]),
    ("b2b3", ["e7e5", "d7d5", "g8f6"]),
]

_RESULT_FLOAT = {1: 1.0, 0: 0.5, -1: 0.0}


class UCIEngine:
    """Manages a UCI engine subprocess."""

    def __init__(self, path: str, no_nnue: bool = False):
        cmd = [path]
        if no_nnue:
            cmd.append("--no-nnue")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send("isready")
        self._wait_for("readyok")

    def _send(self, cmd: str):
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _wait_for(self, token: str) -> list[str]:
        lines = []
        while True:
            line = self.proc.stdout.readline().strip()
            if not line and self.proc.poll() is not None:
                raise RuntimeError("Engine process died")
            lines.append(line)
            if line.startswith(token):
                return lines

    def new_game(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")

    def go(self, moves: list[str], *, depth: int | None, nodes: int) -> tuple[str, int]:
        """Search the position and return (bestmove, eval_cp_stm)."""
        if moves:
            self._send(f"position startpos moves {' '.join(moves)}")
        else:
            self._send("position startpos")

        if depth is not None:
            self._send(f"go depth {depth}")
        else:
            self._send(f"go nodes {nodes}")

        lines = self._wait_for("bestmove")

        # Use the last reported 'score cp' (most accurate after iterative deepening)
        eval_cp = 0
        for line in lines:
            if "score cp" in line:
                parts = line.split()
                for i, tok in enumerate(parts):
                    if tok == "cp" and i + 1 < len(parts):
                        try:
                            eval_cp = int(parts[i + 1])
                        except ValueError:
                            pass

        bestmove = "(none)"
        for line in lines:
            if line.startswith("bestmove"):
                bestmove = line.split()[1]
                break

        return bestmove, eval_cp

    def quit(self):
        try:
            self._send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def random_opening() -> list[str]:
    white_move, black_responses = random.choice(OPENING_PAIRS)
    return [white_move, random.choice(black_responses)]


def play_game(
    engine: UCIEngine,
    depth: int | None,
    nodes: int,
) -> list[tuple[str, int, float]]:
    """Play one self-play game.

    Returns list of (fen, eval_cp_stm, result_white) for quiet positions only.
    """
    engine.new_game()

    board = chess.Board()
    moves: list[str] = []
    for uci_str in random_opening():
        move = chess.Move.from_uci(uci_str)
        if move not in board.legal_moves:
            break
        board.push(move)
        moves.append(uci_str)

    ply = len(moves)

    # (fen, eval_cp_stm, ply) — result attached by finalize()
    raw: list[tuple[str, int, int]] = []
    consecutive_low_eval = 0
    prev_eval_stm = 0

    while ply < MAX_GAME_PLIES:
        bestmove, eval_cp = engine.go(moves, depth=depth, nodes=nodes)
        white_to_move = board.turn == chess.WHITE

        if bestmove == "(none)":
            # No legal moves: checkmate or stalemate
            if abs(prev_eval_stm) > 500:
                prev_was_white = not white_to_move
                result = 1 if prev_was_white else -1
            else:
                result = 0
            return _finalize(raw, result)

        # Quiet filter: record only non-capture, non-check, in-range positions
        if ply >= SKIP_PLIES and abs(eval_cp) <= EVAL_CLIP:
            best_chess_move = chess.Move.from_uci(bestmove)
            if not board.is_check() and not board.is_capture(best_chess_move):
                raw.append((board.fen(), eval_cp, ply))

        # Apply move
        try:
            move = chess.Move.from_uci(bestmove)
            if move not in board.legal_moves:
                return _finalize(raw, 0)
            board.push(move)
        except ValueError:
            return _finalize(raw, 0)

        moves.append(bestmove)
        ply += 1
        prev_eval_stm = eval_cp

        if abs(eval_cp) < 10:
            consecutive_low_eval += 1
        else:
            consecutive_low_eval = 0

        if consecutive_low_eval >= 80:
            return _finalize(raw, 0)

        # Mate score: declare result and stop
        if abs(eval_cp) > 40000:
            if eval_cp > 0:
                result = 1 if white_to_move else -1
            else:
                result = -1 if white_to_move else 1
            return _finalize(raw, result)

    return _finalize(raw, 0)


def _finalize(
    raw: list[tuple[str, int, int]], result_int: int
) -> list[tuple[str, int, float]]:
    """Attach the game result to every recorded position."""
    result_f = _RESULT_FLOAT[result_int]
    return [(fen, ev, result_f) for fen, ev, _ply in raw]


def write_positions(f, positions: list[tuple[str, int, float]]):
    """Write positions in pipe-separated format: FEN | eval_stm | result_white."""
    for fen, eval_cp, result_white in positions:
        eval_cp = max(-32000, min(32000, eval_cp))
        f.write(f"{fen} | {eval_cp} | {result_white}\n")


def count_existing(path: str) -> int:
    """Count positions already written (one per line)."""
    try:
        with open(path, "r") as f:
            return sum(1 for line in f if line.strip())
    except FileNotFoundError:
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-play NNUE training data with Rust Pyro engine"
    )
    parser.add_argument(
        "--depth", type=int, default=None,
        help="Search depth per move (default: use --nodes)",
    )
    parser.add_argument(
        "--nodes", type=int, default=5000,
        help="Node budget per move when --depth is not set (default: 5000)",
    )
    parser.add_argument(
        "--target", type=int, default=100_000_000,
        help="Target number of quiet positions to generate (default: 100M)",
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT,
        help="Output file path",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Append to existing file and count existing positions",
    )
    parser.add_argument(
        "--engine", type=str, default=ENGINE_PATH,
        help="Path to Pyro engine binary",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--no-nnue", action="store_true", dest="no_nnue",
        help="Pass --no-nnue to engine (use PeSTO+Tal eval, skip broken NNUE weights)",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if not os.path.isfile(args.engine):
        print(f"Engine not found: {args.engine}")
        print("Build it: cd engine && cargo build --release")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    existing = 0
    if args.resume:
        existing = count_existing(args.output)
        print(f"Resuming: {existing:,} positions already written")

    mode = "a" if args.resume else "w"
    search_desc = f"depth {args.depth}" if args.depth is not None else f"nodes {args.nodes}"

    print(f"Engine:  {args.engine}")
    print(f"Output:  {os.path.abspath(args.output)}")
    print(f"Search:  {search_desc}/move")
    print(f"NNUE:    {'disabled (PST+Tal)' if args.no_nnue else 'enabled (from pyro.nnue)'}")
    print(f"Target:  {args.target:,} quiet positions")
    print(f"Filter:  quiet only (no captures, no checks)")
    print()

    engine = UCIEngine(args.engine, no_nnue=args.no_nnue)

    wins = draws = losses = 0
    total_positions = existing
    new_positions = 0
    game_num = 0
    start_time = time.time()
    last_report_at = existing  # track when we last printed progress

    try:
        with open(args.output, mode) as f:
            while total_positions < args.target:
                game_num += 1
                positions = play_game(engine, args.depth, args.nodes)

                if positions:
                    write_positions(f, positions)
                    f.flush()
                    new_positions += len(positions)
                    total_positions += len(positions)

                    result_f = positions[0][2]
                    if result_f == 1.0:
                        wins += 1
                    elif result_f == 0.5:
                        draws += 1
                    else:
                        losses += 1
                else:
                    draws += 1

                # Progress report every 10k new positions
                if total_positions - last_report_at >= 10_000:
                    last_report_at = total_positions
                    elapsed = time.time() - start_time
                    rate = new_positions / elapsed if elapsed > 0 else 0
                    remaining = args.target - total_positions
                    eta_h = remaining / rate / 3600 if rate > 0 else float("inf")
                    print(
                        f"  {total_positions:>12,} / {args.target:,} positions  "
                        f"({rate:,.0f}/sec  ETA {eta_h:.1f}h)  "
                        f"games {game_num}  W{wins}/D{draws}/L{losses}"
                    )

    except KeyboardInterrupt:
        print(f"\nInterrupted after {game_num} games")
    finally:
        engine.quit()

    elapsed = time.time() - start_time
    print()
    print(f"Done: {game_num} games in {elapsed:.1f}s")
    print(f"Results: W{wins} / D{draws} / L{losses}")
    print(f"Total positions: {total_positions:,}  (new this run: {new_positions:,})")
    print(f"File: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
