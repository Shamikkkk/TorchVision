"""Byte-identical --no-nnue bestmove proof for baseline vs SCReLU branch."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bestmove(engine: Path, fen: str, depth: int) -> str:
    command = (
        "uci\n"
        "setoption name Threads value 1\n"
        "isready\n"
        f"position fen {fen}\n"
        f"go depth {depth}\n"
        "quit\n"
    )
    result = subprocess.run(
        [str(engine.resolve()), "--no-nnue"],
        input=command,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{engine} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    moves = [
        line.split(maxsplit=1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("bestmove ")
    ]
    if len(moves) != 1:
        raise RuntimeError(f"{engine}: expected one bestmove, got {moves!r}")
    return moves[0]


def transcript(engine: Path, depth: int) -> bytes:
    rows = []
    for label, fen in SUITE:
        rows.append(f"{label}\t{bestmove(engine, fen, depth)}\n")
    return "".join(rows).encode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=8)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline_bytes = transcript(args.baseline, args.depth)
    candidate_bytes = transcript(args.candidate, args.depth)
    baseline_path = args.output_dir / "baseline_no_nnue.tsv"
    candidate_path = args.output_dir / "candidate_no_nnue.tsv"
    baseline_path.write_bytes(baseline_bytes)
    candidate_path.write_bytes(candidate_bytes)

    identical = baseline_bytes == candidate_bytes
    report = {
        "baseline_binary": str(args.baseline.resolve()),
        "baseline_binary_sha256": sha256(args.baseline),
        "candidate_binary": str(args.candidate.resolve()),
        "candidate_binary_sha256": sha256(args.candidate),
        "threads": 1,
        "depth": args.depth,
        "positions": len(SUITE),
        "baseline_transcript": str(baseline_path.resolve()),
        "candidate_transcript": str(candidate_path.resolve()),
        "baseline_transcript_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "candidate_transcript_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "byte_identical": identical,
    }
    report_path = args.output_dir / "no_nnue_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=== BASELINE --no-nnue TRANSCRIPT ===")
    print(baseline_bytes.decode("ascii"), end="")
    print("=== CANDIDATE --no-nnue TRANSCRIPT ===")
    print(candidate_bytes.decode("ascii"), end="")
    print(f"Baseline SHA-256 : {report['baseline_transcript_sha256']}")
    print(f"Candidate SHA-256: {report['candidate_transcript_sha256']}")
    print(f"Byte-identical   : {identical}")
    print(f"Report           : {report_path}")
    if not identical:
        raise SystemExit("FAIL: --no-nnue transcripts differ")


if __name__ == "__main__":
    main()
