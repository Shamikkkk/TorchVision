"""Generate the frozen 10,000-position SCReLU-512 inference proof set.

The output is deterministic and contains:
  - 8,000 natural v2-corpus positions, balanced by side to move
  - queen-promotion and underpromotion material states
  - unusual/multiple-queen material
  - low-material endgames
  - real positions selected for accumulator values near 0, near QA, below 0,
    and above QA
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

import chess
import numpy as np

from screlu512_reference import (
    CHAMPION_SHA256,
    QA,
    accumulators,
    load_champion_raw,
)

SEED = 20260725
NATURAL_PER_SIDE = 4_000
CONSTRUCTED_COUNTS = {
    "promotion_queen": 240,
    "underpromotion": 360,
    "multiple_queen_unusual": 400,
    "low_material_endgame": 500,
}
BOUNDARY_TARGETS = {
    "boundary_near_zero": (63, 62),
    "boundary_near_qa": (62, 63),
    "boundary_below_zero": (63, 62),
    "boundary_above_qa": (62, 63),
}
TOTAL_POSITIONS = 10_000


def corpus_fen(line: str) -> str | None:
    fen = line.split("|", 1)[0].strip()
    return fen or None


def add_piece(board: chess.Board, square: int, piece_type: int, color: bool) -> bool:
    if board.piece_at(square) is not None:
        return False
    if piece_type == chess.PAWN and chess.square_rank(square) in (0, 7):
        return False
    board.set_piece_at(square, chess.Piece(piece_type, color))
    return True


def random_square(rng: random.Random) -> int:
    return rng.randrange(64)


def place_kings(board: chess.Board, rng: random.Random) -> bool:
    white_king = random_square(rng)
    black_king = random_square(rng)
    if white_king == black_king:
        return False
    if chess.square_distance(white_king, black_king) <= 1:
        return False
    board.set_piece_at(white_king, chess.Piece(chess.KING, chess.WHITE))
    board.set_piece_at(black_king, chess.Piece(chess.KING, chess.BLACK))
    return True


def build_constructed(
    rng: random.Random,
    category: str,
    white_to_move: bool,
    serial: int,
) -> str:
    for _ in range(20_000):
        board = chess.Board.empty()
        if not place_kings(board, rng):
            continue

        if category in ("promotion_queen", "underpromotion"):
            promoted_color = chess.WHITE if serial % 2 == 0 else chess.BLACK
            promotion_rank = 7 if promoted_color == chess.WHITE else 0
            promotion_square = chess.square(rng.randrange(8), promotion_rank)
            if category == "promotion_queen":
                promoted_type = chess.QUEEN
            else:
                promoted_type = (chess.KNIGHT, chess.BISHOP, chess.ROOK)[serial % 3]
            if not add_piece(board, promotion_square, promoted_type, promoted_color):
                continue

            # Preserve an original queen in many promotion positions so the
            # frozen set also exercises promotion-created multiple queens.
            if serial % 2 == 0:
                for _ in range(20):
                    if add_piece(
                        board,
                        random_square(rng),
                        chess.QUEEN,
                        promoted_color,
                    ):
                        break
            extra_count = 1 + serial % 4
            for _ in range(extra_count):
                for _ in range(20):
                    if add_piece(
                        board,
                        random_square(rng),
                        rng.choice(
                            (
                                chess.PAWN,
                                chess.KNIGHT,
                                chess.BISHOP,
                                chess.ROOK,
                            )
                        ),
                        bool(rng.getrandbits(1)),
                    ):
                        break

        elif category == "multiple_queen_unusual":
            for color in (chess.WHITE, chess.BLACK):
                for _ in range(2 + (serial + int(color)) % 2):
                    for _ in range(30):
                        if add_piece(board, random_square(rng), chess.QUEEN, color):
                            break
            for _ in range(serial % 7):
                for _ in range(20):
                    if add_piece(
                        board,
                        random_square(rng),
                        rng.choice(
                            (
                                chess.KNIGHT,
                                chess.BISHOP,
                                chess.ROOK,
                                chess.QUEEN,
                            )
                        ),
                        bool(rng.getrandbits(1)),
                    ):
                        break

        elif category == "low_material_endgame":
            for _ in range(serial % 5):
                for _ in range(20):
                    if add_piece(
                        board,
                        random_square(rng),
                        rng.choice(
                            (
                                chess.PAWN,
                                chess.KNIGHT,
                                chess.BISHOP,
                                chess.ROOK,
                                chess.QUEEN,
                            )
                        ),
                        bool(rng.getrandbits(1)),
                    ):
                        break
        else:
            raise ValueError(f"unknown constructed category {category}")

        board.turn = white_to_move
        board.castling_rights = chess.BB_EMPTY
        board.ep_square = None
        board.halfmove_clock = serial % 100
        board.fullmove_number = 1 + serial % 200
        if board.is_valid():
            return board.fen()

    raise RuntimeError(f"could not construct valid {category} position {serial}")


def boundary_flags(values: np.ndarray) -> dict[str, bool]:
    return {
        "boundary_near_zero": bool(np.any((values >= -4) & (values <= 4))),
        "boundary_near_qa": bool(np.any((values >= QA - 4) & (values <= QA + 4))),
        "boundary_below_zero": bool(np.any(values < 0)),
        "boundary_above_qa": bool(np.any(values > QA)),
    }


def generate(raw_path: Path, corpus_path: Path, output_path: Path) -> None:
    rng = random.Random(SEED)
    net = load_champion_raw(raw_path)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    natural_remaining = {True: NATURAL_PER_SIDE, False: NATURAL_PER_SIDE}

    with corpus_path.open("r", encoding="utf-8") as corpus:
        for line in corpus:
            fen = corpus_fen(line)
            if fen is None or fen in seen:
                continue
            try:
                board = chess.Board(fen)
            except ValueError:
                continue
            if not board.is_valid() or natural_remaining[board.turn] == 0:
                continue
            entries.append(("natural_v2", fen))
            seen.add(fen)
            natural_remaining[board.turn] -= 1
            if not any(natural_remaining.values()):
                break

        if any(natural_remaining.values()):
            raise RuntimeError(f"not enough balanced natural positions: {natural_remaining}")

        for category, count in CONSTRUCTED_COUNTS.items():
            for serial in range(count):
                white_to_move = serial % 2 == 0
                while True:
                    fen = build_constructed(rng, category, white_to_move, serial)
                    if fen not in seen:
                        break
                entries.append((category, fen))
                seen.add(fen)

        remaining = {
            category: {True: white_count, False: black_count}
            for category, (white_count, black_count) in BOUNDARY_TARGETS.items()
        }
        priority = (
            "boundary_near_qa",
            "boundary_near_zero",
            "boundary_above_qa",
            "boundary_below_zero",
        )

        scanned = 0
        for line in corpus:
            scanned += 1
            fen = corpus_fen(line)
            if fen is None or fen in seen:
                continue
            try:
                board = chess.Board(fen)
            except ValueError:
                continue
            if not board.is_valid():
                continue

            white_acc, black_acc, _ = accumulators(net, fen)
            flags = boundary_flags(np.concatenate((white_acc, black_acc)))
            chosen = None
            for category in priority:
                if flags[category] and remaining[category][board.turn] > 0:
                    chosen = category
                    break
            if chosen is None:
                continue
            entries.append((chosen, fen))
            seen.add(fen)
            remaining[chosen][board.turn] -= 1
            if all(
                side_count == 0
                for category_counts in remaining.values()
                for side_count in category_counts.values()
            ):
                break
            if scanned >= 1_000_000:
                break

    if any(
        side_count
        for category_counts in remaining.values()
        for side_count in category_counts.values()
    ):
        raise RuntimeError(f"boundary quotas not filled after {scanned:,} scans: {remaining}")
    if len(entries) != TOTAL_POSITIONS:
        raise AssertionError(f"generated {len(entries):,}, expected {TOTAL_POSITIONS:,}")
    if len(seen) != len(entries):
        raise AssertionError("frozen set contains duplicate FENs")

    side_counts = Counter(fen.split()[1] for _, fen in entries)
    if side_counts != Counter({"w": TOTAL_POSITIONS // 2, "b": TOTAL_POSITIONS // 2}):
        raise AssertionError(f"side-to-move imbalance: {side_counts}")

    category_counts = Counter(category for category, _ in entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write("# Phase D SCReLU-512 integer-inference frozen set\n")
        output.write(f"# seed={SEED}\n")
        output.write(f"# champion_sha256={CHAMPION_SHA256}\n")
        output.write(f"# positions={len(entries)} white_stm=5000 black_stm=5000\n")
        output.write("# format: category<TAB>FEN\n")
        for category, fen in entries:
            output.write(f"{category}\t{fen}\n")

    print(f"Wrote {len(entries):,} unique positions to {output_path}")
    print(f"Side to move: {dict(sorted(side_counts.items()))}")
    for category, count in sorted(category_counts.items()):
        print(f"  {category}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw",
        type=Path,
        default=Path("C:/torch_data/phase_d_champion/pyro_v2_screlu512_raw.bin"),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("C:/torch_data/selfplay_v2_sf18.plain"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/scripts/nnue_screlu512_positions.tsv"),
    )
    args = parser.parse_args()
    generate(args.raw, args.corpus, args.output)


if __name__ == "__main__":
    main()
