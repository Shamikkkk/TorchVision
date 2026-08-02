#!/usr/bin/env python3
"""Generate deterministic legal move sequences for Ticket #1 NNUE validation."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

import chess


SEED = 20260802
DEFAULT_UNIQUE_POSITIONS = 10_000
DEFAULT_NULL_TRANSITIONS = 128
FULL_QUOTA = 100
MAX_SEQUENCE_PLIES = 128
MIN_LONG_SEQUENCE_PLIES = 80
MIN_LONG_SEQUENCES = 20

SemanticPositionKey = tuple[str, bool, int, int | None]


def canonical_position_key(board: chess.Board) -> SemanticPositionKey:
    """Return the rule-relevant position state, excluding both move clocks."""
    return (
        board.board_fen(),
        board.turn,
        board.castling_rights,
        board.ep_square,
    )


def canonical_representative(
    board: chess.Board, *, context: str
) -> tuple[SemanticPositionKey, str]:
    """Return an exact-FEN representative proven to round-trip to its key."""
    key = canonical_position_key(board)
    representative_fen = board.fen(en_passant="fen")
    reconstructed_key = canonical_position_key(chess.Board(representative_fen))
    if reconstructed_key != key:
        side_to_move = "white" if board.turn else "black"
        raise ValueError(
            f"{context}: canonical representative round-trip mismatch; "
            f"side_to_move={side_to_move}; original_key={key!r}; "
            f"representative_fen={representative_fen!r}; "
            f"reconstructed_key={reconstructed_key!r}"
        )
    return key, representative_fen


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fixtures(path: Path) -> list[tuple[str, str, str, list[str]]]:
    cases: list[tuple[str, str, str, list[str]]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 4:
            raise ValueError(f"fixture line {line_number}: expected four tab-separated fields")
        case_id, category, fen, moves_text = fields
        if not case_id or case_id in seen:
            raise ValueError(f"fixture line {line_number}: empty or duplicate case ID {case_id!r}")
        seen.add(case_id)
        moves = moves_text.split()
        if not moves:
            raise ValueError(f"fixture line {line_number}: no moves")
        replay_case(case_id, fen, moves)
        cases.append((case_id, category, fen, moves))
    if not cases:
        raise ValueError("fixture set is empty")
    return cases


def replay_case(case_id: str, initial_fen: str, moves: list[str]) -> list[chess.Board]:
    board = chess.Board(initial_fen)
    children: list[chess.Board] = []
    for ply, token in enumerate(moves, 1):
        if token == "0000":
            if board.is_check():
                raise ValueError(f"{case_id} ply {ply}: null transition from check")
            board.push(chess.Move.null())
        else:
            try:
                move = chess.Move.from_uci(token)
            except ValueError as error:
                raise ValueError(f"{case_id} ply {ply}: malformed move {token}") from error
            if move not in board.legal_moves:
                raise ValueError(
                    f"{case_id} ply {ply}: illegal move {token} from {board.fen()}"
                )
            board.push(move)
        children.append(board.copy(stack=False))
    return children


def move_category(board: chess.Board, move: chess.Move) -> str:
    if move == chess.Move.null():
        return "null"
    moving_piece = board.piece_at(move.from_square)
    if moving_piece is None:
        raise AssertionError(f"no piece on {chess.square_name(move.from_square)}")
    if board.is_castling(move):
        return "castling"
    if move.promotion is not None:
        return "promotion_capture" if board.is_capture(move) else "promotion"
    if board.is_en_passant(move):
        return "en_passant"
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured is not None and captured.piece_type == chess.ROOK and move.to_square in (
            chess.A1,
            chess.H1,
            chess.A8,
            chess.H8,
        ):
            return "corner_rook_capture"
        return "ordinary_capture"
    if moving_piece.piece_type == chess.PAWN:
        if abs(move.to_square - move.from_square) == 16:
            return "double_pawn_push"
        return "quiet_pawn"
    if moving_piece.piece_type == chess.KING:
        return "quiet_king"
    if moving_piece.piece_type == chess.ROOK:
        return "quiet_rook"
    return "quiet_non_pawn"


def is_quiet_category(category: str) -> bool:
    return category in {"quiet_pawn", "quiet_king", "quiet_rook", "quiet_non_pawn"}


def choose_move(
    board: chess.Board,
    legal_moves: list[chess.Move],
    rng: random.Random,
    counts: Counter[str],
    quota: int,
) -> chess.Move:
    categorized = [(move, move_category(board, move)) for move in legal_moves]
    priorities: list[tuple[str, object]] = [
        ("double_pawn_push", lambda category: category == "double_pawn_push"),
        ("ordinary_capture", lambda category: category == "ordinary_capture"),
        ("quiet", is_quiet_category),
    ]
    for quota_name, predicate in priorities:
        if counts[quota_name] < quota:
            eligible = [move for move, category in categorized if predicate(category)]
            if eligible:
                return eligible[rng.randrange(len(eligible))]
    return legal_moves[rng.randrange(len(legal_moves))]


def add_case_statistics(
    case_id: str,
    initial_fen: str,
    moves: list[str],
    canonical_positions: set[SemanticPositionKey],
    counts: Counter[str],
    child_sides: Counter[str],
    null_sources: dict[bool, dict[SemanticPositionKey, str]],
    selected_null_sources: dict[bool, set[SemanticPositionKey]],
) -> None:
    board = chess.Board(initial_fen)
    for ply, token in enumerate(moves, 1):
        if token == "0000":
            source_key, representative_fen = canonical_representative(
                board, context=f"{case_id} ply {ply} selected null source"
            )
            selected_for_side = selected_null_sources[board.turn]
            if source_key in selected_for_side:
                raise ValueError(
                    f"{case_id} ply {ply}: duplicate canonical null source {source_key!r}"
                )
            selected_for_side.add(source_key)
            null_sources[board.turn].setdefault(source_key, representative_fen)
            category = "null"
            counts[f"null_source_{'white' if board.turn else 'black'}"] += 1
            board.push(chess.Move.null())
        else:
            move = chess.Move.from_uci(token)
            if move not in board.legal_moves:
                raise ValueError(f"{case_id} ply {ply}: illegal move {token}")
            category = move_category(board, move)
            board.push(move)
            canonical_positions.add(canonical_position_key(board))
            child_sides["white" if board.turn else "black"] += 1
            if not board.is_check():
                source_key, representative_fen = canonical_representative(
                    board, context=f"{case_id} ply {ply} candidate null source"
                )
                null_sources[board.turn].setdefault(source_key, representative_fen)
        counts[category] += 1
        if is_quiet_category(category):
            counts["quiet"] += 1


def generate(args: argparse.Namespace) -> dict[str, object]:
    if args.null_transitions <= 0 or args.null_transitions % 2:
        raise ValueError("--null-transitions must be a positive even number")
    if args.target_unique <= 0:
        raise ValueError("--target-unique must be positive")

    fixtures_path = args.fixtures.resolve()
    fixture_cases = load_fixtures(fixtures_path)
    cases: list[tuple[str, str, str, list[str]]] = list(fixture_cases)
    case_ids = {case[0] for case in cases}
    canonical_positions: set[SemanticPositionKey] = set()
    counts: Counter[str] = Counter()
    child_sides: Counter[str] = Counter()
    null_sources: dict[bool, dict[SemanticPositionKey, str]] = {
        chess.WHITE: {},
        chess.BLACK: {},
    }
    selected_null_sources: dict[bool, set[SemanticPositionKey]] = {
        chess.WHITE: set(),
        chess.BLACK: set(),
    }

    for case_id, _category, fen, moves in fixture_cases:
        add_case_statistics(
            case_id,
            fen,
            moves,
            canonical_positions,
            counts,
            child_sides,
            null_sources,
            selected_null_sources,
        )

    quota = 1 if args.smoke else FULL_QUOTA
    long_required = 1 if args.smoke else MIN_LONG_SEQUENCES
    rng = random.Random(args.seed)
    game_index = 0
    long_sequences = 0

    def quotas_met() -> bool:
        return (
            counts["quiet"] >= quota
            and counts["double_pawn_push"] >= quota
            and counts["ordinary_capture"] >= quota
            and long_sequences >= long_required
        )

    while len(canonical_positions) < args.target_unique or not quotas_met():
        game_index += 1
        if game_index > 20_000:
            raise RuntimeError("generation exhausted 20,000 games before meeting quotas")
        board = chess.Board()
        moves: list[str] = []
        local_counts = counts.copy()
        for _ply in range(MAX_SEQUENCE_PLIES):
            legal = sorted(board.legal_moves, key=lambda move: move.uci())
            if not legal:
                break
            move = choose_move(board, legal, rng, local_counts, quota)
            category = move_category(board, move)
            moves.append(move.uci())
            local_counts[category] += 1
            if is_quiet_category(category):
                local_counts["quiet"] += 1
            board.push(move)

        # Even-length sequences keep child side-to-move accounting balanced.
        # Discard an odd terminal sequence instead of introducing a hidden bias.
        if not moves or len(moves) % 2:
            continue

        case_id = f"generated_{game_index:05d}"
        if case_id in case_ids:
            raise AssertionError(f"duplicate generated case ID {case_id}")
        case_ids.add(case_id)
        cases.append((case_id, "generated_legal_game", chess.STARTING_FEN, moves))
        add_case_statistics(
            case_id,
            chess.STARTING_FEN,
            moves,
            canonical_positions,
            counts,
            child_sides,
            null_sources,
            selected_null_sources,
        )
        if len(moves) >= MIN_LONG_SEQUENCE_PLIES:
            long_sequences += 1

    # Correct the small fixture-side imbalance with deterministic legal
    # one-ply cases. Generated games above are all even length.
    balance_index = 0
    while child_sides["white"] != child_sides["black"]:
        balance_index += 1
        if child_sides["white"] < child_sides["black"]:
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
            moves = ["e7e5"]
        else:
            fen = chess.STARTING_FEN
            moves = ["e2e4"]
        case_id = f"balance_{balance_index:03d}"
        cases.append((case_id, "side_to_move_balance", fen, moves))
        add_case_statistics(
            case_id,
            fen,
            moves,
            canonical_positions,
            counts,
            child_sides,
            null_sources,
            selected_null_sources,
        )

    null_per_side = args.null_transitions // 2
    existing_white = counts["null_source_white"]
    existing_black = counts["null_source_black"]
    if existing_white > null_per_side or existing_black > null_per_side:
        raise ValueError("curated fixture contains more null transitions than requested")

    for side, side_name, existing in (
        (chess.WHITE, "white", existing_white),
        (chess.BLACK, "black", existing_black),
    ):
        needed = null_per_side - existing
        sources = [
            (key, fen)
            for key, fen in null_sources[side].items()
            if key not in selected_null_sources[side]
        ]
        if len(sources) < needed:
            raise RuntimeError(
                f"only {len(sources)} safe {side_name}-to-move null sources; need {needed}"
            )
        for index, (_key, fen) in enumerate(sources[:needed], 1):
            case_id = f"generated_null_{side_name}_{index:03d}"
            cases.append((case_id, f"null_{side_name}", fen, ["0000"]))
            add_case_statistics(
                case_id,
                fen,
                ["0000"],
                canonical_positions,
                counts,
                child_sides,
                null_sources,
                selected_null_sources,
            )

    if len(canonical_positions) < args.target_unique:
        raise AssertionError("unique canonical semantic non-null position quota was not met")
    if child_sides["white"] != child_sides["black"]:
        raise AssertionError(f"child side-to-move counts are not balanced: {dict(child_sides)}")
    if counts["null"] != args.null_transitions:
        raise AssertionError(
            f"expected {args.null_transitions} null transitions, got {counts['null']}"
        )
    if counts["null_source_white"] != null_per_side or counts["null_source_black"] != null_per_side:
        raise AssertionError("null source sides are not exactly balanced")
    unique_null_white = len(selected_null_sources[chess.WHITE])
    unique_null_black = len(selected_null_sources[chess.BLACK])
    unique_null_total = unique_null_white + unique_null_black
    if unique_null_white != null_per_side or unique_null_black != null_per_side:
        raise AssertionError(
            "canonical null sources are not exactly balanced and unique: "
            f"white={unique_null_white} black={unique_null_black} "
            f"expected_each={null_per_side}"
        )
    if unique_null_total != args.null_transitions:
        raise AssertionError(
            "canonical null-source quota failed: "
            f"expected {args.null_transitions}, got {unique_null_total}"
        )
    for quota_name in ("quiet", "double_pawn_push", "ordinary_capture"):
        if counts[quota_name] < quota:
            raise AssertionError(
                f"{quota_name} quota failed: expected {quota}, got {counts[quota_name]}"
            )
    if long_sequences < long_required:
        raise AssertionError(
            f"long-sequence quota failed: expected {long_required}, got {long_sequences}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# case_id\tcategory\tinitial_fen\tspace-separated_uci_moves\n"]
    for case_id, category, fen, moves in cases:
        lines.append(f"{case_id}\t{category}\t{fen}\t{' '.join(moves)}\n")
    args.output.write_text("".join(lines), encoding="utf-8", newline="\n")

    corpus_sha256 = sha256_file(args.output)
    total_transitions = sum(len(case[3]) for case in cases)
    metadata: dict[str, object] = {
        "format": "pyro-incremental-nnue-sequences-v1",
        "seed": args.seed,
        "smoke": args.smoke,
        "fixture_file": fixtures_path.name,
        "fixture_sha256": sha256_file(fixtures_path),
        "fixture_cases": len(fixture_cases),
        "corpus_file": args.output.name,
        "corpus_bytes": args.output.stat().st_size,
        "corpus_sha256": corpus_sha256,
        "sequence_cases": len(cases),
        "total_transitions": total_transitions,
        "unique_canonical_semantic_non_null_child_positions": len(canonical_positions),
        "non_null_child_side_to_move": dict(sorted(child_sides.items())),
        "null_transitions": counts["null"],
        "null_source_side_to_move": {
            "black": counts["null_source_black"],
            "white": counts["null_source_white"],
        },
        "unique_canonical_null_source_positions": unique_null_total,
        "unique_canonical_null_sources_by_side_to_move": {
            "black": unique_null_black,
            "white": unique_null_white,
        },
        "canonical_null_source_representative_round_trip_mismatches": 0,
        "transition_categories": dict(sorted(counts.items())),
        "long_sequence_minimum_plies": MIN_LONG_SEQUENCE_PLIES,
        "long_sequences": long_sequences,
        "maximum_sequence_plies": max(len(case[3]) for case in cases),
        "quotas": {
            "double_pawn_push": quota,
            "long_sequences": long_required,
            "ordinary_capture": quota,
            "quiet": quota,
            "target_unique": args.target_unique,
        },
    }
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return metadata


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=script_dir / "fixtures" / "nnue_incremental_special_moves.tsv",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--target-unique", type=int, default=DEFAULT_UNIQUE_POSITIONS)
    parser.add_argument("--null-transitions", type=int, default=DEFAULT_NULL_TRANSITIONS)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="use reduced move-category and long-sequence quotas for an inexpensive smoke",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = generate(args)
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
