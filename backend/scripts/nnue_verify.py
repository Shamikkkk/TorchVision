"""
NNUE verification: Python implementation vs engine.
Loads pyro.nnue and computes evaluations for several positions,
then compares to what `pyro.exe --no-nnue` (PeSTO) gives vs engine output.

Run:
    cd backend
    python -m scripts.nnue_verify
"""

import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
NNUE_PATH = ROOT / "engine" / "pyro.nnue"
ENGINE_PATH = ROOT / "engine" / "target" / "release" / "pyro.exe"

HIDDEN_SIZE = 256
INPUT_SIZE = 768
QA = 255
QB = 64

MAGIC = b"\x4E\x4E\x55\x45"


def load_nnue(path: Path):
    data = path.read_bytes()
    assert data[:4] == MAGIC, f"Bad magic: {data[:4]!r}"
    version = struct.unpack_from("<I", data, 4)[0]
    assert version == 1, f"Version {version}"

    offset = 8
    n_ft_w = INPUT_SIZE * HIDDEN_SIZE
    ft_w_raw = struct.unpack_from(f"<{n_ft_w}h", data, offset)
    # ft_weights[feature][hidden] — column-major: feature-first blocks of HIDDEN_SIZE
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
    """
    pieces: list of (sq, piece_type, is_white)
    returns (white_acc, black_acc) each of length HIDDEN_SIZE
    """
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
    stm = white_acc if side_to_move else black_acc
    nstm = black_acc if side_to_move else white_acc
    output = out_bias
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, stm[i])) * out_weights[i]
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, nstm[i])) * out_weights[HIDDEN_SIZE + i]
    return output // (QA * QB)


# Piece type constants (matching engine)
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 0, 1, 2, 3, 4, 5


def startpos_pieces():
    """Standard chess starting position pieces: (sq, piece_type, is_white)."""
    pieces = []
    # White pieces
    back_rank = [ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK]
    for f, pt in enumerate(back_rank):
        pieces.append((f, pt, True))          # rank 1
        pieces.append((f + 8, PAWN, True))    # rank 2
    # Black pieces
    for f, pt in enumerate(back_rank):
        pieces.append((56 + f, pt, False))    # rank 8
        pieces.append((48 + f, PAWN, False))  # rank 7
    return pieces


def engine_eval(fen: str, depth: int = 1) -> int:
    """Ask the engine for the evaluation at given depth."""
    cmd_str = f"uci\nisready\nposition fen {fen}\ngo depth {depth}\nquit\n"
    result = subprocess.run(
        [str(ENGINE_PATH)],
        input=cmd_str, capture_output=True, text=True, timeout=30
    )
    lines = result.stdout.splitlines()
    # Find last "info depth N score cp X"
    score = None
    for line in lines:
        if line.startswith("info") and "score cp" in line:
            parts = line.split()
            idx = parts.index("cp")
            score = int(parts[idx + 1])
    return score


def main():
    print(f"Loading {NNUE_PATH}")
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NNUE_PATH)
    print(f"  ft_weights shape: [{INPUT_SIZE}][{HIDDEN_SIZE}]")
    print(f"  out_bias: {out_bias}")
    print(f"  out_weights[0:4]: {out_weights[:4]}")
    print(f"  out_weights[256:260]: {out_weights[256:260]}")
    print()

    # ── Test 1: Startpos (white to move) ──────────────────────────────────────
    pieces = startpos_pieces()
    white_acc, black_acc = make_accumulator(ft_weights, ft_bias, pieces)

    py_eval_w2m = evaluate(white_acc, black_acc, out_weights, out_bias, True)
    engine_d1 = engine_eval("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=1)
    engine_d6 = engine_eval("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=6)
    print(f"Startpos (W2M):")
    print(f"  Python eval      : {py_eval_w2m:+d} cp")
    print(f"  Engine depth-1   : {engine_d1:+d} cp  (best move eval, from White's perspective)")
    print(f"  Engine depth-6   : {engine_d6:+d} cp")
    print()

    # ── Test 2: Startpos after 1.g3 (black to move) ───────────────────────────
    # g2 pawn moves to g3: sq=14 → sq=22 (g2=14, g3=22)
    pieces_after_g3 = [p for p in pieces if not (p[0] == 14 and p[2])]  # remove g2 pawn
    pieces_after_g3.append((22, PAWN, True))  # add pawn on g3

    white_acc_g3, black_acc_g3 = make_accumulator(ft_weights, ft_bias, pieces_after_g3)
    py_eval_b2m_g3 = evaluate(white_acc_g3, black_acc_g3, out_weights, out_bias, False)

    fen_after_g3 = "rnbqkbnr/pppppppp/8/8/8/6P1/PPPPPP1P/RNBQKBNR b KQkq - 0 1"
    engine_b2m_d1 = engine_eval(fen_after_g3, depth=1)
    print(f"After 1.g3 (B2M):")
    print(f"  Python B2M eval  : {py_eval_b2m_g3:+d} cp  (+ = good for black/STM)")
    print(f"  Python W score   : {-py_eval_b2m_g3:+d} cp  (what white gets from playing 1.g3)")
    print(f"  Engine depth-1   : {engine_b2m_d1:+d} cp  (from black's perspective as root)")
    print()

    # ── Test 3: Material asymmetry (white queen missing vs startpos) ─────────
    pieces_no_queen = [(sq, pt, c) for sq, pt, c in pieces if not (pt == QUEEN and c)]
    white_acc_nq, black_acc_nq = make_accumulator(ft_weights, ft_bias, pieces_no_queen)
    py_eval_no_queen = evaluate(white_acc_nq, black_acc_nq, out_weights, out_bias, True)

    fen_no_queen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"
    engine_no_queen = engine_eval(fen_no_queen, depth=1)
    print(f"White queen missing (W2M):")
    print(f"  Python eval      : {py_eval_no_queen:+d} cp  (should be ~-900)")
    print(f"  Engine depth-1   : {engine_no_queen:+d} cp")
    print()

    # ── Test 4: Black queen missing ───────────────────────────────────────────
    pieces_no_bqueen = [(sq, pt, c) for sq, pt, c in pieces if not (pt == QUEEN and not c)]
    white_acc_nbq, black_acc_nbq = make_accumulator(ft_weights, ft_bias, pieces_no_bqueen)
    py_eval_no_bqueen = evaluate(white_acc_nbq, black_acc_nbq, out_weights, out_bias, True)

    fen_no_bqueen = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    engine_no_bqueen = engine_eval(fen_no_bqueen, depth=1)
    print(f"Black queen missing (W2M):")
    print(f"  Python eval      : {py_eval_no_bqueen:+d} cp  (should be ~+900)")
    print(f"  Engine depth-1   : {engine_no_bqueen:+d} cp")
    print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("KEY CHECK: Active neurons in startpos accumulator")
    active = sum(1 for v in white_acc if 0 < v < QA)
    clamped_lo = sum(1 for v in white_acc if v <= 0)
    clamped_hi = sum(1 for v in white_acc if v >= QA)
    print(f"  White acc: active={active}, <=0={clamped_lo}, >=255={clamped_hi}")
    active = sum(1 for v in black_acc if 0 < v < QA)
    clamped_lo = sum(1 for v in black_acc if v <= 0)
    clamped_hi = sum(1 for v in black_acc if v >= QA)
    print(f"  Black acc: active={active}, <=0={clamped_lo}, >=255={clamped_hi}")


if __name__ == "__main__":
    main()
