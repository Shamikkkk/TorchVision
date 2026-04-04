"""Generate self-play training data using the Rust Pyro engine.

Drives the Rust engine via UCI protocol with randomized openings
so each game explores different positions.

Binary output format (18 bytes per position):
  board_hash: u64 (8 bytes) — FNV-1a hash of move sequence
  eval_cp:    i16 (2 bytes) — engine eval in centipawns (white-relative)
  result:     u8  (1 byte)  — 0=black wins, 1=draw, 2=white wins
  ply:        u8  (1 byte)  — half-move count from game start
  padding:    6 bytes        — reserved for future use

WDL interpolation is done at training time:
  target = 0.5 * sigmoid(eval_cp / 400) + 0.5 * game_result
"""

import argparse
import os
import random
import struct
import subprocess
import sys
import time


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "engine", "target", "release", "pyro.exe")
)
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "..", "data", "selfplay_rust.bin")

NODE_LIMIT = 5000
MAX_GAME_PLIES = 400   # max half-moves per game (200 full moves)
SKIP_PLIES = 8         # skip first 8 half-moves (opening theory)
EVAL_CLIP = 3000       # skip positions with |eval| > this

# --- Opening randomization ---
# Common openings: (white_move, [black_responses])
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


def fnv1a_hash(data: bytes) -> int:
    """FNV-1a 64-bit hash."""
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


