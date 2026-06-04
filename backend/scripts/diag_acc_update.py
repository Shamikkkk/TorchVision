"""
Isolate the acc_update bug.

Two ways to compute eval of "after 1.c4 g6" (white to move):
  A) from_board fresh from that FEN
  B) from_board for "after 1.c4" + manually apply g7->g6 update

If A != B, there's a logic bug in our incremental logic.
If A == B, the bug is in the Rust acc_update implementation.

Also: compare the feature indices Python computes vs what Rust should compute.
"""

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
NNUE_PATH = ROOT / "engine" / "pyro.nnue"

HIDDEN_SIZE = 256
INPUT_SIZE = 768
QA = 255
QB = 64

MAGIC = b"\x4E\x4E\x55\x45"
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 0, 1, 2, 3, 4, 5

PIECE_MAP = {
    'P': (PAWN, True),   'N': (KNIGHT, True),  'B': (BISHOP, True),
    'R': (ROOK, True),   'Q': (QUEEN, True),   'K': (KING, True),
    'p': (PAWN, False),  'n': (KNIGHT, False), 'b': (BISHOP, False),
    'r': (ROOK, False),  'q': (QUEEN, False),  'k': (KING, False),
}


def load_nnue(path: Path):
    data = path.read_bytes()
    assert data[:4] == MAGIC
    offset = 8
    n_ft_w = INPUT_SIZE * HIDDEN_SIZE
    ft_w_raw = struct.unpack_from(f"<{n_ft_w}h", data, offset)
    ft_weights = [list(ft_w_raw[f * HIDDEN_SIZE:(f + 1) * HIDDEN_SIZE]) for f in range(INPUT_SIZE)]
    offset += n_ft_w * 2
    ft_bias = list(struct.unpack_from(f"<{HIDDEN_SIZE}h", data, offset))
    offset += HIDDEN_SIZE * 2
    out_weights = list(struct.unpack_from(f"<{HIDDEN_SIZE * 2}h", data, offset))
    offset += HIDDEN_SIZE * 2 * 2
    out_bias = struct.unpack_from("<h", data, offset)[0]
    return ft_weights, ft_bias, out_weights, out_bias


def feature_index(perspective: bool, sq: int, piece_type: int, piece_color: bool) -> int:
    mirrored_sq = sq if perspective else (sq ^ 56)
    color_idx = 0 if (piece_color == perspective) else 1
    return color_idx * 6 * 64 + piece_type * 64 + mirrored_sq


def parse_fen(fen: str):
    parts = fen.split()
    placement, stm_str = parts[0], parts[1]
    pieces = []
    rank, file_ = 7, 0
    for ch in placement:
        if ch == '/':
            rank -= 1; file_ = 0
        elif ch.isdigit():
            file_ += int(ch)
        else:
            sq = rank * 8 + file_
            pt, is_white = PIECE_MAP[ch]
            pieces.append((sq, pt, is_white))
            file_ += 1
    side_to_move = (stm_str == 'w')
    return pieces, side_to_move


def make_accumulator(ft_weights, ft_bias, pieces):
    white = list(ft_bias)
    black = list(ft_bias)
    for sq, pt, is_white in pieces:
        w_idx = feature_index(True, sq, pt, is_white)
        b_idx = feature_index(False, sq, pt, is_white)
        for i in range(HIDDEN_SIZE):
            white[i] += ft_weights[w_idx][i]
            black[i] += ft_weights[b_idx][i]
    return white, black


def evaluate(white_acc, black_acc, out_weights, out_bias, side_to_move: bool) -> int:
    stm  = white_acc if side_to_move else black_acc
    nstm = black_acc if side_to_move else white_acc
    output = out_bias
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, stm[i]))  * out_weights[i]
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, nstm[i])) * out_weights[HIDDEN_SIZE + i]
    return output // (QA * QB)


def acc_update_py(white: list, black: list, ft_weights, from_sq: int, to_sq: int,
                   pt: int, is_white_piece: bool):
    """Python simulation of Rust acc_update for a quiet move (no capture)."""
    new_white = list(white)
    new_black = list(black)

    # Remove from from_sq
    w_rm = feature_index(True,  from_sq, pt, is_white_piece)
    b_rm = feature_index(False, from_sq, pt, is_white_piece)
    for i in range(HIDDEN_SIZE):
        new_white[i] -= ft_weights[w_rm][i]
        new_black[i] -= ft_weights[b_rm][i]

    # Add to to_sq
    w_add = feature_index(True,  to_sq, pt, is_white_piece)
    b_add = feature_index(False, to_sq, pt, is_white_piece)
    for i in range(HIDDEN_SIZE):
        new_white[i] += ft_weights[w_add][i]
        new_black[i] += ft_weights[b_add][i]

    return new_white, new_black


