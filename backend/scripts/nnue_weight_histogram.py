"""
NNUE weight saturation diagnostic.

Reads:
  - quantised.bin (i16 quantized weights — what the engine loads)
  - raw.bin       (f32 pre-quantization weights — what training produced)

Reports histograms and saturation counts to determine whether the
"bang-bang" weight pattern comes from training dynamics or from
quantization clipping.
"""

import struct
from pathlib import Path

CHECKPOINT_DIR = Path("C:/Users/shami/OneDrive/Documents/torch/bullet/checkpoints/pyro-d2-clip10/pyro-d2-clip10-30")
QUANTISED_PATH = CHECKPOINT_DIR / "quantised.bin"
RAW_PATH       = CHECKPOINT_DIR / "raw.bin"

INPUT_SIZE  = 768
HIDDEN_SIZE = 256
QA = 255
QB = 64

N_FT_W   = INPUT_SIZE * HIDDEN_SIZE   # 196,608
N_FT_B   = HIDDEN_SIZE                # 256
N_OUT_W  = HIDDEN_SIZE * 2            # 512
N_OUT_B  = 1
N_TOTAL  = N_FT_W + N_FT_B + N_OUT_W + N_OUT_B  # 197,377


def load_quantised():
    data = QUANTISED_PATH.read_bytes()
    expected = N_TOTAL * 2
    weights_blob = data[:expected]   # strip footer
    vals = struct.unpack(f"<{N_TOTAL}h", weights_blob)
    off = 0
    ft_w   = list(vals[off:off + N_FT_W]);  off += N_FT_W
    ft_b   = list(vals[off:off + N_FT_B]);  off += N_FT_B
    out_w  = list(vals[off:off + N_OUT_W]); off += N_OUT_W
    out_b  = list(vals[off:off + N_OUT_B]); off += N_OUT_B
    return ft_w, ft_b, out_w, out_b


def load_raw():
    data = RAW_PATH.read_bytes()
    expected = N_TOTAL * 4
    if len(data) < expected:
        return None
    vals = struct.unpack(f"<{N_TOTAL}f", data[:expected])
    off = 0
    ft_w   = list(vals[off:off + N_FT_W]);  off += N_FT_W
    ft_b   = list(vals[off:off + N_FT_B]);  off += N_FT_B
    out_w  = list(vals[off:off + N_OUT_W]); off += N_OUT_W
    out_b  = list(vals[off:off + N_OUT_B]); off += N_OUT_B
    return ft_w, ft_b, out_w, out_b


def stats(vals: list[float]):
    n = len(vals)
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / n
    return n, m, var ** 0.5, min(vals), max(vals)


def hist_int(vals: list[int], lo: int = -127, hi: int = 127, n_bins: int = 10):
    """Histogram with edges from lo to hi inclusive on the last bucket."""
    width = (hi - lo) / n_bins
    bins = [0] * n_bins
    for v in vals:
        if v >= hi:
            bins[-1] += 1
        elif v <= lo:
            bins[0] += 1
        else:
            b = int((v - lo) / width)
            b = max(0, min(n_bins - 1, b))
            bins[b] += 1
    return bins, width


def hist_float(vals: list[float], lo: float, hi: float, n_bins: int = 10):
    width = (hi - lo) / n_bins
    bins = [0] * n_bins
    for v in vals:
        if v >= hi:
            bins[-1] += 1
        elif v <= lo:
            bins[0] += 1
        else:
            b = int((v - lo) / width)
            b = max(0, min(n_bins - 1, b))
            bins[b] += 1
    return bins, width


def print_int_hist(label: str, vals: list[int]):
    n, m, sd, vmin, vmax = stats([float(x) for x in vals])
    bins, width = hist_int(vals, -127, 127, 10)

    n_at_pos127 = sum(1 for v in vals if v >=  127)
    n_at_neg127 = sum(1 for v in vals if v <= -127)
    n_at_extremes = n_at_pos127 + n_at_neg127
    n_zero = sum(1 for v in vals if v == 0)
    n_small = sum(1 for v in vals if abs(v) <= 5)

    print(f"--- {label}  (n={n:,}) ---")
    print(f"  stats: mean={m:+.3f}  stddev={sd:.3f}  min={vmin:.0f}  max={vmax:.0f}")
    print(f"  saturation: at +127 = {n_at_pos127:,} ({100*n_at_pos127/n:.2f}%)   "
          f"at -127 = {n_at_neg127:,} ({100*n_at_neg127/n:.2f}%)   "
          f"total = {n_at_extremes:,} ({100*n_at_extremes/n:.2f}%)")
    print(f"  near-zero: |v|<=5 = {n_small:,} ({100*n_small/n:.2f}%)   "
          f"v==0 = {n_zero:,} ({100*n_zero/n:.2f}%)")
    max_count = max(bins) if max(bins) > 0 else 1
    print(f"  histogram (10 buckets, width={width:.0f}):")
    for i, c in enumerate(bins):
        edge_lo = -127 + i * width
        edge_hi = edge_lo + width
        pct = 100.0 * c / n
        bar_len = int(60 * c / max_count)
        print(f"    [{edge_lo:+5.0f}, {edge_hi:+5.0f}): {c:8,d}  {pct:6.2f}%  {'#' * bar_len}")
    print()


