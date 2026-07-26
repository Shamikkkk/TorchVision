"""Exhaustive Rust-vs-Python integer proof for the Phase D SCReLU-512 net."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

import chess
import numpy as np

from screlu512_reference import (
    CHAMPION_SHA256,
    HEADER,
    HIDDEN_SIZE,
    QA,
    accumulators,
    evaluate,
    load_versioned_net,
    screlu_square,
    sha256_file,
    write_versioned_net,
)

RUST_MAGIC = b"NVR1"
RUST_HEADER = struct.Struct("<4sII")
RUST_RECORD = np.dtype(
    [
        ("cp", "<i4"),
        ("white", "<i4", (HIDDEN_SIZE,)),
        ("black", "<i4", (HIDDEN_SIZE,)),
    ]
)
BOUNDARY_CASES = (
    (-100_000, 0),
    (-1, 0),
    (0, 0),
    (1, 1),
    (QA - 1, (QA - 1) ** 2),
    (QA, QA**2),
    (QA + 1, QA**2),
    (100_000, QA**2),
)


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_positions(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        try:
            category, fen = line.split("\t", 1)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: expected category<TAB>FEN") from exc
        entries.append((category, fen))
    if len(entries) < 10_000:
        raise ValueError(f"frozen set has {len(entries):,} positions; require >=10,000")
    return entries


def load_rust_results(path: Path, expected_count: int) -> np.ndarray:
    data = path.read_bytes()
    if len(data) < RUST_HEADER.size:
        raise ValueError("Rust result file is truncated before header")
    magic, count, hidden = RUST_HEADER.unpack_from(data)
    if magic != RUST_MAGIC:
        raise ValueError(f"Rust result magic {magic!r}, expected {RUST_MAGIC!r}")
    if count != expected_count:
        raise ValueError(f"Rust result count {count}, expected {expected_count}")
    if hidden != HIDDEN_SIZE:
        raise ValueError(f"Rust hidden size {hidden}, expected {HIDDEN_SIZE}")
    expected_bytes = RUST_HEADER.size + expected_count * RUST_RECORD.itemsize
    if len(data) != expected_bytes:
        raise ValueError(f"Rust result bytes {len(data)}, expected {expected_bytes}")
    return np.frombuffer(data, dtype=RUST_RECORD, count=expected_count, offset=RUST_HEADER.size)


def assert_frozen_set_coverage(entries: list[tuple[str, str]]) -> dict[str, object]:
    categories = Counter(category for category, _ in entries)
    sides = Counter(fen.split()[1] for _, fen in entries)
    required = {
        "natural_v2",
        "promotion_queen",
        "underpromotion",
        "multiple_queen_unusual",
        "low_material_endgame",
        "boundary_near_zero",
        "boundary_near_qa",
        "boundary_below_zero",
        "boundary_above_qa",
    }
    missing = sorted(required - categories.keys())
    if missing:
        raise ValueError(f"frozen set missing categories: {missing}")
    if sides["w"] != sides["b"]:
        raise ValueError(f"side-to-move set is not balanced: {dict(sides)}")
    if len({fen for _, fen in entries}) != len(entries):
        raise ValueError("frozen set contains duplicate FENs")

    underpromotion_types = Counter()
    for index, (category, fen) in enumerate(entries):
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError(f"frozen set case {index} is not a valid board: {fen}")

        back_rank_pieces = [
            piece
            for square, piece in board.piece_map().items()
            if chess.square_rank(square) in (0, 7)
        ]
        if category == "promotion_queen" and not any(
            piece.piece_type == chess.QUEEN for piece in back_rank_pieces
        ):
            raise ValueError(f"queen-promotion case lacks a back-rank queen: {fen}")
        if category == "underpromotion":
            present_types = {
                piece.piece_type
                for piece in back_rank_pieces
                if piece.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK)
            }
            if not present_types:
                raise ValueError(f"underpromotion case lacks a back-rank N/B/R: {fen}")
            underpromotion_types.update(present_types)
        if category == "multiple_queen_unusual":
            queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(
                board.pieces(chess.QUEEN, chess.BLACK)
            )
            if queens < 3:
                raise ValueError(f"multiple-queen case has only {queens} queens: {fen}")
        if category == "low_material_endgame" and len(board.piece_map()) > 6:
            raise ValueError(f"low-material case has over six pieces: {fen}")

    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK):
        if underpromotion_types[piece_type] == 0:
            raise ValueError(
                f"underpromotion set does not cover {chess.piece_name(piece_type)}"
            )
    return {
        "categories": dict(sorted(categories.items())),
        "side_to_move": dict(sorted(sides.items())),
        "underpromotion_piece_coverage": {
            chess.piece_name(piece_type): underpromotion_types[piece_type]
            for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK)
        },
    }


def verify(args: argparse.Namespace) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    protected = (
        root / "engine" / "pyro.nnue",
        root / "engine" / "target" / "release" / "pyro.nnue",
    )
    raw_path = args.raw.resolve()
    net_path = args.net.resolve()
    if sha256_file(raw_path) != CHAMPION_SHA256:
        raise ValueError("raw input is not the staged Phase D champion")

    # Independently quantize raw floats and write the explicit v2 header.
    python_net = write_versioned_net(raw_path, net_path, protected_paths=protected)
    serialized_net = load_versioned_net(net_path)
    for field in ("ft_weights", "ft_bias", "out_weights"):
        if not np.array_equal(
            getattr(python_net, field), getattr(serialized_net, field)
        ):
            raise AssertionError(f"serialized net differs in {field}")
    if python_net.out_bias != serialized_net.out_bias:
        raise AssertionError("serialized net differs in out_bias")

    bullet_quantised_report = None
    if args.bullet_quantised is not None:
        bullet_path = args.bullet_quantised.resolve()
        bullet_bytes = bullet_path.read_bytes()
        versioned_payload = net_path.read_bytes()[HEADER.size :]
        if bullet_bytes[: len(versioned_payload)] != versioned_payload:
            raise AssertionError(
                "v2 payload differs from Bullet's original quantised.bin"
            )
        bullet_padding = bullet_bytes[len(versioned_payload) :]
        expected_padding = (b"bullet" * 11)[: len(bullet_padding)]
        if bullet_padding != expected_padding:
            raise AssertionError(
                f"unexpected Bullet alignment padding: {bullet_padding!r}"
            )
        bullet_quantised_report = {
            "path": str(bullet_path),
            "sha256": sha256_file(bullet_path),
            "bytes": len(bullet_bytes),
            "v2_payload_bytes": len(versioned_payload),
            "payload_sha256": hashlib.sha256(versioned_payload).hexdigest(),
            "prefix_byte_identical": True,
            "alignment_padding_bytes": len(bullet_padding),
        }

    entries = load_positions(args.positions)
    coverage = assert_frozen_set_coverage(entries)

    args.rust_output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.rust_verifier.resolve()),
        "--net",
        str(net_path),
        "--positions",
        str(args.positions.resolve()),
        "--output",
        str(args.rust_output.resolve()),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Rust verifier failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    rust = load_rust_results(args.rust_output, len(entries))

    boundary_passed = 0
    for value, expected in BOUNDARY_CASES:
        actual = screlu_square(value)
        if actual != expected:
            raise AssertionError(
                f"Python SCReLU boundary {value}: {actual}, expected {expected}"
            )
        boundary_passed += 1

    exact_matches = 0
    mismatches: list[dict[str, object]] = []
    actual_boundary_counts = Counter()
    for index, (category, fen) in enumerate(entries):
        white, black, white_to_move = accumulators(python_net, fen)
        python_cp = evaluate(python_net, white, black, white_to_move)
        rust_white = rust[index]["white"]
        rust_black = rust[index]["black"]
        rust_cp = int(rust[index]["cp"])

        all_values = np.concatenate((white, black))
        if np.any((all_values >= -4) & (all_values <= 4)):
            actual_boundary_counts["near_zero"] += 1
        if np.any((all_values >= QA - 4) & (all_values <= QA + 4)):
            actual_boundary_counts["near_qa"] += 1
        if np.any(all_values < 0):
            actual_boundary_counts["below_zero"] += 1
        if np.any(all_values > QA):
            actual_boundary_counts["above_qa"] += 1

        boundary_requirements = {
            "boundary_near_zero": np.any(
                (all_values >= -4) & (all_values <= 4)
            ),
            "boundary_near_qa": np.any(
                (all_values >= QA - 4) & (all_values <= QA + 4)
            ),
            "boundary_below_zero": np.any(all_values < 0),
            "boundary_above_qa": np.any(all_values > QA),
        }
        if category in boundary_requirements and not boundary_requirements[category]:
            raise AssertionError(
                f"frozen boundary label is not satisfied: {category}: {fen}"
            )

        white_match = np.array_equal(white, rust_white)
        black_match = np.array_equal(black, rust_black)
        cp_match = python_cp == rust_cp
        if white_match and black_match and cp_match:
            exact_matches += 1
            continue

        mismatch: dict[str, object] = {
            "index": index,
            "category": category,
            "fen": fen,
            "python_cp": python_cp,
            "rust_cp": rust_cp,
        }
        if not white_match:
            indices = np.flatnonzero(white != rust_white)
            mismatch["white_accumulator_mismatch_count"] = int(indices.size)
            mismatch["white_first_mismatch"] = (
                int(indices[0]),
                int(white[indices[0]]),
                int(rust_white[indices[0]]),
            )
        if not black_match:
            indices = np.flatnonzero(black != rust_black)
            mismatch["black_accumulator_mismatch_count"] = int(indices.size)
            mismatch["black_first_mismatch"] = (
                int(indices[0]),
                int(black[indices[0]]),
                int(rust_black[indices[0]]),
            )
        mismatches.append(mismatch)

    report: dict[str, object] = {
        "raw_path": str(raw_path),
        "raw_sha256": sha256_file(raw_path),
        "versioned_net_path": str(net_path),
        "versioned_net_bytes": net_path.stat().st_size,
        "versioned_net_sha256": sha256_file(net_path),
        "versioned_net_md5": md5_file(net_path),
        "bullet_quantised_comparison": bullet_quantised_report,
        "positions_path": str(args.positions.resolve()),
        "positions_sha256": sha256_file(args.positions.resolve()),
        "total_cases": len(entries),
        "exact_matches": exact_matches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "coverage": coverage,
        "actual_accumulator_boundary_case_counts": dict(
            sorted(actual_boundary_counts.items())
        ),
        "synthetic_boundary_tests": {
            "passed": boundary_passed,
            "total": len(BOUNDARY_CASES),
            "values": [value for value, _ in BOUNDARY_CASES],
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=== SCReLU-512 RUST-vs-PYTHON INTEGER AGREEMENT ===")
    print(f"Raw champion SHA-256 : {report['raw_sha256']}")
    print(f"Versioned net        : {net_path}")
    print(f"Versioned net SHA-256: {report['versioned_net_sha256']}")
    if bullet_quantised_report is not None:
        print(
            "Bullet payload       : byte-identical "
            f"({bullet_quantised_report['v2_payload_bytes']:,} bytes; "
            f"{bullet_quantised_report['alignment_padding_bytes']} padding bytes excluded)"
        )
    print(f"Frozen positions     : {len(entries):,}")
    print(f"Exact matches        : {exact_matches:,}/{len(entries):,}")
    print(f"Mismatches           : {len(mismatches):,}")
    print(
        "Synthetic boundaries : "
        f"{boundary_passed}/{len(BOUNDARY_CASES)} "
        f"{[value for value, _ in BOUNDARY_CASES]}"
    )
    print(f"Actual boundaries    : {dict(sorted(actual_boundary_counts.items()))}")
    print(f"Coverage             : {coverage}")
    print(f"Report               : {args.report}")

    if mismatches:
        print("\nEVERY MISMATCH:")
        for mismatch in mismatches:
            print(json.dumps(mismatch, sort_keys=True))
        raise AssertionError(
            f"{len(mismatches):,} Rust/Python mismatches; stop and diagnose"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw",
        type=Path,
        default=Path("C:/torch_data/phase_d_champion/pyro_v2_screlu512_raw.bin"),
    )
    parser.add_argument("--net", type=Path, required=True)
    parser.add_argument(
        "--positions",
        type=Path,
        default=Path("backend/scripts/nnue_screlu512_positions.tsv"),
    )
    parser.add_argument("--rust-verifier", type=Path, required=True)
    parser.add_argument("--rust-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--bullet-quantised",
        type=Path,
        help="optional original Bullet quantised.bin for byte-exact payload proof",
    )
    args = parser.parse_args()
    try:
        verify(args)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
