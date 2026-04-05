"""Validate trained NNUE by playing games: NNUE Pyro vs PST Pyro.

Runs two instances of the Rust engine:
  - NNUE: loads pyro.nnue (trained weights)
  - PST:  runs with --no-nnue flag (PeSTO evaluation only)

Games alternate colors. Each move uses "go nodes 5000".
Reports W/D/L and score percentage. PASS if NNUE scores >= 52%.

Usage:
  cd backend && source venv/Scripts/activate
  python -m scripts.validate_nnue_rust --games 200
"""

import argparse
import os
import subprocess
import sys
import time


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "engine", "target", "release", "pyro.exe")
)

NODE_LIMIT = 5000
MAX_GAME_PLIES = 400


class UCIEngine:
    """Manages a UCI engine subprocess."""

    def __init__(self, path: str, extra_args: list[str] = None):
        cmd = [path] + (extra_args or [])
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

    def go_nodes(self, moves: list[str], nodes: int) -> tuple[str, int]:
        """Search and return (bestmove, eval_cp from STM perspective)."""
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
                bestmove = line.split()[1]
                break

        return bestmove, eval_cp

    def quit(self):
        try:
            self._send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def play_game(
    white_engine: UCIEngine,
    black_engine: UCIEngine,
    node_limit: int,
) -> int:
    """Play one game. Returns result from White's perspective: 1/0/-1."""
    white_engine.new_game()
    black_engine.new_game()

    moves: list[str] = []
    ply = 0
    consecutive_low_eval = 0
    prev_eval_stm = 0

    while ply < MAX_GAME_PLIES:
        engine = white_engine if ply % 2 == 0 else black_engine
        bestmove, eval_cp = engine.go_nodes(moves, node_limit)

        white_to_move = ply % 2 == 0

        if bestmove == "(none)":
            # No legal moves — checkmate or stalemate
            if abs(prev_eval_stm) > 500:
                prev_was_white = not white_to_move
                return 1 if prev_was_white else -1
            else:
                return 0  # stalemate

        prev_eval_stm = eval_cp
        moves.append(bestmove)
        ply += 1

        # Draw by low eval
        if abs(eval_cp) < 10:
            consecutive_low_eval += 1
        else:
            consecutive_low_eval = 0

        if consecutive_low_eval >= 80:
            return 0

        # Mate found
        if abs(eval_cp) > 40000:
            if eval_cp > 0:
                return 1 if white_to_move else -1
            else:
                return -1 if white_to_move else 1

    return 0  # max plies


def main():
    parser = argparse.ArgumentParser(
        description="Validate NNUE vs PST by playing games"
    )
    parser.add_argument("--games", type=int, default=200, help="Number of games")
    parser.add_argument("--nodes", type=int, default=NODE_LIMIT, help="Nodes per move")
    parser.add_argument("--engine", type=str, default=ENGINE_PATH, help="Engine binary")
    parser.add_argument("--pass-threshold", type=float, default=52.0,
                        help="Score %% needed to pass")
    args = parser.parse_args()

    if not os.path.isfile(args.engine):
        print(f"Engine not found: {args.engine}")
        print("Build it first: cd engine && cargo build --release")
        sys.exit(1)

    print(f"Engine: {args.engine}")
    print(f"Games:  {args.games}")
    print(f"Nodes:  {args.nodes}/move")
    print(f"Pass:   >= {args.pass_threshold:.0f}% score")
    print()

    # Launch both engines
    nnue_engine = UCIEngine(args.engine)
    pst_engine = UCIEngine(args.engine, ["--no-nnue"])

    # NNUE results
    nnue_wins = 0
    nnue_draws = 0
    nnue_losses = 0

    start_time = time.time()

    try:
        for game_num in range(1, args.games + 1):
            nnue_is_white = game_num % 2 == 1

            if nnue_is_white:
                white_eng, black_eng = nnue_engine, pst_engine
                white_label, black_label = "NNUE", "PST"
            else:
                white_eng, black_eng = pst_engine, nnue_engine
                white_label, black_label = "PST", "NNUE"

            result_white = play_game(white_eng, black_eng, args.nodes)

            # Convert to NNUE perspective
            result_nnue = result_white if nnue_is_white else -result_white

            if result_nnue == 1:
                nnue_wins += 1
                outcome = f"{white_label} wins" if nnue_is_white else f"{black_label} wins"
            elif result_nnue == -1:
                nnue_losses += 1
                outcome = f"{black_label} wins" if nnue_is_white else f"{white_label} wins"
            else:
                nnue_draws += 1
                outcome = "draw"

            total = nnue_wins + nnue_draws + nnue_losses
            score_pct = (nnue_wins + 0.5 * nnue_draws) / total * 100

            elapsed = time.time() - start_time
            gps = game_num / elapsed if elapsed > 0 else 0

            if game_num <= 5 or game_num % 10 == 0:
                print(
                    f"Game {game_num:3d}/{args.games}: "
                    f"{white_label} W vs {black_label} B -> {outcome}  "
                    f"[NNUE W{nnue_wins}/D{nnue_draws}/L{nnue_losses} = {score_pct:.1f}%]  "
                    f"({gps:.1f} g/s)"
                )

    except KeyboardInterrupt:
        print(f"\nInterrupted after {nnue_wins + nnue_draws + nnue_losses} games")
    finally:
        nnue_engine.quit()
        pst_engine.quit()

    total = nnue_wins + nnue_draws + nnue_losses
    if total == 0:
        print("No games played")
        sys.exit(1)

    score_pct = (nnue_wins + 0.5 * nnue_draws) / total * 100
    elapsed = time.time() - start_time

    print()
    print(f"Results ({total} games, {elapsed:.1f}s):")
    print(f"  NNUE: W={nnue_wins}  D={nnue_draws}  L={nnue_losses}  ({score_pct:.1f}% score)")
    print()

    if score_pct >= args.pass_threshold:
        print(f"PASS  (NNUE scores {score_pct:.1f}% >= {args.pass_threshold:.0f}%)")
        sys.exit(0)
    else:
        print(f"FAIL  (NNUE scores {score_pct:.1f}% < {args.pass_threshold:.0f}%)")
        sys.exit(1)


if __name__ == "__main__":
    main()
