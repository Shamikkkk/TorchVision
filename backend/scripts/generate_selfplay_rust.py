"""Generate self-play training data using the Rust Pyro engine.

Drives two copies of the Rust engine (one per side) via UCI protocol.
Each move uses "go nodes 5000" for consistent quality.

Binary output format (18 bytes per position):
  board_hash: u64 (8 bytes) — FNV-1a hash of FEN position part
  eval_cp:    i16 (2 bytes) — engine eval in centipawns (STM-relative)
  result:     u8  (1 byte)  — 0=black wins, 1=draw, 2=white wins
  ply:        u8  (1 byte)  — half-move count from game start
  padding:    6 bytes        — reserved for future use

WDL interpolation is done at training time:
  target = 0.5 * sigmoid(eval_cp / 400) + 0.5 * game_result
"""

import argparse
import hashlib
import os
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


def fnv1a_hash(data: bytes) -> int:
    """FNV-1a 64-bit hash."""
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def fen_board_hash(fen: str) -> int:
    """Hash only the board position + side to move from a FEN string."""
    # Use first two FEN fields: piece placement + side to move
    parts = fen.split()
    key = f"{parts[0]} {parts[1]}".encode("ascii")
    return fnv1a_hash(key)


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

    def go_nodes(self, fen: str, moves: list[str], nodes: int) -> tuple[str, int]:
        """Search position and return (bestmove, eval_cp)."""
        if moves:
            self._send(f"position fen {fen} moves {' '.join(moves)}")
        else:
            self._send(f"position fen {fen}")

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


STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def is_game_over(fen: str, moves: list[str], engine: UCIEngine) -> tuple[bool, int | None]:
    """Check if the game is over by trying to get a move.

    Returns (is_over, result) where result: 0=black, 1=draw, 2=white, None=not over.
    """
    # 50-move rule
    parts = fen.split()
    halfmove = int(parts[4]) if len(parts) > 4 else 0

    # We can't easily detect checkmate/stalemate without the engine's move gen.
    # Instead, we send "go nodes 1" and if bestmove is "(none)", it's game over.
    # But we already get bestmove from the main search, so we handle it in the game loop.
    return False, None


def play_game(engine: UCIEngine, node_limit: int) -> list[tuple[int, int, int]]:
    """Play one self-play game. Returns list of (board_hash, eval_cp, ply) tuples.

    Result (0/1/2) is filled in after the game ends.
    """
    engine.new_game()
    moves: list[str] = []
    positions: list[tuple[int, int, int]] = []  # (hash, eval_cp, ply)
    fen = STARTPOS_FEN
    ply = 0
    consecutive_no_progress = 0
    last_halfmove = 0

    while ply < MAX_GAME_PLIES:
        bestmove, eval_cp = engine.go_nodes(fen, moves, node_limit)

        if bestmove == "(none)":
            # Game over — checkmate or stalemate
            # If eval is very negative, side to move is mated
            if abs(eval_cp) > 40000:
                # Checkmate — the side to move lost
                white_to_move = (ply % 2 == 0)
                result = 0 if white_to_move else 2  # loser's perspective
            else:
                result = 1  # stalemate = draw
            return finalize(positions, result)

        # Eval from STM perspective — convert to white-relative for storage
        white_to_move = (ply % 2 == 0)
        eval_white = eval_cp if white_to_move else -eval_cp

        # Record position (skip early plies and extreme evals)
        if ply >= SKIP_PLIES and abs(eval_cp) <= EVAL_CLIP:
            parts = fen.split()
            # Build the actual FEN after moves by using position string
            # For hashing, we use the move list representation
            pos_key = f"{fen} {' '.join(moves)}".encode("ascii")
            board_hash = fnv1a_hash(pos_key)
            positions.append((board_hash, eval_white, ply))

        moves.append(bestmove)
        ply += 1

        # Update FEN for tracking (we don't actually need the full FEN since
        # we send "position fen startpos moves ..." to the engine)
        # But we need to track side to move and halfmove clock for draw detection

        # Simple draw detection: if eval stays near 0 for too long
        if abs(eval_cp) < 10:
            consecutive_no_progress += 1
        else:
            consecutive_no_progress = 0

        if consecutive_no_progress >= 80:
            return finalize(positions, 1)  # draw by no progress

        # Detect if eval suggests decisive advantage held for a while
        if abs(eval_cp) > 40000:
            # Mate score — game is effectively over
            if eval_cp > 0:
                result = 2 if white_to_move else 0
            else:
                result = 0 if white_to_move else 2
            return finalize(positions, result)

    # Max plies reached — draw
    return finalize(positions, 1)


def finalize(positions: list[tuple[int, int, int]], result: int) -> list[tuple[int, int, int, int]]:
    """Attach game result to all positions."""
    return [(h, ev, ply, result) for h, ev, ply in positions]


def write_positions(f, positions: list[tuple[int, int, int, int]]):
    """Write positions in binary format."""
    padding = b"\x00" * 6
    for board_hash, eval_cp, ply, result in positions:
        # Clamp eval to i16 range
        eval_cp = max(-32768, min(32767, eval_cp))
        ply = min(255, ply)
        f.write(struct.pack("<Q", board_hash))      # u64
        f.write(struct.pack("<h", eval_cp))          # i16
        f.write(struct.pack("<B", result))            # u8
        f.write(struct.pack("<B", ply))               # u8
        f.write(padding)                              # 6 bytes


def main():
    parser = argparse.ArgumentParser(description="Generate self-play data with Rust Pyro engine")
    parser.add_argument("--games", type=int, default=10000, help="Number of games to play")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output binary file")
    parser.add_argument("--resume", action="store_true", help="Append to existing file")
    parser.add_argument("--nodes", type=int, default=NODE_LIMIT, help="Node limit per move")
    parser.add_argument("--engine", type=str, default=ENGINE_PATH, help="Path to engine binary")
    args = parser.parse_args()

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
    print()

    engine = UCIEngine(args.engine)

    wins = 0
    draws = 0
    losses = 0
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

                total_positions += len(positions)
                elapsed = time.time() - start_time
                gps = game_num / elapsed if elapsed > 0 else 0

                if game_num % 10 == 0 or game_num == 1:
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
    print()
    print(f"Done: {wins + draws + losses} games in {elapsed:.1f}s")
    print(f"Results: W{wins} / D{draws} / L{losses}")
    print(f"Total positions: {total_positions:,}")
    print(f"File size: {os.path.getsize(args.output):,} bytes")


if __name__ == "__main__":
    main()
