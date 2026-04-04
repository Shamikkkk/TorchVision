"""Initialize pyro.nnue with hardcoded material knowledge.

Encodes piece material values directly into the NNUE weight matrix so
the network starts from a baseline that at least matches material-counting
evaluation.  This is the "chess-inator" trick.

Architecture: 768 -> 256 -> 1

The key design constraint is that the i32 accumulator values must stay
within CReLU range [0, QA=255] for the signal to survive.  We pick a
DIVISOR such that a full side's material (≈3900cp) maps to ~200 in the
accumulator, leaving headroom.

Quantization chain (must match engine/src/nnue.rs):
  ft_i16  = round(ft_float * QA)       # QA = 255
  out_i16 = round(out_float * QB)      # QB = 64
  cp      = raw_output * SCALE / (QA * QB)   # SCALE = 400
"""

import struct
import os
import numpy as np

# ---------------------------------------------------------------------------
# Constants (must match engine/src/nnue.rs)
# ---------------------------------------------------------------------------
INPUT_SIZE = 768
HIDDEN_SIZE = 256
QA = 255
QB = 64
SCALE = 400

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = range(6)

PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 0,
}

# Scaling: DIVISOR chosen so that a full side's material ≈ 200 in accumulator.
# Full side = 8*100 + 2*320 + 2*330 + 2*500 + 900 = 3900
# ft_i16 = round(piece_val * QA / DIVISOR), sum ≈ 3900 * 255 / 5000 ≈ 199
DIVISOR = 5000

# Output weight (i16) derived from: out_i16 = round(DIVISOR * QB / (H * SCALE))
# = round(5000 * 64 / (256 * 400)) = round(3.125) = 3
OUT_W = round(DIVISOR * QB / (HIDDEN_SIZE * SCALE))

MAGIC = bytes([0x4E, 0x4E, 0x55, 0x45])
VERSION = 1

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(SCRIPT_DIR, "..", "..", "engine")
OUTPUT_PATH = os.path.join(ENGINE_DIR, "pyro.nnue")


def init_weights():
    """Build float weight matrices with material knowledge."""
    rng = np.random.default_rng(42)

    ft_weights = np.zeros((INPUT_SIZE, HIDDEN_SIZE), dtype=np.float32)

    for color_idx in range(2):
        sign = 1.0 if color_idx == 0 else -1.0
        for piece_type in range(6):
            val = PIECE_VALUES[piece_type] * sign / DIVISOR
            for sq in range(64):
                feat_idx = color_idx * 384 + piece_type * 64 + sq
                ft_weights[feat_idx, :] = val

    # Small noise to break symmetry for future training (±1 in quantized domain)
    ft_weights += rng.normal(0, 0.005, ft_weights.shape).astype(np.float32)

    ft_bias = np.zeros(HIDDEN_SIZE, dtype=np.float32)

    # Output weights: STM positive, NSTM negative
    # out_float = DIVISOR / (HIDDEN_SIZE * SCALE)
    out_float = DIVISOR / (HIDDEN_SIZE * SCALE)
    out_weights = np.zeros(HIDDEN_SIZE * 2, dtype=np.float32)
    out_weights[:HIDDEN_SIZE] = out_float
    out_weights[HIDDEN_SIZE:] = -out_float

    out_bias = np.float32(0.0)

    return ft_weights, ft_bias, out_weights, out_bias


def quantize(ft_weights, ft_bias, out_weights, out_bias):
    """Quantize float weights to i16."""
    ft_q = np.clip(np.round(ft_weights * QA), -32768, 32767).astype(np.int16)
    ft_bias_q = np.clip(np.round(ft_bias * QA), -32768, 32767).astype(np.int16)
    out_q = np.clip(np.round(out_weights * QB), -32768, 32767).astype(np.int16)
    out_bias_q = np.int16(np.clip(np.round(out_bias * QB), -32768, 32767))
    return ft_q, ft_bias_q, out_q, out_bias_q


def write_nnue(path, ft_q, ft_bias_q, out_q, out_bias_q):
    """Write the binary .nnue file."""
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", VERSION))
        for row in range(INPUT_SIZE):
            for col in range(HIDDEN_SIZE):
                f.write(struct.pack("<h", int(ft_q[row, col])))
        for val in ft_bias_q:
            f.write(struct.pack("<h", int(val)))
        for val in out_q:
            f.write(struct.pack("<h", int(val)))
        f.write(struct.pack("<h", int(out_bias_q)))


