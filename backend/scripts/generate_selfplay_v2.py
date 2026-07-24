"""Self-play data generator v2 — the Session 2b data campaign (July 2026).

Replaces generate_selfplay_rust.py, whose 37-pair fixed opening book x
deterministic engine produced a corpus of ~30 distinct games replayed
~10,000x each (the root cause of the fake 51% black bias, the 48% draw
mass, and the Phase D training ceiling — see HISTORY.md Stage 0 record).

v2 recipe (Stage 0 plan, reviewed July 12, 2026):
  - Openings: 4-8 uniformly-random legal plies from startpos, screened by
    the engine itself at depth 4 to |eval| <= 150cp. GLOBAL stem dedup by
    construction: stems are partitioned across workers by crc32 of the stem
    position epd (transpositions collapse), each worker dedups its slice.
  - COLOR BALANCE BY CONSTRUCTION: each screened stem is played twice —
    once as reached, once color-mirrored (python-chess Board.mirror()) —
    so opening-induced color advantage cancels by definition. Mirror-
    symmetric stems play only game A (B would be an identical replay).
  - Engine: pyro.exe --no-nnue, one process per worker, fixed nodes/move
    (default 8000) for predictable throughput. Eval quality is irrelevant:
    SF18 d12 relabels everything downstream.
  - Adjudication (the fake-draw mass is the enemy):
      * python-chess game-over incl. claimable draws (threefold/50-move)
      * Syzygy WDL probe at <= 6 pieces (backend/data/syzygy, instant)
      * resign: 4 consecutive plies with white-POV |eval| >= 900, same sign
      * shuffle draw: 60 consecutive plies with |eval| < 10
      * hard cap 250 plies -> draw (counted; should be rare)
  - Recording (identical filter to v1 so the SF18+convert pipeline runs
    unchanged): ply >= stem_len+2, not in check, best move not a capture,
    |eval| <= 3000. Line format: FEN | eval_cp_stm | result_white.

Output: one shard per worker ({output}.shard{i}.plain) + {shard}.stats.json;
merge shards after the run. Resume: rerun with same args — workers append.

Usage:
    python -m scripts.generate_selfplay_v2 --target 2_000_000 \
        --output C:/torch_data/selfplay_v2_pilot --workers 10
"""

import argparse
import json
import multiprocessing as mp
import os
import random
import signal
import subprocess
import sys
import time
import zlib

import chess
import chess.syzygy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# V2_ENGINE_PATH: campaign runs use a copy OUTSIDE the OneDrive-synced tree —
# OneDrive's July 18 52GB commit leak OOM-killed pyro spawns mid-campaign
ENGINE_PATH = os.environ.get("V2_ENGINE_PATH") or os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "engine", "target", "release", "pyro.exe")
)
SYZYGY_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "syzygy"))

# Opening scheme
STEM_PLIES_MIN = 4
STEM_PLIES_MAX = 8
STEM_EVAL_SCREEN = 150     # |eval| at depth 4 must be <= this
STEM_SCREEN_DEPTH = 4

# Adjudication
RESIGN_EVAL = 900          # white-POV |eval| >= this ...
RESIGN_PLIES = 4           # ... for this many consecutive plies, same sign
SHUFFLE_EVAL = 10          # |eval| < this ...
SHUFFLE_PLIES = 60         # ... for this many consecutive plies -> draw
MAX_PLIES = 250            # hard cap -> draw (counted)

# Recording (matches v1 quiet filter)
EVAL_CLIP = 3000


def disable_power_throttling(pid: int | None = None):
    """Force Windows EcoQoS OFF for a process (default: current).

    ROOT CAUSE (July 16, 2026): processes launched from background/hidden
    contexts get EcoQoS power-throttling — CPU pinned at ~50% frequency and
    lazy scheduling, degrading the pipeline ~7x (28 pos/s vs ~190). This
    releases it (measured: %ProcessorPerformance 48% -> 144% instantly).
    """
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class PPTS(ctypes.Structure):
        _fields_ = [("Version", wintypes.DWORD),
                    ("ControlMask", wintypes.DWORD),
                    ("StateMask", wintypes.DWORD)]

    k32 = ctypes.windll.kernel32
    try:
        if pid is None:
            h = k32.GetCurrentProcess()
        else:
            h = k32.OpenProcess(0x0200, False, pid)  # PROCESS_SET_INFORMATION
            if not h:
                return
        s = PPTS(1, 0x1, 0)  # control EXECUTION_SPEED; state 0 = never throttle
        k32.SetProcessInformation(h, 4, ctypes.byref(s), ctypes.sizeof(s))
        if pid is not None:
            k32.CloseHandle(h)
    except Exception:
        pass