def main():
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NNUE_PATH)

    # FEN after 1.c4 (black to move)
    fen_after_c4 = "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1"
    # FEN after 1.c4 g6 (white to move)
    fen_after_c4_g6 = "rnbqkbnr/pppppp1p/6p1/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 0 2"

    # Method A: from_board for "after 1.c4 g6"
    pieces_A, stm_A = parse_fen(fen_after_c4_g6)
    white_A, black_A = make_accumulator(ft_weights, ft_bias, pieces_A)
    eval_A = evaluate(white_A, black_A, out_weights, out_bias, stm_A)

    # Method B: from_board for "after 1.c4", then apply g7->g6 update
    pieces_B0, _ = parse_fen(fen_after_c4)
    white_B0, black_B0 = make_accumulator(ft_weights, ft_bias, pieces_B0)
    # Apply black pawn g7->g6: from_sq=54, to_sq=46, piece=PAWN, is_white=False
    g7 = 6 * 8 + 6  # 54
    g6 = 5 * 8 + 6  # 46
    white_B, black_B = acc_update_py(white_B0, black_B0, ft_weights, g7, g6, PAWN, False)
    # STM after g6 is White (True)
    eval_B = evaluate(white_B, black_B, out_weights, out_bias, True)

    print("=" * 70)
    print("Method A (from_board of 'after 1.c4 g6'):")
    print(f"  eval = {eval_A:+d} cp  (white to move)")
    print()
    print("Method B (from_board of 'after 1.c4' + incremental g7->g6):")
    print(f"  eval = {eval_B:+d} cp  (white to move)")
    print()
    print(f"Difference A-B: {eval_A - eval_B:+d} cp")
    print()

    # Check if accumulators match
    mismatches_w = sum(1 for a, b in zip(white_A, white_B) if a != b)
    mismatches_b = sum(1 for a, b in zip(black_A, black_B) if a != b)
    print(f"White acc mismatches: {mismatches_w}/{HIDDEN_SIZE}")
    print(f"Black acc mismatches: {mismatches_b}/{HIDDEN_SIZE}")

    if mismatches_w + mismatches_b == 0:
        print("Accumulators MATCH — Python incremental update is correct.")
        print("The bug MUST be in the Rust acc_update implementation.")
    else:
        print("Accumulators DIFFER — bug in Python incremental logic too.")
        # Show the first mismatch
        for i in range(HIDDEN_SIZE):
            if white_A[i] != white_B[i]:
                print(f"  white[{i}]: A={white_A[i]}, B={white_B[i]}, delta={white_A[i]-white_B[i]}")
                break

    print()
    print("=" * 70)
    print("Feature index verification for g7->g6 (black pawn, sq=54->46):")
    print()
    sq_from, sq_to, pt, is_white_piece = g7, g6, PAWN, False

    w_rm  = feature_index(True,  sq_from, pt, is_white_piece)
    b_rm  = feature_index(False, sq_from, pt, is_white_piece)
    w_add = feature_index(True,  sq_to,   pt, is_white_piece)
    b_add = feature_index(False, sq_to,   pt, is_white_piece)

    print(f"  g7={sq_from}: white_rm={w_rm}, black_rm={b_rm}")
    print(f"  g6={sq_to}:  white_add={w_add}, black_add={b_add}")
    print()

    # What would Rust compute? Same formula, so we just verify inputs.
    # piece_color = is_white_piece = False (black piece)
    # perspective = True (white's view): color_idx = (False == True) = 1
    # mirrored_sq = sq (white perspective uses sq directly)
    # white_rm = 1*384 + 0*64 + 54 = 438 (matches?)
    # black_rm: perspective=False, mirrored_sq = 54^56 = 10
    # color_idx = (False == False) = True = 0
    # black_rm = 0*384 + 0*64 + 10 = 10

    # Recompute manually for verification
    manual_w_rm  = 1 * 6 * 64 + PAWN * 64 + 54
    manual_b_rm  = 0 * 6 * 64 + PAWN * 64 + (54 ^ 56)
    manual_w_add = 1 * 6 * 64 + PAWN * 64 + 46
    manual_b_add = 0 * 6 * 64 + PAWN * 64 + (46 ^ 56)

    print(f"  Manual verification:")
    print(f"    white_rm expected: 1*384 + 0*64 + 54 = {manual_w_rm}, got {w_rm}")
    print(f"    black_rm expected: 0*384 + 0*64 + {54^56} = {manual_b_rm}, got {b_rm}")
    print(f"    white_add expected: 1*384 + 0*64 + 46 = {manual_w_add}, got {w_add}")
    print(f"    black_add expected: 0*384 + 0*64 + {46^56} = {manual_b_add}, got {b_add}")

    print()
    print("=" * 70)
    print("Also checking 1.e4 position (should show same pattern):")
    fen_after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    pieces_e4, _ = parse_fen(fen_after_e4)
    white_e4, black_e4 = make_accumulator(ft_weights, ft_bias, pieces_e4)
    eval_e4_g6 = evaluate(*(acc_update_py(white_e4, black_e4, ft_weights, g7, g6, PAWN, False)),
                          out_weights, out_bias, True)
    print(f"  After 1.e4 + g7->g6 (incremental): {eval_e4_g6:+d} cp")

    fen_after_e4_g6 = "rnbqkbnr/pppppp1p/6p1/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    pieces_e4_g6, _ = parse_fen(fen_after_e4_g6)
    white_e4_g6, black_e4_g6 = make_accumulator(ft_weights, ft_bias, pieces_e4_g6)
    eval_e4_g6_fresh = evaluate(white_e4_g6, black_e4_g6, out_weights, out_bias, True)
    print(f"  After 1.e4 g6 (from_board fresh): {eval_e4_g6_fresh:+d} cp")
    print(f"  Match: {eval_e4_g6 == eval_e4_g6_fresh}")


if __name__ == "__main__":
    main()