def print_float_hist(label: str, vals: list[float], qa_or_qb: int, sat_label: str):
    """Compare float weights against the quantization saturation point.
    For l0 weights, saturation at +/- (32767 / QA), max representable.
    Actually relevant saturation: post-quantization at +/-127 means float >= 127/scale.
    """
    n, m, sd, vmin, vmax = stats(vals)
    # Where do we saturate at +/- 127 in i16 after quantization?
    # quant = round(float * scale).  saturated to +127 means float >= 126.5/scale.
    # But i16 max is 32767, so the *real* clip is at +/- 32767/scale.
    sat_threshold_127 = 126.5 / qa_or_qb
    sat_threshold_i16 = 32767.0 / qa_or_qb

    n_above_127 = sum(1 for v in vals if abs(v) > sat_threshold_127)
    n_above_i16 = sum(1 for v in vals if abs(v) > sat_threshold_i16)

    # Choose a sensible histogram range
    span = max(abs(vmin), abs(vmax))
    bins, width = hist_float(vals, -span, span, 10)

    print(f"--- {label}  (n={n:,})  scale={qa_or_qb} ---")
    print(f"  stats: mean={m:+.6f}  stddev={sd:.6f}  min={vmin:+.4f}  max={vmax:+.4f}")
    print(f"  i16 saturation thresholds for {sat_label}:")
    print(f"    |float| > {sat_threshold_127:.4f}  ({sat_label} -> ±127): "
          f"{n_above_127:,} ({100*n_above_127/n:.2f}%)")
    print(f"    |float| > {sat_threshold_i16:.4f}  ({sat_label} -> ±32767, hard i16 clip): "
          f"{n_above_i16:,} ({100*n_above_i16/n:.2f}%)")
    max_count = max(bins) if max(bins) > 0 else 1
    print(f"  histogram (10 buckets, width={width:.4f}):")
    for i, c in enumerate(bins):
        edge_lo = -span + i * width
        edge_hi = edge_lo + width
        pct = 100.0 * c / n
        bar_len = int(60 * c / max_count)
        print(f"    [{edge_lo:+8.4f}, {edge_hi:+8.4f}): {c:8,d}  {pct:6.2f}%  {'#' * bar_len}")
    print()


def main():
    print("=" * 78)
    print("QUANTISED WEIGHTS (i16, what the engine loads)")
    print("=" * 78)
    q_ft_w, q_ft_b, q_out_w, q_out_b = load_quantised()
    print_int_hist("ft_weights (l0w, scale=QA=255)", q_ft_w)
    print_int_hist("ft_bias    (l0b, scale=QA=255)", q_ft_b)
    print_int_hist("out_weights (l1w, scale=QB=64)", q_out_w)
    print(f"out_bias (l1b, scale=QA*QB=16320) = {q_out_b[0]}")
    print()

    print("=" * 78)
    print("RAW WEIGHTS (f32, pre-quantization)")
    print("=" * 78)
    raw = load_raw()
    if raw is None:
        print("raw.bin not found or wrong size.")
        return
    r_ft_w, r_ft_b, r_out_w, r_out_b = raw
    print_float_hist("ft_weights (l0w)", r_ft_w, QA, "scale=QA=255")
    print_float_hist("ft_bias    (l0b)", r_ft_b, QA, "scale=QA=255")
    print_float_hist("out_weights (l1w)", r_out_w, QB, "scale=QB=64")
    print(f"out_bias (l1b, raw f32) = {r_out_b[0]:+.6f}")
    print(f"  -> after quantisation by QA*QB=16320 = {round(r_out_b[0] * QA * QB)}")
    print()

    # Sanity check: do raw l1w values match q_out_w / 64?
    print("=" * 78)
    print("ROUND-TRIP CHECK: do quantised values match raw * scale?")
    print("=" * 78)
    n_check = 8
    print(f"out_weights[0:{n_check}]:")
    for i in range(n_check):
        print(f"  raw={r_out_w[i]:+.5f}  raw*QB={r_out_w[i]*QB:+.4f}  "
              f"quantised={q_out_w[i]:+d}  saturated={'Y' if abs(q_out_w[i]) >= 127 else 'n'}")
    print()


if __name__ == "__main__":
    main()