class UCIEngine:
    """Thin UCI wrapper (adapted from generate_selfplay_rust.py)."""

    def __init__(self, path: str):
        self.proc = subprocess.Popen(
            [path, "--no-nnue"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        disable_power_throttling(self.proc.pid)
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

    def go(self, root_fen: str | None, moves: list[str], *,
           depth: int | None = None, nodes: int | None = None) -> tuple[str, int]:
        """Search; returns (bestmove, eval_cp_stm)."""
        pos = "position startpos" if root_fen is None else f"position fen {root_fen}"
        if moves:
            pos += " moves " + " ".join(moves)
        self._send(pos)
        self._send(f"go depth {depth}" if depth is not None else f"go nodes {nodes}")
        lines = self._wait_for("bestmove")

        eval_cp = 0
        for line in lines:
            if "score cp" in line:
                try:
                    eval_cp = int(line.split("score cp")[1].split()[0])
                except (ValueError, IndexError):
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


def random_stem(rng: random.Random, engine: UCIEngine, seen: set,
                worker_id: int, n_workers: int,
                stats: dict) -> tuple[list[str], chess.Board] | None:
    """One attempt at a screened random opening stem. None = rejected.

    Global dedup by construction: stems are partitioned across workers by a
    stable hash of the stem POSITION (epd, so transpositions collapse too) —
    a stem belongs to exactly one worker, which also dedups it locally.
    Python's hash() is salted per process, hence zlib.crc32.
    """
    board = chess.Board()
    n_plies = rng.randint(STEM_PLIES_MIN, STEM_PLIES_MAX)
    moves: list[str] = []
    for _ in range(n_plies):
        legal = list(board.legal_moves)
        if not legal:
            return None
        mv = rng.choice(legal)
        moves.append(mv.uci())
        board.push(mv)
    if board.is_game_over():
        return None
    # dedup on the crc32 itself (int set, ~60B/entry vs ~190B for EPD
    # strings; a same-worker crc collision merely skips one valid stem)
    h = zlib.crc32(board.epd().encode())
    if h % n_workers != worker_id:
        stats["stem_offpartition"] = stats.get("stem_offpartition", 0) + 1
        return None
    if h in seen:
        return None
    _, eval_cp = engine.go(None, moves, depth=STEM_SCREEN_DEPTH)
    if abs(eval_cp) > STEM_EVAL_SCREEN:
        return None
    seen.add(h)
    return moves, board, h


def play_game(engine: UCIEngine, tb: chess.syzygy.Tablebase | None,
              root_fen: str | None, init_moves: list[str], board: chess.Board,
              stem_len: int, nodes: int, stats: dict) -> list[tuple[str, int, float]]:
    """Play one game from the stem position. Returns [(fen, eval_stm, result_white)].

    root_fen=None → engine root is startpos and init_moves must be the stem
    moves; root_fen=FEN → engine root is that FEN and init_moves is empty.
    Either way `board` must already BE the stem position.
    """
    engine.new_game()
    board = board.copy()
    moves: list[str] = list(init_moves)
    raw: list[tuple[str, int]] = []

    resign_streak = 0          # consecutive plies with white-POV |eval| >= RESIGN_EVAL
    resign_sign = 0
    shuffle_streak = 0
    ply = stem_len
    result: float | None = None
    end = None

    while True:
        # --- terminal / adjudication checks on the current position ---
        if board.is_game_over(claim_draw=True):
            res_str = board.result(claim_draw=True)
            result = {"1-0": 1.0, "0-1": 0.0}.get(res_str, 0.5)
            end = "checkmate" if board.is_checkmate() else "rules_draw"
            break

        if tb is not None and chess.popcount(board.occupied) <= 6 \
                and not board.castling_rights:
            try:
                wdl = tb.probe_wdl(board)  # STM perspective
            except (chess.syzygy.MissingTableError, KeyError):
                wdl = None
            if wdl is not None:
                if abs(wdl) < 2:           # draw incl. cursed/blessed (50-move)
                    result = 0.5
                else:
                    stm_wins = wdl > 0
                    white_wins = stm_wins == (board.turn == chess.WHITE)
                    result = 1.0 if white_wins else 0.0
                end = "syzygy"
                break

        if ply >= MAX_PLIES:
            result = 0.5
            end = "cap"
            break

        # --- search ---
        bestmove, eval_cp = engine.go(root_fen, moves, nodes=nodes)
        if bestmove == "(none)":
            result = 0.5   # engine sees no move but board disagreed — treat as draw
            end = "engine_none"
            break

        eval_white = eval_cp if board.turn == chess.WHITE else -eval_cp

        # resign adjudication
        if abs(eval_white) >= RESIGN_EVAL:
            sign = 1 if eval_white > 0 else -1
            resign_streak = resign_streak + 1 if sign == resign_sign else 1
            resign_sign = sign
            if resign_streak >= RESIGN_PLIES:
                result = 1.0 if resign_sign > 0 else 0.0
                end = "resign"
                break
        else:
            resign_streak = 0
            resign_sign = 0

        # shuffle adjudication
        if abs(eval_cp) < SHUFFLE_EVAL:
            shuffle_streak += 1
            if shuffle_streak >= SHUFFLE_PLIES:
                result = 0.5
                end = "shuffle"
                break
        else:
            shuffle_streak = 0

        # recording (v1 quiet filter)
        if ply >= stem_len + 2 and abs(eval_cp) <= EVAL_CLIP:
            try:
                mv = chess.Move.from_uci(bestmove)
            except ValueError:
                result = 0.5
                end = "badmove"
                break
            if not board.is_check() and not board.is_capture(mv):
                raw.append((board.fen(), eval_cp))

        # apply move
        try:
            mv = chess.Move.from_uci(bestmove)
            if mv not in board.legal_moves:
                result = 0.5
                end = "illegal"
                break
            board.push(mv)
        except ValueError:
            result = 0.5
            end = "badmove"
            break
        moves.append(bestmove)
        ply += 1

    stats["end_" + end] = stats.get("end_" + end, 0) + 1
    stats["res_" + str(result)] = stats.get("res_" + str(result), 0) + 1
    return [(fen, ev, result) for fen, ev in raw]


def worker_fn(worker_id: int, args, target_per_worker: int):
    disable_power_throttling()

    if os.environ.get("V2_HEADLESS"):
        # detached campaign runs have died to spurious console-control
        # events (phantom ^C, July 16); stop a headless run with taskkill
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    rng = random.Random(args.seed * 1_000_003 + worker_id)
    shard_path = f"{args.output}.shard{worker_id}.plain"
    stats_path = f"{args.output}.shard{worker_id}.stats.json"

    written = 0
    stats: dict = {"games": 0}
    if os.path.exists(shard_path):
        with open(shard_path, "r", encoding="utf-8") as f:
            written = sum(1 for _ in f)
        if os.path.exists(stats_path):
            with open(stats_path) as f:
                stats = json.load(f)
        # advance RNG state so resume does not replay the same stems
        rng = random.Random(args.seed * 1_000_003 + worker_id + stats["games"] * 7919)

    def make_engine():
        # OOM famines kill pyro spawns transiently (July 18): retry with
        # backoff instead of dying on the first failure
        delay = 5
        for attempt in range(3):
            try:
                return UCIEngine(ENGINE_PATH)
            except Exception:
                stats["engine_spawn_retries"] = stats.get("engine_spawn_retries", 0) + 1
                time.sleep(delay)
                delay *= 3
        raise RuntimeError(f"worker {worker_id}: engine spawn failed after 3 attempts")

    engine = make_engine()
    tb = None
    if os.path.isdir(SYZYGY_PATH):
        tb = chess.syzygy.open_tablebase(SYZYGY_PATH)

    # stem dedup survives restarts: without the sidecar, every resume forgot
    # played stems and replayed ~1% of games (10M mini-audit, July 17).
    # Lines are 8-hex crc32 of the stem EPD.
    seen_path = f"{args.output}.shard{worker_id}.stems.txt"
    seen: set = set()
    if os.path.exists(seen_path):
        with open(seen_path, encoding="utf-8") as f:
            seen = {int(ln, 16) for ln in f if ln.strip()}
    seen_out = open(seen_path, "a", encoding="utf-8")
    t0 = time.time()
    last_flush = t0

    with open(shard_path, "a", encoding="utf-8") as out:
        while written < target_per_worker:
            try:
                stem = random_stem(rng, engine, seen, worker_id, args.workers, stats)
            except RuntimeError:
                # engine died mid-screen: rebuild (with backoff) and go on;
                # nothing was recorded, so nothing is lost
                stats["engine_restarts"] = stats.get("engine_restarts", 0) + 1
                engine.quit()
                engine = make_engine()
                continue
            if stem is None:
                stats["stem_rejects"] = stats.get("stem_rejects", 0) + 1
                continue
            moves, board, stem_hash = stem
            seen_out.write(f"{stem_hash:08x}\n")

            # game A: as reached; game B: color-mirrored. A mirror-symmetric
            # stem would make B the identical game — skip it (deterministic
            # engine, so it would be a byte-for-byte replay).
            games = [(None, moves, board)]
            mirrored = board.mirror()
            if mirrored.epd() != board.epd():
                games.append((mirrored.fen(), [], mirrored))
            else:
                stats["mirror_skips"] = stats.get("mirror_skips", 0) + 1

            for root_fen, init_moves, root_board in games:
                try:
                    positions = play_game(engine, tb, root_fen, init_moves,
                                          root_board, len(moves), args.nodes, stats)
                except RuntimeError:
                    # engine died mid-game: abandon the unrecorded game,
                    # rebuild the engine, keep the worker alive
                    stats["engine_restarts"] = stats.get("engine_restarts", 0) + 1
                    engine.quit()
                    engine = make_engine()
                    continue
                stats["games"] += 1
                for fen, ev, res in positions:
                    ev = max(-32000, min(32000, ev))
                    out.write(f"{fen} | {ev} | {res}\n")
                written += len(positions)

            now = time.time()
            if now - last_flush >= 30:
                out.flush()
                seen_out.flush()
                stats["positions"] = written
                stats["pos_per_sec"] = round(written / (now - t0), 2)
                with open(stats_path, "w") as f:
                    json.dump(stats, f, indent=1)
                last_flush = now

        out.flush()
    seen_out.close()
    stats["positions"] = written
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=1)
    if tb is not None:
        tb.close()
    engine.quit()


def main():
    ap = argparse.ArgumentParser(description="Self-play generator v2 (Session 2b)")
    ap.add_argument("--target", type=int, required=True, help="total positions")
    ap.add_argument("--output", required=True,
                    help="output prefix (shards: PREFIX.shardN.plain)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--nodes", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=20260712)
    args = ap.parse_args()

    disable_power_throttling()
    if os.environ.get("V2_HEADLESS"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    per_worker = args.target // args.workers
    print(f"engine : {ENGINE_PATH}")
    print(f"syzygy : {SYZYGY_PATH} ({'found' if os.path.isdir(SYZYGY_PATH) else 'MISSING'})")
    print(f"target : {args.target:,} positions ({per_worker:,} x {args.workers} workers)")
    print(f"nodes  : {args.nodes}/move   output: {args.output}.shard*.plain")

    procs = []
    for i in range(args.workers):
        p = mp.Process(target=worker_fn, args=(i, args, per_worker), daemon=True)
        p.start()
        procs.append(p)

    t0 = time.time()
    prev_alive = len(procs)
    try:
        while any(p.is_alive() for p in procs):
            time.sleep(30)
            alive = sum(1 for p in procs if p.is_alive())
            if alive < prev_alive:
                # a dead worker must not abort the fleet: log and continue
                # at N-1; the watchdog/resume path restores full strength
                print(f"WARNING: worker died ({alive}/{len(procs)} alive) — "
                      f"fleet continues", flush=True)
            prev_alive = alive
            total = 0
            for i in range(args.workers):
                sp = f"{args.output}.shard{i}.stats.json"
                if os.path.exists(sp):
                    try:
                        with open(sp) as f:
                            total += json.load(f).get("positions", 0)
                    except (json.JSONDecodeError, OSError):
                        pass
            el = time.time() - t0
            rate = total / el if el > 0 else 0
            eta_h = (args.target - total) / rate / 3600 if rate > 0 else float("inf")
            print(f"[{el/60:6.1f} min] ~{total:>11,} pos  {rate:7.1f} pos/s  ETA {eta_h:.1f} h",
                  flush=True)
    except KeyboardInterrupt:
        print("interrupted — workers are daemonic and will die; shards are resumable")
        sys.exit(1)

    for p in procs:
        p.join()
    print("done.")


if __name__ == "__main__":
    main()
