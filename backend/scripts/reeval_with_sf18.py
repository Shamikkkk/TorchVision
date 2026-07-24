"""
Re-evaluate selfplay .plain positions using Stockfish 18.

Replaces PeSTO eval_cp_stm with SF18's evaluation at --depth / --movetime.
Game results (result_white) are preserved unchanged.

Input format:  FEN | eval_cp_stm | result_white
Output format: FEN | eval_cp_stm | result_white   (SF18 evals)

Architecture:
  - N worker processes, each keeps ONE persistent SF18 subprocess.
  - Main process feeds (idx, fen, result_white) via work_q.
  - Workers return (idx, eval_stm, fen, result_white, err) via result_q.
  - Main collects, sorts by idx, flushes every --chunk positions.
  - Checkpoint saved after each flush for --resume support.
"""

import argparse
import json
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

from scripts.generate_selfplay_v2 import disable_power_throttling

SF18_DEFAULT = r"C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"
INPUT_DEFAULT = "data/selfplay_d6_combined.plain"
OUTPUT_DEFAULT = "C:/torch_data/selfplay_sf18_d12.plain"
PROGRESS_DEFAULT = "C:/torch_data/reeval_progress.json"
LOG_DEFAULT = "C:/torch_data/reeval.log"


# ---------------------------------------------------------------------------
# Worker (runs in a subprocess, one persistent SF18 per worker)
# ---------------------------------------------------------------------------

