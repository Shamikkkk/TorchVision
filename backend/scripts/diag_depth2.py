"""
Depth-2 NNUE corruption diagnostic.

Root observation:
  Python static eval after 1.c4 (black STM) = -3 cp  [normal]
  Engine depth-1 from same position         = +492 cp [catastrophic]

Since depth-1 searches ONE black reply and evaluates the resulting
position statically, one of the positions after 1.c4 <black_move>
must have a wildly wrong NNUE evaluation.

This script finds it by checking all common black replies to five
first moves, computing Python static NNUE eval of each resulting
position (white to move), and flagging outliers.
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
    assert data[:4] == MAGIC, f"Bad magic: {data[:4]!r}"
    version = struct.unpack_from("<I", data, 4)[0]
    assert version == 1, f"Version {version}"
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


def parse_fen(fen: str):
    parts = fen.split()
    placement, stm_str = parts[0], parts[1]
    pieces = []
    rank, file = 7, 0
    for ch in placement:
        if ch == '/':
            rank -= 1; file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = rank * 8 + file
            pt, is_white = PIECE_MAP[ch]
            pieces.append((sq, pt, is_white))
            file += 1
    side_to_move = (stm_str == 'w')
    return pieces, side_to_move


def eval_fen(fen: str, ft_weights, ft_bias, out_weights, out_bias) -> int:
    pieces, stm = parse_fen(fen)
    w, b = make_accumulator(ft_weights, ft_bias, pieces)
    return evaluate(w, b, out_weights, out_bias, stm)


def main():
    print(f"Loading NNUE: {NNUE_PATH}")
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NNUE_PATH)
    print()

    # Positions to test: after white's first move (black to move), then
    # after black's reply (white to move).  Format: (label, fen_after_white1, black_replies)
    # Squares: a1=0 b1=1 ... h1=7 / a2=8 ... h8=63
    # FENs are exact from chess rules.

    test_tree = [
        ("1.c4", "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1", [
            ("1...e5",  "rnbqkbnr/pppp1ppp/8/4p3/2P5/8/PP1PPPPP/RNBQKBNR w KQkq e6 0 2"),
            ("1...c5",  "rnbqkbnr/pp1ppppp/8/2p5/2P5/8/PP1PPPPP/RNBQKBNR w KQkq c6 0 2"),
            ("1...Nf6", "rnbqkb1r/pppppppp/5n2/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 1 2"),
            ("1...e6",  "rnbqkbnr/pppp1ppp/4p3/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 0 2"),
            ("1...d5",  "rnbqkbnr/ppp1pppp/8/3p4/2P5/8/PP1PPPPP/RNBQKBNR w KQkq d6 0 2"),
            ("1...g6",  "rnbqkbnr/pppppp1p/6p1/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 0 2"),
            ("1...f5",  "rnbqkbnr/ppppp1pp/8/5p2/2P5/8/PP1PPPPP/RNBQKBNR w KQkq f6 0 2"),
            ("1...b6",  "rnbqkbnr/p1pppppp/1p6/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 0 2"),
        ]),
        ("1.e4", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", [
            ("1...e5",  "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"),
            ("1...c5",  "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"),
            ("1...e6",  "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"),
            ("1...d5",  "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"),
            ("1...Nf6", "rnbqkb1r/pppppppp/5n2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2"),
            ("1...d6",  "rnbqkbnr/ppp1pppp/3p4/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"),
            ("1...Nc6", "r1bqkbnr/pppppppp/2n5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2"),
            ("1...g6",  "rnbqkbnr/pppppp1p/6p1/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"),
        ]),
        ("1.d4", "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1", [
            ("1...d5",  "rnbqkbnr/ppp1pppp/8/3p4/3P4/8/PPP1PPPP/RNBQKBNR w KQkq d6 0 2"),
            ("1...Nf6", "rnbqkb1r/pppppppp/5n2/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 1 2"),
            ("1...e6",  "rnbqkbnr/pppp1ppp/4p3/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2"),
            ("1...f5",  "rnbqkbnr/ppppp1pp/8/5p2/3P4/8/PPP1PPPP/RNBQKBNR w KQkq f6 0 2"),
            ("1...c5",  "rnbqkbnr/pp1ppppp/8/2p5/3P4/8/PPP1PPPP/RNBQKBNR w KQkq c6 0 2"),
            ("1...g6",  "rnbqkbnr/pppppp1p/6p1/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2"),
        ]),
        ("1.Nf3", "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1", [
            ("1...d5",  "rnbqkbnr/ppp1pppp/8/3p4/8/5N2/PPPPPPPP/RNBQKB1R w KQkq d6 0 2"),
            ("1...Nf6", "rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 2 2"),
            ("1...c5",  "rnbqkbnr/pp1ppppp/8/2p5/8/5N2/PPPPPPPP/RNBQKB1R w KQkq c6 0 2"),
            ("1...e6",  "rnbqkbnr/pppp1ppp/4p3/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 2"),
            ("1...g6",  "rnbqkbnr/pppppp1p/6p1/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 2"),
        ]),
    ]

    print("=" * 78)
    print("DEPTH-2 NNUE STATIC EVAL SCAN")
    print("Finding corrupted positions (expect |eval| > 200 cp for normal opening moves)")
    print("=" * 78)
    print()

    # Also baseline: startpos itself
    startpos_eval = eval_fen(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        ft_weights, ft_bias, out_weights, out_bias
    )
    print(f"  startpos (W2M): {startpos_eval:+d} cp")
    print()

    OUTLIER_THRESHOLD = 150  # flag anything beyond ±150 cp in an opening position

    all_results = []

    for white_move, fen_after_white, black_replies in test_tree:
        w1_eval = eval_fen(fen_after_white, ft_weights, ft_bias, out_weights, out_bias)
        print(f"After {white_move} (B2M): {w1_eval:+d} cp (STM=black, + means black ahead)")
        best_for_black = None

        for reply_label, fen_after_reply in black_replies:
            ev = eval_fen(fen_after_reply, ft_weights, ft_bias, out_weights, out_bias)
            flag = " <-- OUTLIER" if abs(ev) > OUTLIER_THRESHOLD else ""
            print(f"  {reply_label:12s} (W2M): {ev:+d} cp{flag}")
            all_results.append((white_move + " " + reply_label, ev))
            if best_for_black is None or (-ev) > (-best_for_black[1]):
                best_for_black = (reply_label, ev)

        # black picks the move that minimizes white's eval
        if best_for_black:
            print(f"  -> Black best: {best_for_black[0]} gives white {best_for_black[1]:+d} cp")
            print(f"     (Depth-1 from {white_move} would return {-best_for_black[1]:+d} for black)")
        print()

    # Summary of most extreme positions
    all_results.sort(key=lambda x: x[1])
    print("=" * 78)
    print("MOST EXTREME EVALS (potential corruption sources):")
    print("=" * 78)
    print("Bottom 5 (worst for white):")
    for label, ev in all_results[:5]:
        print(f"  {label:30s}: {ev:+d} cp")
    print("Top 5 (most wildly good for white):")
    for label, ev in reversed(all_results[-5:]):
        print(f"  {label:30s}: {ev:+d} cp")


if __name__ == "__main__":
    main()
