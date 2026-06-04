"""
Deep corruption scan: enumerate ALL positions reachable in 2-4 half-moves
from startpos and flag NNUE evals beyond ±200 cp.

The depth-2 common-move scan showed max ±118 cp (all normal).
The engine depth-1 shows +492 cp, which must come from qsearch exploring
capture sequences 3+ ply deep.

Strategy: use python-chess to generate ALL legal moves from key positions,
then evaluate every resulting position, going 3 ply deep from startpos.
"""

import struct
from pathlib import Path
import chess

ROOT = Path(__file__).resolve().parent.parent.parent
NNUE_PATH = ROOT / "engine" / "pyro.nnue"

HIDDEN_SIZE = 256
INPUT_SIZE = 768
QA = 255
QB = 64

MAGIC = b"\x4E\x4E\x55\x45"

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 0, 1, 2, 3, 4, 5

PIECE_TYPE_MAP = {
    chess.PAWN: PAWN, chess.KNIGHT: KNIGHT, chess.BISHOP: BISHOP,
    chess.ROOK: ROOK,  chess.QUEEN: QUEEN,  chess.KING: KING,
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


def board_to_pieces(board: chess.Board):
    pieces = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            pt = PIECE_TYPE_MAP[piece.piece_type]
            is_white = (piece.color == chess.WHITE)
            pieces.append((sq, pt, is_white))
    return pieces


def eval_board(board: chess.Board, ft_weights, ft_bias, out_weights, out_bias) -> int:
    pieces = board_to_pieces(board)
    white = list(ft_bias)
    black_acc = list(ft_bias)
    for sq, pt, is_white in pieces:
        w_idx = feature_index(True, sq, pt, is_white)
        b_idx = feature_index(False, sq, pt, is_white)
        for i in range(HIDDEN_SIZE):
            white[i] += ft_weights[w_idx][i]
            black_acc[i] += ft_weights[b_idx][i]
    stm_flag = (board.turn == chess.WHITE)
    stm  = white if stm_flag else black_acc
    nstm = black_acc if stm_flag else white
    output = out_bias
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, stm[i]))  * out_weights[i]
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, nstm[i])) * out_weights[HIDDEN_SIZE + i]
    return output // (QA * QB)


def scan(ft_weights, ft_bias, out_weights, out_bias, max_depth: int = 3,
         outlier_threshold: int = 200):
    """BFS over all positions reachable in max_depth half-moves from startpos."""
    root = chess.Board()
    found_outliers = []

    def dfs(board: chess.Board, depth: int, path: list):
        ev = eval_board(board, ft_weights, ft_bias, out_weights, out_bias)
        if abs(ev) > outlier_threshold:
            found_outliers.append((list(path), ev, board.fen()))
        if depth == 0:
            return
        for move in board.legal_moves:
            board.push(move)
            dfs(board, depth - 1, path + [move.uci()])
            board.pop()

    dfs(root, max_depth, [])
    return found_outliers


def main():
    print(f"Loading NNUE: {NNUE_PATH}")
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NNUE_PATH)
    print()

    # Depth 2: all positions reachable in 2 half-moves (quick sanity check)
    print("Scanning depth=2 (all positions, outlier threshold: ±200 cp)...")
    outliers2 = scan(ft_weights, ft_bias, out_weights, out_bias, max_depth=2, outlier_threshold=200)
    print(f"  Found {len(outliers2)} outliers out of (20 * 20 = ~400) positions")
    for path, ev, fen in sorted(outliers2, key=lambda x: abs(x[1]), reverse=True)[:10]:
        print(f"  {' '.join(path):20s}: {ev:+d} cp   [{fen[:40]}...]")
    print()

    # Depth 3: all positions reachable in 3 half-moves (finds qsearch targets)
    print("Scanning depth=3 (all positions, outlier threshold: ±200 cp)...")
    print("  (This covers qsearch depth-1 captures from depth-2 positions)")
    outliers3 = scan(ft_weights, ft_bias, out_weights, out_bias, max_depth=3, outlier_threshold=200)
    print(f"  Found {len(outliers3)} outliers")
    for path, ev, fen in sorted(outliers3, key=lambda x: abs(x[1]), reverse=True)[:20]:
        print(f"  {' '.join(path):28s}: {ev:+d} cp")
    print()

    # Depth 4: narrowed scan — only explore positions where depth-3 eval > 100 cp
    # (follow the "suspicious" branches)
    print("Scanning depth=4 for EXTREME outliers (threshold ±350 cp)...")
    outliers4 = scan(ft_weights, ft_bias, out_weights, out_bias, max_depth=4, outlier_threshold=350)
    print(f"  Found {len(outliers4)} extreme outliers")
    for path, ev, fen in sorted(outliers4, key=lambda x: abs(x[1]), reverse=True)[:20]:
        print(f"  {' '.join(path):35s}: {ev:+d} cp")
    print()

    if outliers4:
        worst = sorted(outliers4, key=lambda x: x[1])[0]
        print("Most negative (worst for STM):")
        print(f"  Path: {' '.join(worst[0])}")
        print(f"  Eval: {worst[1]:+d} cp")
        print(f"  FEN:  {worst[2]}")


if __name__ == "__main__":
    main()