def _launch_sf(sf_path):
    proc = subprocess.Popen(
        [sf_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
    )
    proc.stdin.write("uci\n"); proc.stdin.flush()
    for line in proc.stdout:
        if "uciok" in line:
            break
    proc.stdin.write("isready\n"); proc.stdin.flush()
    for line in proc.stdout:
        if "readyok" in line:
            break
    return proc


def _kill_sf(proc):
    try:
        proc.stdin.write("quit\n"); proc.stdin.flush()
        proc.wait(timeout=2)
    except Exception:
        try: proc.kill()
        except Exception: pass


def _eval_fen(proc, fen, depth, movetime):
    """Evaluate one FEN with an already-open SF process.

    Returns (eval_stm_cp: int, error: str|None).
    eval_stm_cp is from the side-to-move's perspective (positive = STM winning).
    """
    proc.stdin.write(f"position fen {fen}\n")
    proc.stdin.write(f"go depth {depth} movetime {movetime}\n")
    proc.stdin.flush()

    last_score = None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        if line == "":  # EOF — process died
            return None, "EOF (SF died)"
        if "score cp" in line:
            try:
                val = int(line.split("score cp")[1].split()[0])
                last_score = ("cp", val)
            except (ValueError, IndexError):
                pass
        elif "score mate" in line:
            try:
                val = int(line.split("score mate")[1].split()[0])
                last_score = ("mate", val)
            except (ValueError, IndexError):
                pass
        if line.startswith("bestmove"):
            break

    if last_score is None:
        return None, "no score before bestmove"

    kind, val = last_score
    if kind == "cp":
        return max(-30000, min(30000, val)), None
    # mate: positive N → STM mates in N, negative N → STM gets mated in |N|
    if val > 0:
        return 30000 - abs(val), None
    return -(30000 - abs(val)), None


def worker_fn(sf_path, depth, movetime, work_q, result_q):
    disable_power_throttling()
    if os.environ.get("V2_HEADLESS"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    proc = None

    def restart():
        nonlocal proc
        if proc is not None:
            _kill_sf(proc)
        proc = _launch_sf(sf_path)
        disable_power_throttling(proc.pid)

    restart()

    while True:
        item = work_q.get()
        if item is None:  # poison pill — shut down
            break

        idx, fen, result_white = item
        try:
            eval_stm, err = _eval_fen(proc, fen, depth, movetime)
            result_q.put((idx, eval_stm, fen, result_white, err))
            if err is not None:
                restart()
        except Exception as e:
            result_q.put((idx, None, fen, result_white, str(e)))
            try:
                restart()
            except Exception:
                pass

    _kill_sf(proc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def save_checkpoint(path, last_input_idx, total_written, total_errors, output_path, input_path):
    with open(path, "w") as f:
        json.dump({
            "last_input_idx": last_input_idx,
            "total_written": total_written,
            "total_errors": total_errors,
            "output_path": output_path,
            "input_path": input_path,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Re-evaluate .plain data with SF18")
    parser.add_argument("--input",    default=INPUT_DEFAULT)
    parser.add_argument("--output",   default=OUTPUT_DEFAULT)
    parser.add_argument("--sf18",     default=SF18_DEFAULT)
    parser.add_argument("--depth",    type=int, default=12)
    parser.add_argument("--movetime", type=int, default=1000)
    parser.add_argument("--workers",  type=int, default=6)
    parser.add_argument("--chunk",    type=int, default=100_000)
    parser.add_argument("--limit",    type=int, default=0, help="0 = process all positions")
    parser.add_argument("--resume",   action="store_true")
    parser.add_argument("--progress", default=PROGRESS_DEFAULT)
    args = parser.parse_args()

    disable_power_throttling()
    if os.environ.get("V2_HEADLESS"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(LOG_DEFAULT)), exist_ok=True)

    log_fh = open(LOG_DEFAULT, "a", encoding="utf-8")

    def log(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log_fh.write(line + "\n")
        log_fh.flush()

    log("=" * 60)
    log("reeval_with_sf18 started")
    log(f"  input    : {args.input}")
    log(f"  output   : {args.output}")
    log(f"  sf18     : {args.sf18}")
    log(f"  depth    : {args.depth}   movetime: {args.movetime}ms")
    log(f"  workers  : {args.workers}   chunk: {args.chunk:,}")
    log(f"  limit    : {args.limit if args.limit else 'all'}")

    # Resume state
    skip_lines = 0       # input lines already processed
    total_written = 0    # output lines already in file
    total_errors = 0

    if args.resume and os.path.exists(args.progress):
        with open(args.progress) as f:
            ckpt = json.load(f)
        skip_lines = ckpt["last_input_idx"] + 1
        total_written = ckpt["total_written"]
        total_errors = ckpt.get("total_errors", 0)
        log(f"  resume   : skipping {skip_lines:,} input lines ({total_written:,} already written)")
        # Reconcile: the checkpoint is written AFTER each flush, so a kill
        # between flush and checkpoint leaves the output AHEAD of the
        # checkpoint; appending blindly would duplicate lines. Truncate the
        # output back to exactly total_written lines before resuming.
        if not os.path.exists(args.output):
            sys.exit("resume: checkpoint exists but output file is missing — refusing")
        with open(args.output, "r+", encoding="utf-8") as f:
            pos = 0
            for i in range(total_written):
                if not f.readline():
                    sys.exit(f"resume: output has only {i:,} lines, checkpoint says "
                             f"{total_written:,} — corrupt state, refusing")
            pos = f.tell()
            extra = sum(1 for _ in f)
            if extra:
                log(f"  resume   : truncating {extra:,} unreconciled lines past checkpoint")
            f.seek(pos)
            f.truncate()
    elif args.resume:
        log("  resume   : no checkpoint found, starting fresh")

    out_mode = "a" if (args.resume and skip_lines > 0) else "w"

    with open(args.input, encoding="utf-8") as f:
        input_total = sum(1 for _ in f)
    log(f"  input has {input_total:,} lines")

    # Queues — bound work_q to avoid feeding too far ahead
    max_in_flight = args.workers * 16
    work_q   = mp.Queue(maxsize=max_in_flight)
    result_q = mp.Queue()

    procs = []
    for _ in range(args.workers):
        p = mp.Process(
            target=worker_fn,
            args=(args.sf18, args.depth, args.movetime, work_q, result_q),
            daemon=True,
        )
        p.start()
        procs.append(p)

    log(f"Started {args.workers} SF18 worker processes")

    t0 = time.time()
    t_last_report = t0
    last_reported_written = 0

    # Ordering buffer: idx → output_line_str | None (skipped)
    pending    = {}
    next_write = skip_lines    # next input idx to consume from pending
    chunk_buf  = []

    in_flight   = 0
    total_sent  = 0
    line_idx    = skip_lines   # tracks current input line number
    input_done  = False
    limit       = args.limit if args.limit > 0 else float("inf")

    def flush_chunk(fout):
        nonlocal total_written
        fout.write("".join(chunk_buf))
        fout.flush()
        total_written += len(chunk_buf)
        chunk_buf.clear()

    with open(args.input, "r", encoding="utf-8") as fin, \
         open(args.output, out_mode, encoding="utf-8") as fout:

        # Skip already-processed lines
        for _ in range(skip_lines):
            fin.readline()

        while True:
            did_work = False

            # ── Feed work queue ──────────────────────────────────────────
            while in_flight < max_in_flight and not input_done:
                if total_sent >= limit:
                    input_done = True
                    break
                raw = fin.readline()
                if not raw:
                    input_done = True
                    break
                raw = raw.strip()
                if not raw:
                    pending[line_idx] = None  # blank line — skip in output
                    line_idx += 1
                    continue
                parts = raw.split("|")
                if len(parts) != 3:
                    pending[line_idx] = None
                    total_errors += 1
                    line_idx += 1
                    continue
                fen = parts[0].strip()
                try:
                    result_white = float(parts[2].strip())
                except ValueError:
                    pending[line_idx] = None
                    total_errors += 1
                    line_idx += 1
                    continue
                try:
                    work_q.put_nowait((line_idx, fen, result_white))
                    in_flight += 1
                    total_sent += 1
                    line_idx += 1
                    did_work = True
                except Exception:
                    # Queue full — back off; don't advance line_idx
                    break

            # ── Drain result queue ───────────────────────────────────────
            while True:
                try:
                    idx, eval_stm, fen, result_white, err = result_q.get_nowait()
                    in_flight -= 1
                    did_work = True
                    if err is not None or eval_stm is None:
                        total_errors += 1
                        log(f"  SKIP idx={idx} err={err} fen={fen[:50]}")
                        pending[idx] = None
                    else:
                        pending[idx] = f"{fen} | {eval_stm} | {result_white}\n"
                except Exception:
                    break

            # ── Move ordered results into chunk buffer ───────────────────
            while next_write in pending:
                line = pending.pop(next_write)
                next_write += 1
                if line is not None:
                    chunk_buf.append(line)
                if len(chunk_buf) >= args.chunk:
                    flush_chunk(fout)
                    save_checkpoint(args.progress, next_write - 1, total_written,
                                    total_errors, args.output, args.input)

            # ── Progress report ──────────────────────────────────────────
            now = time.time()
            elapsed = now - t0
            new_since_report = total_written - last_reported_written
            if new_since_report >= 100_000 or (elapsed > 0 and now - t_last_report >= 300):
                if total_written > 0:
                    rate = total_written / elapsed if elapsed > 0 else 0
                    total_target = min(args.limit, input_total) if args.limit else input_total
                    remaining_pos = max(0, total_target - total_written)
                    eta_s = remaining_pos / rate if rate > 0 else 0
                    eta_str = (datetime.now() + timedelta(seconds=eta_s)).strftime("%Y-%m-%d %H:%M")
                    log(f"  {total_written:>10,} written  {rate:,.0f} pos/s  "
                        f"errors={total_errors}  ETA={eta_str}")
                    last_reported_written = total_written
                    t_last_report = now

            # ── Termination check ────────────────────────────────────────
            if input_done and in_flight == 0 and result_q.empty():
                # Drain any last pending
                while next_write in pending:
                    line = pending.pop(next_write)
                    next_write += 1
                    if line is not None:
                        chunk_buf.append(line)
                if chunk_buf:
                    flush_chunk(fout)
                    save_checkpoint(args.progress, next_write - 1, total_written,
                                    total_errors, args.output, args.input)
                break

            if not did_work:
                time.sleep(0.005)

    # Shut down workers
    for _ in procs:
        work_q.put(None)
    for p in procs:
        p.join(timeout=15)

    elapsed = time.time() - t0
    rate = total_written / elapsed if elapsed > 0 else 0
    log(f"Finished: {total_written:,} written, {total_errors:,} errors, "
        f"{elapsed:.1f}s ({rate:,.0f} pos/s)")

    completion_pct = (total_written / total_sent * 100) if total_sent > 0 else 0
    log(f"Completion: {completion_pct:.2f}% ({total_written:,} / {total_sent:,})")
    log_fh.close()

    if total_sent > 0 and completion_pct < 99.0:
        print(f"ERROR: only {completion_pct:.2f}% completed (<99%)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