def verify(path):
    """Load the file and run evaluation sanity checks."""
    with open(path, "rb") as f:
        magic = f.read(4)
        assert magic == MAGIC, f"Bad magic: {magic!r}"
        version = struct.unpack("<I", f.read(4))[0]
        assert version == VERSION, f"Bad version: {version}"
        data = f.read()

    total_values = INPUT_SIZE * HIDDEN_SIZE + HIDDEN_SIZE + HIDDEN_SIZE * 2 + 1
    assert len(data) == total_values * 2
    values = struct.unpack(f"<{total_values}h", data)
    idx = 0

    ft_w = np.array(values[idx:idx + INPUT_SIZE * HIDDEN_SIZE], dtype=np.int16).reshape(INPUT_SIZE, HIDDEN_SIZE)
    idx += INPUT_SIZE * HIDDEN_SIZE
    ft_b = np.array(values[idx:idx + HIDDEN_SIZE], dtype=np.int16)
    idx += HIDDEN_SIZE
    out_w = np.array(values[idx:idx + HIDDEN_SIZE * 2], dtype=np.int16)
    idx += HIDDEN_SIZE * 2
    out_b = values[idx]

    # Print quantized weight samples
    print(f"  ft_w pawn (friendly, sq=0):  {ft_w[0, 0]:+d}")
    print(f"  ft_w queen (friendly, sq=0): {ft_w[QUEEN * 64, 0]:+d}")
    print(f"  ft_w pawn (opponent, sq=0):  {ft_w[384, 0]:+d}")
    print(f"  out_w STM[0]: {out_w[0]:+d},  NSTM[0]: {out_w[HIDDEN_SIZE]:+d}")
    print(f"  out_bias: {out_b}")
    print()

    def simulate_eval(pieces_white, pieces_black, stm_white=True):
        """Simulate the Rust NNUE evaluation."""
        acc_w = ft_b.astype(np.int32).copy()
        acc_b = ft_b.astype(np.int32).copy()

        for pt, sq in pieces_white:
            # White perspective: friendly (color_idx=0)
            acc_w += ft_w[0 * 384 + pt * 64 + sq].astype(np.int32)
            # Black perspective: opponent (color_idx=1), mirror sq
            acc_b += ft_w[1 * 384 + pt * 64 + (sq ^ 56)].astype(np.int32)

        for pt, sq in pieces_black:
            # White perspective: opponent (color_idx=1)
            acc_w += ft_w[1 * 384 + pt * 64 + sq].astype(np.int32)
            # Black perspective: friendly (color_idx=0), mirror sq
            acc_b += ft_w[0 * 384 + pt * 64 + (sq ^ 56)].astype(np.int32)

        stm_acc, nstm_acc = (acc_w, acc_b) if stm_white else (acc_b, acc_w)

        stm_c = np.clip(stm_acc, 0, QA)
        nstm_c = np.clip(nstm_acc, 0, QA)

        output = int(out_b)
        output += int(np.dot(stm_c, out_w[:HIDDEN_SIZE].astype(np.int32)))
        output += int(np.dot(nstm_c, out_w[HIDDEN_SIZE:].astype(np.int32)))

        return output * SCALE // (QA * QB)

    # Standard starting pieces
    white_pieces = (
        [(PAWN, sq) for sq in range(8, 16)]
        + [(ROOK, 0), (KNIGHT, 1), (BISHOP, 2), (QUEEN, 3),
           (KING, 4), (BISHOP, 5), (KNIGHT, 6), (ROOK, 7)]
    )
    black_pieces = (
        [(PAWN, sq) for sq in range(48, 56)]
        + [(ROOK, 56), (KNIGHT, 57), (BISHOP, 58), (QUEEN, 59),
           (KING, 60), (BISHOP, 61), (KNIGHT, 62), (ROOK, 63)]
    )

    # Test 1: starting position ≈ 0
    score = simulate_eval(white_pieces, black_pieces)
    print(f"  Startpos eval:           {score:+d} cp  (expect ~0)")
    assert abs(score) < 100, f"Startpos eval too far from 0: {score}"

    # Test 2: White up a queen (remove black queen from d8=59)
    no_bq = [p for p in black_pieces if p != (QUEEN, 59)]
    score = simulate_eval(white_pieces, no_bq)
    print(f"  White +Queen eval:       {score:+d} cp  (expect ~+900)")
    assert score > 400, f"White up a queen should be > 400: {score}"

    # Test 3: White down a rook (remove white rook from h1=7)
    no_wr = [p for p in white_pieces if p != (ROOK, 7)]
    score = simulate_eval(no_wr, black_pieces)
    print(f"  White -Rook eval:        {score:+d} cp  (expect ~-500)")
    assert score < -200, f"White down a rook should be < -200: {score}"

    # Test 4: Perspective flip — same position, black to move
    score_btm = simulate_eval(white_pieces, black_pieces, stm_white=False)
    print(f"  Startpos (black to move): {score_btm:+d} cp  (expect ~0)")
    assert abs(score_btm) < 100, f"Startpos BTM eval too far from 0: {score_btm}"

    print()
    print("  All verification checks passed!")


def main():
    ft_weights, ft_bias, out_weights, out_bias = init_weights()
    ft_q, ft_bias_q, out_q, out_bias_q = quantize(ft_weights, ft_bias, out_weights, out_bias)

    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
    write_nnue(OUTPUT_PATH, ft_q, ft_bias_q, out_q, out_bias_q)

    file_size = os.path.getsize(OUTPUT_PATH)
    print(f"Initialized pyro.nnue with material knowledge")
    print(f"  Path: {os.path.abspath(OUTPUT_PATH)}")
    print(f"  Size: {file_size:,} bytes")
    print(f"  Architecture: {INPUT_SIZE} -> {HIDDEN_SIZE} -> 1")
    print(f"  Quantization: QA={QA}, QB={QB}, SCALE={SCALE}")
    print(f"  Material scaling: DIVISOR={DIVISOR}, out_w=±{OUT_W}")
    print()
    print("Verifying...")
    verify(OUTPUT_PATH)


if __name__ == "__main__":
    main()
