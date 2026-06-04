"""
NNUE training-set fit diagnostic.

Samples random positions from selfplay_sf18_d12.plain, compares the SF18
eval (already in the file) to the Python static NNUE eval. This is the
SAME inference path that nnue_verify.py uses — pure NNUE static eval,
no engine, no search, no depth-1 noise.

Goal: distinguish capacity bottleneck from inference noise.

If the network fits training data well (high correlation, low MAE), the
±127 weight saturation is NOT a capacity problem — it's an inference-time
phenomenon (e.g., search/eval mismatch, quantization, etc.) and going to
512 neurons won't help.

If the network can't fit its own training data, capacity IS limiting.
"""

import random
import struct
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent.parent
NNUE_PATH = ROOT / "engine" / "pyro.nnue"
DATA_PATH = Path("C:/torch_data/selfplay_sf18_d12.plain")

HIDDEN_SIZE = 256
INPUT_SIZE = 768
QA = 255
QB = 64

MAGIC = b"\x4E\x4E\x55\x45"

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 0, 1, 2, 3, 4, 5

PIECE_MAP = {
    'P': (PAWN, True), 'N': (KNIGHT, True), 'B': (BISHOP, True),
    'R': (ROOK, True), 'Q': (QUEEN, True), 'K': (KING, True),
    'p': (PAWN, False), 'n': (KNIGHT, False), 'b': (BISHOP, False),
    'r': (ROOK, False), 'q': (QUEEN, False), 'k': (KING, False),
}


# ── NNUE loading & eval (copied from nnue_verify.py) ────────────────────

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
    stm = white_acc if side_to_move else black_acc
    nstm = black_acc if side_to_move else white_acc
    output = out_bias
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, stm[i])) * out_weights[i]
    for i in range(HIDDEN_SIZE):
        output += max(0, min(QA, nstm[i])) * out_weights[HIDDEN_SIZE + i]
    return output // (QA * QB)


# ── FEN parsing ─────────────────────────────────────────────────────────

def parse_fen(fen: str):
    """Return (pieces, side_to_move) where pieces=[(sq, piece_type, is_white), ...]"""
    parts = fen.split()
    placement, stm_str = parts[0], parts[1]

    pieces = []
    rank = 7  # FEN starts with rank 8
    file = 0
    for ch in placement:
        if ch == '/':
            rank -= 1
            file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = rank * 8 + file
            pt, is_white = PIECE_MAP[ch]
            pieces.append((sq, pt, is_white))
            file += 1

    side_to_move = (stm_str == 'w')
    return pieces, side_to_move


# ── Reservoir sampling over a streamed file ─────────────────────────────

def sample_positions(path: Path, n: int, max_abs_eval: int = 5000, seed: int = 42):
    """Reservoir-sample n positions, skipping |eval| > max_abs_eval."""
    rng = random.Random(seed)
    reservoir: list[tuple[str, int]] = []
    seen = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                fen, eval_str, _wdl = line.split(" | ")
                eval_cp = int(eval_str)
            except ValueError:
                continue
            if abs(eval_cp) > max_abs_eval:
                continue

            seen += 1
            if len(reservoir) < n:
                reservoir.append((fen, eval_cp))
            else:
                j = rng.randrange(seen)
                if j < n:
                    reservoir[j] = (fen, eval_cp)

    return reservoir, seen


# ── Statistics ──────────────────────────────────────────────────────────

def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print(f"Loading NNUE: {NNUE_PATH}")
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NNUE_PATH)
    print(f"  HIDDEN_SIZE={HIDDEN_SIZE}, out_bias={out_bias}")
    print()

    print(f"Sampling 1000 positions from {DATA_PATH} (skip |eval|>5000)...")
    samples, total_seen = sample_positions(DATA_PATH, n=1000)
    print(f"  Reservoir filled from {total_seen:,} candidate positions")
    print()

    sf_evals: list[int] = []
    nnue_evals: list[int] = []
    errors: list[int] = []  # nnue - sf (signed)

    for fen, sf_eval in samples:
        pieces, stm = parse_fen(fen)
        white_acc, black_acc = make_accumulator(ft_weights, ft_bias, pieces)
        nnue_eval = evaluate(white_acc, black_acc, out_weights, out_bias, stm)
        sf_evals.append(sf_eval)
        nnue_evals.append(nnue_eval)
        errors.append(nnue_eval - sf_eval)

    n = len(sf_evals)
    abs_errors = [abs(e) for e in errors]

    corr = pearson([float(x) for x in sf_evals], [float(x) for x in nnue_evals])
    mae = mean(abs_errors)
    me_signed = mean(errors)

    print("=" * 70)
    print(f"Fit metrics over {n} positions:")
    print(f"  Pearson correlation       : {corr:+.4f}")
    print(f"  Mean absolute error (MAE) : {mae:7.1f} cp")
    print(f"  Mean signed error         : {me_signed:+7.1f} cp   (NNUE - SF18)")
    print()

    sf_abs = [abs(x) for x in sf_evals]
    nn_abs = [abs(x) for x in nnue_evals]

    print("Eval magnitude distribution (|cp|):")
    print(f"                  10th       50th       90th       max")
    print(f"  SF18 evals : {percentile(sf_abs, 0.1):7.0f}  {percentile(sf_abs, 0.5):7.0f}  "
          f"{percentile(sf_abs, 0.9):7.0f}  {max(sf_abs):7.0f}")
    print(f"  NNUE evals : {percentile(nn_abs, 0.1):7.0f}  {percentile(nn_abs, 0.5):7.0f}  "
          f"{percentile(nn_abs, 0.9):7.0f}  {max(nn_abs):7.0f}")
    print()

    print("Error distribution (|NNUE - SF18|):")
    print(f"                  10th       50th       90th       max")
    print(f"             : {percentile(abs_errors, 0.1):7.0f}  {percentile(abs_errors, 0.5):7.0f}  "
          f"{percentile(abs_errors, 0.9):7.0f}  {max(abs_errors):7.0f}")
    print()

    # Interpretation
    print("=" * 70)
    print("Interpretation:")
    fits_well = corr > 0.85 and mae < 150 and abs(me_signed) < 30
    cant_fit  = corr < 0.7 or mae > 250
    has_bias  = corr > 0.7 and abs(me_signed) > 50

    if fits_well:
        print("  ✓ Network fits training data well (high corr, low MAE, small bias).")
        print("    Capacity is NOT the bottleneck. The depth-1 +492cp problem is")
        print("    inference-time noise (search/eval mismatch, quantization slack,")
        print("    or saturation creating spiky landscape). 512 neurons won't fix")
        print("    this directly.")
    elif cant_fit:
        print("  ✗ Network can't fit its own training data.")
        print("    Capacity IS limiting. Going to 512 neurons is justified.")
    elif has_bias:
        print(f"  ! Network correlates with SF18 but has systematic bias of "
              f"{me_signed:+.0f}cp.")
        print("    This is a calibration issue, not pure capacity.")
    else:
        print("  Mixed signals. Inspect the distribution above.")


if __name__ == "__main__":
    main()
