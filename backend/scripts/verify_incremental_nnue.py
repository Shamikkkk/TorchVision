#!/usr/bin/env python3
"""Verify incremental SCReLU-512 lanes against Rust and independent Python full refreshes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import subprocess

import chess
import numpy as np

from screlu512_reference import (
    HIDDEN_SIZE,
    accumulators,
    evaluate,
    load_versioned_net,
    sha256_file,
)


MAGIC = b"NVS1"
HEADER = struct.Struct("<4sIII")
RECORD_PREFIX = struct.Struct("<IIH")
CP_PAIR = struct.Struct("<ii")
LANE_BYTES = HIDDEN_SIZE * 4


@dataclass(frozen=True)
class SequenceCase:
    case_id: str
    category: str
    initial_fen: str
    moves: tuple[str, ...]


def load_sequences(path: Path) -> list[SequenceCase]:
    cases: list[SequenceCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 4:
            raise ValueError(f"{path}:{line_number}: expected four tab-separated fields")
        case_id, category, initial_fen, moves_text = fields
        if not case_id or case_id in seen:
            raise ValueError(f"{path}:{line_number}: empty or duplicate case ID {case_id!r}")
        seen.add(case_id)
        board = chess.Board(initial_fen)
        if not board.is_valid():
            raise ValueError(f"{case_id}: invalid initial board: {initial_fen}")
        moves = tuple(moves_text.split())
        if not moves:
            raise ValueError(f"{case_id}: sequence contains no moves")
        cases.append(SequenceCase(case_id, category, initial_fen, moves))
    if not cases:
        raise ValueError("sequence corpus is empty")
    return cases


def read_exact(handle, size: int, description: str) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError(f"Rust output truncated while reading {description}: {len(data)} of {size} bytes")
    return data


def read_lanes(handle, description: str) -> np.ndarray:
    data = read_exact(handle, LANE_BYTES, description)
    return np.frombuffer(data, dtype="<i4", count=HIDDEN_SIZE).copy()


def mismatch_message(
    *,
    case: SequenceCase,
    board: chess.Board,
    prefix: list[str],
    ply: int,
    move: str,
    network_sha256: str,
    corpus_sha256: str,
    perspective: str,
    lane: int | None,
    expected_raw: int | None,
    actual_raw: int | None,
    expected_cp: int,
    actual_cp: int,
    source: str,
) -> str:
    return (
        "incremental NNUE mismatch\n"
        f"case_id={case.case_id}\n"
        f"category={case.category}\n"
        f"initial_fen={case.initial_fen}\n"
        f"current_fen={board.fen()}\n"
        f"move_prefix={' '.join(prefix)}\n"
        f"ply={ply}\n"
        f"move={move}\n"
        f"source={source}\n"
        f"perspective={perspective}\n"
        f"lane={lane}\n"
        f"expected_raw={expected_raw}\n"
        f"actual_raw={actual_raw}\n"
        f"expected_cp={expected_cp}\n"
        f"actual_cp={actual_cp}\n"
        f"network_sha256={network_sha256}\n"
        f"corpus_sha256={corpus_sha256}"
    )


def compare_lanes(
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    source: str,
    perspective: str,
    case: SequenceCase,
    board: chess.Board,
    prefix: list[str],
    ply: int,
    move: str,
    expected_cp: int,
    actual_cp: int,
    network_sha256: str,
    corpus_sha256: str,
) -> None:
    mismatch_indices = np.flatnonzero(actual != expected)
    if mismatch_indices.size:
        lane = int(mismatch_indices[0])
        raise AssertionError(
            mismatch_message(
                case=case,
                board=board,
                prefix=prefix,
                ply=ply,
                move=move,
                network_sha256=network_sha256,
                corpus_sha256=corpus_sha256,
                perspective=perspective,
                lane=lane,
                expected_raw=int(expected[lane]),
                actual_raw=int(actual[lane]),
                expected_cp=expected_cp,
                actual_cp=actual_cp,
                source=source,
            )
        )


def run_rust_verifier(args: argparse.Namespace) -> dict[str, object]:
    command = [
        str(args.verifier.resolve()),
        "--net",
        str(args.net.resolve()),
        "--sequences",
        str(args.sequences.resolve()),
        "--output",
        str(args.rust_output.resolve()),
    ]
    args.rust_output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=args.timeout_seconds,
        check=False,
    )
    stdout_path = args.report.parent / "rust_sequence_verifier.stdout.txt"
    stderr_path = args.report.parent / "rust_sequence_verifier.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Rust sequence verifier failed with exit {completed.returncode}: {completed.stderr.strip()}"
        )
    if completed.stdout.strip() or completed.stderr.strip():
        raise RuntimeError(
            "Rust sequence verifier emitted unexpected diagnostics despite exit 0: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
    }


def verify(args: argparse.Namespace) -> dict[str, object]:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    network_sha256 = sha256_file(args.net.resolve())
    corpus_sha256 = sha256_file(args.sequences.resolve())
    if args.expected_net_sha256 and network_sha256.lower() != args.expected_net_sha256.lower():
        raise ValueError(
            f"network SHA-256 {network_sha256} != expected {args.expected_net_sha256.lower()}"
        )
    if args.expected_corpus_sha256 and corpus_sha256.lower() != args.expected_corpus_sha256.lower():
        raise ValueError(
            f"corpus SHA-256 {corpus_sha256} != expected {args.expected_corpus_sha256.lower()}"
        )

    cases = load_sequences(args.sequences.resolve())
    expected_transitions = sum(len(case.moves) for case in cases)
    rust_run = run_rust_verifier(args)
    network = load_versioned_net(args.net.resolve())

    transition_count = 0
    null_count = 0
    null_sides = {"white": 0, "black": 0}
    child_sides = {"white": 0, "black": 0}

    with args.rust_output.resolve().open("rb") as handle:
        magic, case_count, rust_transitions, hidden = HEADER.unpack(
            read_exact(handle, HEADER.size, "sequence header")
        )
        if magic != MAGIC:
            raise ValueError(f"Rust output magic {magic!r}, expected {MAGIC!r}")
        if case_count != len(cases):
            raise ValueError(f"Rust case count {case_count}, expected {len(cases)}")
        if rust_transitions != expected_transitions:
            raise ValueError(
                f"Rust transition count {rust_transitions}, expected {expected_transitions}"
            )
        if hidden != HIDDEN_SIZE:
            raise ValueError(f"Rust hidden size {hidden}, expected {HIDDEN_SIZE}")

        for expected_case_index, case in enumerate(cases):
            board = chess.Board(case.initial_fen)
            prefix: list[str] = []
            for expected_ply, expected_move in enumerate(case.moves, 1):
                case_index, ply, move_length = RECORD_PREFIX.unpack(
                    read_exact(handle, RECORD_PREFIX.size, "record prefix")
                )
                move = read_exact(handle, move_length, "move token").decode("ascii")
                incremental_cp, full_cp = CP_PAIR.unpack(
                    read_exact(handle, CP_PAIR.size, "centipawn pair")
                )
                incremental_white = read_lanes(handle, "incremental white lanes")
                incremental_black = read_lanes(handle, "incremental black lanes")
                full_white = read_lanes(handle, "full white lanes")
                full_black = read_lanes(handle, "full black lanes")

                if case_index != expected_case_index or ply != expected_ply or move != expected_move:
                    raise AssertionError(
                        "Rust sequence ordering mismatch: "
                        f"expected case={expected_case_index} ply={expected_ply} move={expected_move}, "
                        f"got case={case_index} ply={ply} move={move}"
                    )

                if expected_move == "0000":
                    if board.is_check():
                        raise AssertionError(f"{case.case_id} ply {expected_ply}: null from check")
                    null_sides["white" if board.turn else "black"] += 1
                    null_count += 1
                    board.push(chess.Move.null())
                else:
                    move_object = chess.Move.from_uci(expected_move)
                    if move_object not in board.legal_moves:
                        raise AssertionError(
                            f"{case.case_id} ply {expected_ply}: illegal Python move "
                            f"{expected_move} from {board.fen()}"
                        )
                    board.push(move_object)
                    child_sides["white" if board.turn else "black"] += 1
                prefix.append(expected_move)

                python_white, python_black, white_to_move = accumulators(network, board.fen())
                python_cp = evaluate(network, python_white, python_black, white_to_move)

                comparisons = (
                    (incremental_white, python_white, "rust_incremental", "white", incremental_cp),
                    (incremental_black, python_black, "rust_incremental", "black", incremental_cp),
                    (full_white, python_white, "rust_full", "white", full_cp),
                    (full_black, python_black, "rust_full", "black", full_cp),
                )
                for actual, expected, source, perspective, actual_cp in comparisons:
                    compare_lanes(
                        actual,
                        expected,
                        source=source,
                        perspective=perspective,
                        case=case,
                        board=board,
                        prefix=prefix,
                        ply=expected_ply,
                        move=expected_move,
                        expected_cp=python_cp,
                        actual_cp=actual_cp,
                        network_sha256=network_sha256,
                        corpus_sha256=corpus_sha256,
                    )

                for source, actual_cp in (
                    ("rust_incremental", incremental_cp),
                    ("rust_full", full_cp),
                ):
                    if actual_cp != python_cp:
                        raise AssertionError(
                            mismatch_message(
                                case=case,
                                board=board,
                                prefix=prefix,
                                ply=expected_ply,
                                move=expected_move,
                                network_sha256=network_sha256,
                                corpus_sha256=corpus_sha256,
                                perspective="side_to_move",
                                lane=None,
                                expected_raw=None,
                                actual_raw=None,
                                expected_cp=python_cp,
                                actual_cp=actual_cp,
                                source=source,
                            )
                        )
                transition_count += 1

        trailing = handle.read(1)
        if trailing:
            raise ValueError("Rust output contains trailing bytes")

    report: dict[str, object] = {
        "status": "exact",
        "format": "pyro-incremental-nnue-verification-v1",
        "network_path": str(args.net.resolve()),
        "network_sha256": network_sha256,
        "corpus_path": str(args.sequences.resolve()),
        "corpus_sha256": corpus_sha256,
        "rust_output_path": str(args.rust_output.resolve()),
        "rust_output_bytes": args.rust_output.resolve().stat().st_size,
        "rust_output_sha256": sha256_file(args.rust_output.resolve()),
        "sequence_cases": len(cases),
        "transitions": transition_count,
        "legal_non_null_transitions": transition_count - null_count,
        "null_transitions": null_count,
        "null_source_side_to_move": null_sides,
        "non_null_child_side_to_move": child_sides,
        "lanes_per_transition": HIDDEN_SIZE * 2,
        "raw_lanes_proven_four_way_equal": transition_count * HIDDEN_SIZE * 2,
        "raw_value_comparisons": transition_count * HIDDEN_SIZE * 4,
        "cp_three_way_comparisons": transition_count,
        "mismatches": 0,
        "rust_incremental_vs_rust_full": "exact",
        "rust_incremental_vs_python_full": "exact",
        "rust_full_vs_python_full": "exact",
        "rust_run": rust_run,
    }
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--net", type=Path, required=True)
    parser.add_argument("--sequences", type=Path, required=True)
    parser.add_argument("--rust-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-net-sha256")
    parser.add_argument("--expected-corpus-sha256")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    return parser.parse_args()


def main() -> None:
    report = verify(parse_args())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