class UCIEngine:
    """Manages a UCI engine subprocess."""

    def __init__(self, path: str):
        self.proc = subprocess.Popen(
            [path],
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
        """Read lines until one starts with token. Return all lines read."""
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
        """Search position and return (bestmove, eval_cp)."""
        if moves:
            self._send(f"position startpos moves {' '.join(moves)}")
        else:
            self._send("position startpos")

        self._send(f"go nodes {nodes}")
        lines = self._wait_for("bestmove")

        # Parse eval from info lines
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

        # Parse bestmove
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
    """Pick a random opening (2 plies: one white move + one black response)."""
    white_move, black_responses = random.choice(OPENING_PAIRS)
    black_move = random.choice(black_responses)
    return [white_move, black_move]


def play_game(engine: UCIEngine, node_limit: int) -> list[tuple[int, int, int, int]]:
    """Play one self-play game.

    Returns list of (board_hash, eval_cp_white, ply, result) tuples.
    """
    engine.new_game()

    # Start with a random opening (2 plies)
    moves: list[str] = random_opening()
    ply = len(moves)

    positions: list[tuple[int, int, int]] = []  # (hash, eval_cp_white, ply)
    consecutive_low_eval = 0
    prev_eval_stm = 0  # last eval from side-to-move perspective

    while ply < MAX_GAME_PLIES:
        bestmove, eval_cp = engine.go_nodes(moves, node_limit)

        white_to_move = (ply % 2 == 0)

        if bestmove == "(none)":
            # No legal moves: checkmate or stalemate.
            # Use previous eval to distinguish: if the side that just moved
            # had a large advantage (prev_eval_stm was high), they delivered
            # checkmate. Otherwise it's stalemate.
            if abs(prev_eval_stm) > 500:
                # Previous side was winning — they delivered checkmate.
                # prev side was white if current ply is odd (black to move now)
                prev_was_white = not white_to_move
                result = 2 if prev_was_white else 0
            else:
                result = 1  # stalemate
            return finalize(positions, result)

        # eval_cp is from STM perspective — convert to white-relative
        eval_white = eval_cp if white_to_move else -eval_cp
        prev_eval_stm = eval_cp

        # Record position (skip opening plies and extreme evals)
        if ply >= SKIP_PLIES and abs(eval_cp) <= EVAL_CLIP:
            pos_key = " ".join(moves).encode("ascii")
            board_hash = fnv1a_hash(pos_key)
            positions.append((board_hash, eval_white, ply))

        moves.append(bestmove)
        ply += 1

        # Draw: eval stays near 0 for 80 consecutive plies
        if abs(eval_cp) < 10:
            consecutive_low_eval += 1
        else:
            consecutive_low_eval = 0

        if consecutive_low_eval >= 80:
            return finalize(positions, 1)

        # Mate found by engine — the side to move found a forced mate.
        # eval_cp > 40000 means STM is winning (will deliver mate).
        if abs(eval_cp) > 40000:
            if eval_cp > 0:
                # STM found mate — STM wins
                result = 2 if white_to_move else 0
            else:
                # STM is getting mated — other side wins
                result = 0 if white_to_move else 2
            return finalize(positions, result)

    # Max plies reached — draw
    return finalize(positions, 1)


def finalize(
    positions: list[tuple[int, int, int]], result: int
) -> list[tuple[int, int, int, int]]:
    """Attach game result to all positions."""
    return [(h, ev, ply, result) for h, ev, ply in positions]


def write_positions(f, positions: list[tuple[int, int, int, int]]):
    """Write positions in binary format."""
    padding = b"\x00" * 6
    for board_hash, eval_cp, ply, result in positions:
        eval_cp = max(-32768, min(32767, eval_cp))
        ply = min(255, ply)
        f.write(struct.pack("<Q", board_hash))
        f.write(struct.pack("<h", eval_cp))
        f.write(struct.pack("<B", result))
        f.write(struct.pack("<B", ply))
        f.write(padding)


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-play data with Rust Pyro engine"
    )
    parser.add_argument("--games", type=int, default=10000, help="Number of games")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output file")
    parser.add_argument("--resume", action="store_true", help="Append to existing file")
    parser.add_argument("--nodes", type=int, default=NODE_LIMIT, help="Nodes per move")
    parser.add_argument("--engine", type=str, default=ENGINE_PATH, help="Engine binary")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if not os.path.isfile(args.engine):
        print(f"Engine not found: {args.engine}")
        print("Build it first: cd engine && cargo build --release")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    mode = "ab" if args.resume else "wb"
    existing_positions = 0
    if args.resume and os.path.isfile(args.output):
        existing_positions = os.path.getsize(args.output) // 18
        print(f"Resuming: {existing_positions:,} existing positions")

    print(f"Engine: {args.engine}")
    print(f"Output: {os.path.abspath(args.output)}")
    print(f"Games:  {args.games}")
    print(f"Nodes:  {args.nodes}/move")
    print(f"Openings: {len(OPENING_PAIRS)} first moves x varied responses")
    print()

    engine = UCIEngine(args.engine)

    wins = 0    # white wins
    draws = 0
    losses = 0  # black wins
    total_positions = existing_positions
    start_time = time.time()

    try:
        with open(args.output, mode) as f:
            for game_num in range(1, args.games + 1):
                positions = play_game(engine, args.nodes)

                if positions:
                    write_positions(f, positions)
                    f.flush()

                # Count result
                if positions:
                    result = positions[0][3]
                    if result == 2:
                        wins += 1
                    elif result == 1:
                        draws += 1
                    else:
                        losses += 1
                else:
                    draws += 1  # no positions = very short draw

                total_positions += len(positions)
                elapsed = time.time() - start_time
                gps = game_num / elapsed if elapsed > 0 else 0

                if game_num % 10 == 0 or game_num <= 3:
                    print(
                        f"Game {game_num}/{args.games}: "
                        f"W{wins}/D{draws}/L{losses}  "
                        f"positions: {len(positions)}  "
                        f"total: {total_positions:,}  "
                        f"({gps:.1f} games/s)"
                    )

    except KeyboardInterrupt:
        print(f"\nInterrupted after {wins + draws + losses} games")
    finally:
        engine.quit()

    elapsed = time.time() - start_time
    total_games = wins + draws + losses
    print()
    print(f"Done: {total_games} games in {elapsed:.1f}s")
    print(f"Results: W{wins} ({100*wins//max(total_games,1)}%) / "
          f"D{draws} ({100*draws//max(total_games,1)}%) / "
          f"L{losses} ({100*losses//max(total_games,1)}%)")
    print(f"Total positions: {total_positions:,}")
    print(f"File size: {os.path.getsize(args.output):,} bytes")


if __name__ == "__main__":
    main()
