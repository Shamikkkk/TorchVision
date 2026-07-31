"""Regression proof for timed root-iteration completion.

This harness compares fixed-depth baseline/candidate transcripts, exercises the
two forced-mate incident positions, and runs fresh-process production-clock
repetitions at Threads=1 and Threads=2. It never queues ``quit`` until the
engine has returned ``bestmove``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import queue
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import chess


INCIDENT_FEN = "r4rk1/p4ppp/Q1p5/2qpp3/2P5/P6n/2P1B1PP/RR3K2 b - - 3 19"
INCIDENT_GO = "go wtime 137330 btime 190309 winc 0 binc 0"
INCIDENT_MATES = {"c5g1", "c5f2"}

PREVIOUS_FEN = "r4rk1/p4ppp/Q1p5/2qpp3/2P5/P7/2P1BnPP/RR4K1 b - - 1 18"
PREVIOUS_GO = "go wtime 139530 btime 197818 winc 0 binc 0"
PREVIOUS_MOVE = "f2h3"

MATE_THRESHOLD = 49_000
INFO_RE = re.compile(r"\bdepth\s+(\d+)\b.*\bscore\s+cp\s+(-?\d+)\b")

SUITE = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("after_1e4", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"),
    ("italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("french", "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3"),
    ("sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    ("kgambit", "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq - 0 2"),
    ("kid", "rnbqk2r/ppp1ppbp/3p1np1/8/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5"),
    ("dragon", "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"),
    (
        "greek_gift_attack",
        "r1bq1rk1/ppp2ppp/2n5/3pn3/1bB1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7",
    ),
    (
        "king_attack_pos",
        "r1b1k2r/ppp2ppp/2n5/3qp3/1bB5/2N2N2/PPPP1PPP/R1BQ1RK1 w kq - 0 7",
    ),
]


@dataclass
class SearchResult:
    label: str
    engine: str
    mode: str
    threads: int
    fen: str
    go: str
    elapsed_seconds: float
    info_lines: str
    depth: int | None
    score_cp: int | None
    bestmove: str
    san: str
    legal: bool
    checkmate_after_move: bool
    exit_code: int
    stderr: str

    def transcript(self) -> str:
        return f"{self.info_lines}\nbestmove {self.bestmove}\n"


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _pump_stdout(stream, output: queue.Queue[str | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            output.put(line.rstrip("\r\n"))
    finally:
        output.put(None)


def _pump_stderr(stream, output: list[str]) -> None:
    for line in iter(stream.readline, ""):
        output.append(line.rstrip("\r\n"))


def _stop_owned_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_search(
    engine: Path,
    label: str,
    fen: str,
    go_command: str,
    threads: int,
    no_nnue: bool,
    timeout_seconds: float,
) -> SearchResult:
    command = [str(engine.resolve())]
    mode = "PeSTO"
    if no_nnue:
        command.append("--no-nnue")
    else:
        mode = "NNUE"

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(engine.resolve().parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=creation_flags,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_queue: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(
        target=_pump_stdout, args=(process.stdout, stdout_queue), daemon=True
    )
    stderr_thread = threading.Thread(
        target=_pump_stderr, args=(process.stderr, stderr_lines), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    deadline = time.monotonic() + timeout_seconds

    def send(line: str) -> None:
        process.stdin.write(line + "\n")
        process.stdin.flush()

    def read_line() -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{label}: timed out waiting for engine output")
        try:
            line = stdout_queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(f"{label}: timed out waiting for engine output") from exc
        if line is None:
            raise RuntimeError(
                f"{label}: engine stdout closed before bestmove; exit={process.poll()}"
            )
        return line

    try:
        send("uci")
        while read_line() != "uciok":
            pass
        send(f"setoption name Threads value {threads}")
        send("isready")
        while read_line() != "readyok":
            pass
        send("ucinewgame")
        send(f"position fen {fen}")

        info_lines: list[str] = []
        started = time.monotonic()
        send(go_command)
        bestmove = ""
        while not bestmove:
            line = read_line()
            if line.startswith("info "):
                info_lines.append(line)
            elif line.startswith("bestmove "):
                parts = line.split()
                bestmove = parts[1] if len(parts) > 1 else ""
        elapsed = time.monotonic() - started

        # The task requires quit to be sent only after bestmove is received.
        send("quit")
        process.wait(timeout=max(1.0, deadline - time.monotonic()))
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
    except Exception:
        _stop_owned_process(process)
        raise

    depth = None
    score_cp = None
    for line in info_lines:
        match = INFO_RE.search(line)
        if match:
            depth = int(match.group(1))
            score_cp = int(match.group(2))

    board = chess.Board(fen)
    legal = False
    san = ""
    checkmate = False
    try:
        move = chess.Move.from_uci(bestmove)
        legal = move in board.legal_moves
        if legal:
            san = board.san(move)
            board.push(move)
            checkmate = board.is_checkmate()
    except ValueError:
        pass

    return SearchResult(
        label=label,
        engine=str(engine.resolve()),
        mode=mode,
        threads=threads,
        fen=fen,
        go=go_command,
        elapsed_seconds=round(elapsed, 6),
        info_lines=" || ".join(info_lines),
        depth=depth,
        score_cp=score_cp,
        bestmove=bestmove,
        san=san,
        legal=legal,
        checkmate_after_move=checkmate,
        exit_code=process.returncode,
        stderr=" | ".join(stderr_lines),
    )


def write_tsv(path: Path, rows: Iterable[SearchResult]) -> None:
    materialized = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(asdict(materialized[0]).keys()) if materialized else [],
            delimiter="\t",
        )
        if materialized:
            writer.writeheader()
            writer.writerows(asdict(row) for row in materialized)


def assert_search_ok(result: SearchResult) -> None:
    if result.exit_code != 0:
        raise AssertionError(f"{result.label}: engine exited {result.exit_code}")
    if not result.legal:
        raise AssertionError(
            f"{result.label}: illegal bestmove {result.bestmove!r}\n{result.info_lines}"
        )
    if result.depth is None or result.score_cp is None:
        raise AssertionError(
            f"{result.label}: missing parseable depth/score\n{result.info_lines}"
        )


def assert_incident_mate(result: SearchResult) -> None:
    assert_search_ok(result)
    if result.bestmove not in INCIDENT_MATES:
        raise AssertionError(
            f"{result.label}: non-mating incident move {result.bestmove} ({result.san})"
        )
    if not result.checkmate_after_move:
        raise AssertionError(
            f"{result.label}: {result.bestmove} is not immediate checkmate"
        )
    if result.score_cp is None or result.score_cp < MATE_THRESHOLD:
        raise AssertionError(
            f"{result.label}: mating move lacks mate-range score: {result.score_cp}"
        )


def assert_previous_mate(result: SearchResult) -> None:
    assert_search_ok(result)
    if result.bestmove != PREVIOUS_MOVE:
        raise AssertionError(
            f"{result.label}: expected {PREVIOUS_MOVE}, got {result.bestmove}"
        )
    if result.score_cp is None or result.score_cp < MATE_THRESHOLD:
        raise AssertionError(
            f"{result.label}: Nh3+ lacks mate-range score: {result.score_cp}"
        )


def verify_semantic_transcripts(
    baseline: Path,
    candidate: Path,
    timeout_seconds: float,
) -> list[SearchResult]:
    rows: list[SearchResult] = []
    for mode, no_nnue in (("NNUE", False), ("PeSTO", True)):
        for label, fen in SUITE:
            baseline_result = run_search(
                baseline,
                f"semantic_{mode}_{label}_baseline",
                fen,
                "go depth 8",
                1,
                no_nnue,
                timeout_seconds,
            )
            candidate_result = run_search(
                candidate,
                f"semantic_{mode}_{label}_candidate",
                fen,
                "go depth 8",
                1,
                no_nnue,
                timeout_seconds,
            )
            assert_search_ok(baseline_result)
            assert_search_ok(candidate_result)
            rows.extend((baseline_result, candidate_result))
            if baseline_result.transcript() != candidate_result.transcript():
                raise AssertionError(
                    f"{mode}/{label}: fixed-depth transcript changed\n"
                    f"baseline:\n{baseline_result.transcript()}"
                    f"candidate:\n{candidate_result.transcript()}"
                )
    return rows


def print_timed_row(repetition: int, result: SearchResult) -> None:
    print(
        f"rep={repetition:02d} threads={result.threads} "
        f"elapsed={result.elapsed_seconds:.3f}s depth={result.depth} "
        f"score={result.score_cp} bestmove={result.bestmove} san={result.san} "
        f"legal={result.legal} checkmate={result.checkmate_after_move}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--net", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()

    if args.repetitions < 1:
        raise ValueError("--repetitions must be positive")
    for path in (args.baseline, args.candidate, args.net):
        if not path.is_file():
            raise FileNotFoundError(path)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    print("Checking fixed-depth NNUE and PeSTO transcripts...", flush=True)
    semantic_rows = verify_semantic_transcripts(
        args.baseline.resolve(), args.candidate.resolve(), args.timeout_seconds
    )
    write_tsv(output_dir / "semantic_transcripts.tsv", semantic_rows)

    print("Checking incident FEN at fixed depths 1-12...", flush=True)
    fixed_rows: list[SearchResult] = []
    for depth in range(1, 13):
        result = run_search(
            args.candidate,
            f"incident_fixed_depth_{depth}",
            INCIDENT_FEN,
            f"go depth {depth}",
            1,
            False,
            args.timeout_seconds,
        )
        assert_incident_mate(result)
        fixed_rows.append(result)
    write_tsv(output_dir / "incident_fixed_depths.tsv", fixed_rows)

    timed_counts: dict[str, int] = {}
    for threads in (1, 2):
        path = output_dir / f"incident_threads{threads}.tsv"
        rows: list[SearchResult] = []
        print(
            f"Running {args.repetitions} fresh production-clock processes "
            f"at Threads={threads}...",
            flush=True,
        )
        for repetition in range(1, args.repetitions + 1):
            result = run_search(
                args.candidate,
                f"incident_threads{threads}_rep_{repetition:02d}",
                INCIDENT_FEN,
                INCIDENT_GO,
                threads,
                False,
                args.timeout_seconds,
            )
            rows.append(result)
            write_tsv(path, rows)
            print_timed_row(repetition, result)
            assert_incident_mate(result)
        timed_counts[str(threads)] = len(rows)

    print("Rechecking the preceding Nh3+ position...", flush=True)
    previous_rows = [
        run_search(
            args.candidate,
            "previous_fixed_depth_12",
            PREVIOUS_FEN,
            "go depth 12",
            1,
            False,
            args.timeout_seconds,
        ),
        run_search(
            args.candidate,
            "previous_original_clock",
            PREVIOUS_FEN,
            PREVIOUS_GO,
            2,
            False,
            args.timeout_seconds,
        ),
    ]
    for result in previous_rows:
        assert_previous_mate(result)
    write_tsv(output_dir / "previous_mate.tsv", previous_rows)

    summary = {
        "baseline": {
            "path": str(args.baseline.resolve()),
            "bytes": args.baseline.stat().st_size,
            "md5": digest(args.baseline, "md5"),
            "sha256": digest(args.baseline, "sha256"),
        },
        "candidate": {
            "path": str(args.candidate.resolve()),
            "bytes": args.candidate.stat().st_size,
            "md5": digest(args.candidate, "md5"),
            "sha256": digest(args.candidate, "sha256"),
        },
        "net": {
            "path": str(args.net.resolve()),
            "bytes": args.net.stat().st_size,
            "md5": digest(args.net, "md5"),
            "sha256": digest(args.net, "sha256"),
        },
        "semantic_positions_per_mode": len(SUITE),
        "semantic_transcripts_byte_identical": True,
        "incident_fixed_depths": list(range(1, 13)),
        "incident_repetitions": timed_counts,
        "incident_allowed_moves": sorted(INCIDENT_MATES),
        "previous_required_move": PREVIOUS_MOVE,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"PASS: reports written to {output_dir}", flush=True)


if __name__ == "__main__":
    main()
