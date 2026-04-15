"""TAL_AGGRESSION A/B match: play two Rust engine binaries against each other.

Usage
-----
Build baseline (TAL=1.5) and candidate (TAL=X) binaries separately, then run:

    python -m scripts.tune_aggression \\
        --engine-a ../../engine/target/release/pyro_baseline.exe \\
        --engine-b ../../engine/target/release/pyro_candidate.exe \\
        --games 40 --nodes 5000

Results are reported as W/D/L from Engine A's perspective and as a score %.
Engines alternate colours every game so first-move advantage cancels out.
"""

import argparse
import os
import random
import subprocess
import sys

import chess


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "engine", "target", "release", "pyro.exe")
)

NODE_LIMIT  = 5000
MAX_PLIES   = 400   # half-moves (200 full moves)
SKIP_PLIES  = 8     # not used in match games — every move counts

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


class UCIEngine:
    """Manages a single UCI engine subprocess."""

    def __init__(self, path: str, label: str = ""):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Engine binary not found: {path}")
        self.label = label or os.path.basename(path)
        self.proc = subprocess.Popen(
            [path, "--no-nnue"],
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

    def _send(self, cmd: str) -> None:
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _wait_for(self, token: str) -> list[str]:
        lines: list[str] = []
        while True:
            line = self.proc.stdout.readline().strip()
            if not line and self.proc.poll() is not None:
                raise RuntimeError(f"Engine {self.label!r} process died")
            lines.append(line)
            if line.startswith(token):
                return lines

    def new_game(self) -> None:
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")

    def go_nodes(self, moves: list[str], nodes: int) -> tuple[str, int]:
        """Search and return (bestmove_uci, eval_cp_stm)."""
        if moves:
            self._send(f"position startpos moves {' '.join(moves)}")
        else:
            self._send("position startpos")
        self._send(f"go nodes {nodes}")
        lines = self._wait_for("bestmove")

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
                toks = line.split()
                if len(toks) >= 2:
                    bestmove = toks[1]
                break

        return bestmove, eval_cp

    def quit(self) -> None:
        try:
            self._send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def random_opening() -> list[str]:
    white_move, black_responses = random.choice(OPENING_PAIRS)
    black_move = random.choice(black_responses)
    return [white_move, black_move]


def play_game(
    engine_white: UCIEngine,
    engine_black: UCIEngine,
    nodes: int,
) -> str:
    """Play one game.  Returns 'white', 'black', or 'draw'."""
    engine_white.new_game()
    engine_black.new_game()

    board = chess.Board()
    moves: list[str] = []

    # Randomised opening (2 plies)
    for uci_str in random_opening():
        mv = chess.Move.from_uci(uci_str)
        if mv not in board.legal_moves:
            break
        board.push(mv)
        moves.append(uci_str)

    consecutive_low = 0
    prev_eval_stm = 0

    for _ply in range(MAX_PLIES):
        engine = engine_white if board.turn == chess.WHITE else engine_black
        bestmove, eval_cp = engine.go_nodes(moves, nodes)

        white_to_move = board.turn == chess.WHITE

        if bestmove == "(none)":
            if board.is_checkmate():
                return "black" if white_to_move else "white"
            return "draw"

        # Stalemate / repetition / material checks via python-chess
        # (engine may not detect 50-move / 3-fold; we check explicitly)
        mv = chess.Move.from_uci(bestmove)
        if mv not in board.legal_moves:
            return "draw"  # illegal move — treat as forfeit/draw

        board.push(mv)
        moves.append(bestmove)

        # python-chess game-over checks
        if board.is_checkmate():
            return "white" if board.turn == chess.BLACK else "black"
        if board.is_stalemate() or board.is_insufficient_material():
            return "draw"
        if board.can_claim_fifty_moves() or board.is_repetition(3):
            return "draw"

        # Eval-based termination
        prev_eval_stm = eval_cp
        if abs(eval_cp) > 40_000:
            return ("white" if white_to_move else "black") if eval_cp > 0 else \
                   ("black" if white_to_move else "white")

        if abs(eval_cp) < 10:
            consecutive_low += 1
        else:
            consecutive_low = 0
        if consecutive_low >= 80:
            return "draw"

    return "draw"


def main() -> None:
    parser = argparse.ArgumentParser(description="TAL_AGGRESSION A/B match")
    parser.add_argument(
        "--engine-a",
        default=ENGINE_PATH,
        help="Path to Engine A binary (baseline, default: pyro.exe)",
    )
    parser.add_argument(
        "--engine-b",
        required=True,
        help="Path to Engine B binary (candidate)",
    )
    parser.add_argument("--games",  type=int, default=40,         help="Number of games (default 40)")
    parser.add_argument("--nodes",  type=int, default=NODE_LIMIT, help="Nodes per move (default 5000)")
    parser.add_argument("--label-a", default="A (baseline)",      help="Label for engine A")
    parser.add_argument("--label-b", default="B (candidate)",     help="Label for engine B")
    parser.add_argument("--seed",   type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    print(f"Engine A: {args.engine_a}  [{args.label_a}]")
    print(f"Engine B: {args.engine_b}  [{args.label_b}]")
    print(f"Games:    {args.games}  |  Nodes/move: {args.nodes}")
    print()

    try:
        eng_a = UCIEngine(args.engine_a, args.label_a)
        eng_b = UCIEngine(args.engine_b, args.label_b)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # W/D/L from Engine A's perspective
    a_wins = a_draws = a_losses = 0

    try:
        for game_num in range(1, args.games + 1):
            # Alternate colours every game
            if game_num % 2 == 1:
                white_engine, black_engine = eng_a, eng_b
                a_is_white = True
            else:
                white_engine, black_engine = eng_b, eng_a
                a_is_white = False

            result = play_game(white_engine, black_engine, args.nodes)

            if result == "draw":
                a_draws += 1
                label = "draw"
            elif (result == "white" and a_is_white) or (result == "black" and not a_is_white):
                a_wins += 1
                label = f"A wins  ({args.label_a})"
            else:
                a_losses += 1
                label = f"B wins  ({args.label_b})"

            total = a_wins + a_draws + a_losses
            score_pct = (a_wins + 0.5 * a_draws) / total * 100
            print(
                f"Game {game_num:3d}:  {label:<28s}  "
                f"A: W{a_wins}/D{a_draws}/L{a_losses}  score={score_pct:.1f}%"
            )

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        eng_a.quit()
        eng_b.quit()

    total = a_wins + a_draws + a_losses
    if total == 0:
        return

    score_pct = (a_wins + 0.5 * a_draws) / total * 100
    print()
    print("=" * 60)
    print(f"FINAL  ({total} games)")
    print(f"  {args.label_a}: W{a_wins}/D{a_draws}/L{a_losses}  score={score_pct:.1f}%")
    print(f"  {args.label_b}: W{a_losses}/D{a_draws}/L{a_wins}  score={100-score_pct:.1f}%")
    print()
    if score_pct > 52:
        print(f"  >> {args.label_a} is STRONGER  (+{score_pct-50:.1f}% over 50%)")
    elif score_pct < 48:
        print(f"  >> {args.label_b} is STRONGER  (+{50-score_pct:.1f}% over 50%)")
    else:
        print("  >> Too close to call -- run more games")
    print("=" * 60)


if __name__ == "__main__":
    main()
