"""
DIAGNOSTIC F — three read-only checks.
Run from repo root: python backend/scripts/diag_f.py
"""
import numpy as np
from pathlib import Path
import math, sys

HIDDEN = 256
QA = 255.0
QB = 64.0
CLIP = 1.98
SCALE = 400

# ── CHECK 2: SF18 target distribution ──────────────────────────────────────
def check_target_distribution():
    plain = Path("C:/torch_data/selfplay_sf18_d12.plain")
    file_size = plain.stat().st_size
    rng = np.random.RandomState(42)

    scores = []
    # ~10 000 seek points × 200 lines each = ~2M samples
    N_SEEKS = 10_000
    LINES_PER_SEEK = 200

    with open(plain, "r") as f:
        for i in range(N_SEEKS):
            seek_pos = int(rng.randint(0, file_size - 2000))
            f.seek(seek_pos)
            f.readline()  # discard partial line
            for _ in range(LINES_PER_SEEK):
                line = f.readline()
                if not line:
                    break
                parts = line.split(" | ")
                if len(parts) >= 2:
                    try:
                        scores.append(int(parts[1]))
                    except ValueError:
                        pass

    scores = np.array(scores, dtype=np.float32)
    n = len(scores)
    print(f"\n=== CHECK 2: SF18 target distribution (n={n:,}) ===")
    print(f"min={scores.min():.0f}  max={scores.max():.0f}")
    print(f"mean={scores.mean():.1f}  std={scores.std():.1f}")
    ps = np.percentile(scores, [1, 10, 25, 50, 75, 90, 99])
    labels = ["p1","p10","p25","p50","p75","p90","p99"]
    for l, v in zip(labels, ps):
        print(f"  {l}={v:.0f}")

    for thresh in [400, 600, 800, 1000, 2000]:
        frac = float(np.mean(np.abs(scores) > thresh))
        print(f"|eval| > {thresh:4d}cp : {100*frac:5.1f}%")

    # sigmoid saturation
    # sigmoid(x/400) < 0.05 or > 0.95 means |x| > 400*ln(19) ≈ 1168cp
    sat_thresh = SCALE * math.log(19)  # ≈ 1168 cp
    sat = float(np.mean(np.abs(scores) > sat_thresh))
    print(f"sigmoid-saturated (|eval|>{sat_thresh:.0f}cp, sigmoid<0.05 or >0.95): {100*sat:.1f}%")

    # median |target - 0.5| (how far from the decision boundary)
    targets = 1.0 / (1.0 + np.exp(-scores / SCALE))
    med_dist = float(np.median(np.abs(targets - 0.5)))
    mean_dist = float(np.mean(np.abs(targets - 0.5)))
    print(f"median |sigmoid - 0.5| = {med_dist:.3f}  mean = {mean_dist:.3f}")
    return scores

# ── CHECK 3: d1v3-clean raw.bin ──────────────────────────────────────────────
def check_baseline_weights():
    raw_path = Path("bullet/checkpoints/pyro-d1v3/pyro-d1v3-30/raw.bin")
    data = np.fromfile(raw_path, dtype=np.float32)

    n_l0w = int(768 * HIDDEN)    # 196608
    n_l0b = int(HIDDEN)           # 256
    n_l1w = int(2 * HIDDEN)       # 512
    # l1b = 1 scalar

    l0w = data[:n_l0w]
    l0b = data[n_l0w : n_l0w + n_l0b]
    l1w = data[n_l0w + n_l0b : n_l0w + n_l0b + n_l1w]
    l1b_raw = float(data[n_l0w + n_l0b + n_l1w])

    print(f"\n=== CHECK 3: d1v3-clean raw.bin (SB30) ===")
    print(f"l1b (out_bias) raw float : {l1b_raw:.6f}")
    print(f"l1b quantized (×QA×QB)   : {int(round(l1b_raw * QA * QB))}")
    print(f"l1b as % of AdamW clip   : {100*abs(l1b_raw)/CLIP:.1f}%")

    # l1w saturation
    sat_hi = float(np.mean(np.abs(l1w) >= 0.95 * CLIP))
    sat_med = float(np.mean(np.abs(l1w) >= 0.5 * CLIP))
    print(f"\nl1w (out_weights): n={len(l1w)}")
    print(f"  min={l1w.min():.4f}  max={l1w.max():.4f}")
    print(f"  mean={l1w.mean():.4f}  mean_abs={np.abs(l1w).mean():.4f}  std={l1w.std():.4f}")
    print(f"  |w| >= 0.95×clip ({0.95*CLIP:.3f}) : {100*sat_hi:.1f}%  (near-saturated)")
    print(f"  |w| >= 0.50×clip ({0.50*CLIP:.3f}) : {100*sat_med:.1f}%  (above half-clip)")

    # l0w stats
    print(f"\nl0w (ft_weights): n={len(l0w)}")
    print(f"  mean_abs={np.abs(l0w).mean():.4f}  std={l0w.std():.4f}")
    print(f"  |w| >= 0.95×clip ({0.95*CLIP:.3f}) : {100*float(np.mean(np.abs(l0w)>=0.95*CLIP)):.2f}%")
    print(f"  |w| >= 0.50×clip ({0.50*CLIP:.3f}) : {100*float(np.mean(np.abs(l0w)>=0.50*CLIP)):.1f}%")
    print(f"  |w| <= 0.10       : {100*float(np.mean(np.abs(l0w)<=0.10)):.1f}%")

    # l0b (ft_bias) stats
    print(f"\nl0b (ft_bias): n={len(l0b)}")
    print(f"  mean={l0b.mean():.4f}  std={l0b.std():.4f}  min={l0b.min():.4f}  max={l0b.max():.4f}")

    # what max eval the network CAN produce from weight physics
    # max_output_float = 2 * HIDDEN * max_crelu * max_l1w (two perspectives)
    # crelu in [0,1], so max = 2 * 256 * 1.0 * CLIP
    max_output_theoretical = 2 * HIDDEN * 1.0 * CLIP
    print(f"\nTheoretical max float output (2×{HIDDEN}×1.0×{CLIP}): {max_output_theoretical:.1f}")
    print(f"  → in cp (our sigmoid(output/400) loss): {max_output_theoretical:.0f} cp")
    print(f"  → in cp (stock sigmoid(output) loss × SCALE): {max_output_theoretical*SCALE:.0f} cp")

    # mean_abs l1w × HIDDEN (rough expected output for a 'typical' position)
    mean_l1w = float(np.abs(l1w).mean())
    typical_output = 2 * HIDDEN * 0.5 * mean_l1w  # crelu ≈ 0.5 average for active
    print(f"\nTypical float output (2×{HIDDEN}×0.5×mean_abs_l1w={mean_l1w:.4f}): {typical_output:.1f}")
    print(f"  → our cp: {typical_output:.0f}  stock cp: {typical_output*SCALE:.0f}")

    return l1b_raw, l1w, l0w, l0b

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scores = check_target_distribution()
    l1b_raw, l1w, l0w, l0b = check_baseline_weights()

    print("\n=== SCALE MISMATCH SUMMARY ===")
    print(f"Our loss: sigmoid(output/400) → network learns output ≈ eval_cp")
    print(f"Stock loss: output.sigmoid()  → network learns output ≈ eval_cp/400")
    print(f"Our l1w clip: ±{CLIP}  →  max output: ±{2*HIDDEN*1.0*CLIP:.0f} cp")
    print(f"Stock l1w clip: ±{CLIP}  →  max output × SCALE=400: ±{2*HIDDEN*1.0*CLIP*SCALE:.0f} cp")
    print(f"Ratio of representable range: stock/ours = {SCALE:.0f}×")
    print()
    print(f"For a queen (~900cp):")
    print(f"  Our system: needs mean_l1w ≈ {900/(2*HIDDEN*0.5):.2f} → EXCEEDS ±{CLIP} clip")
    print(f"  Stock system: needs mean_l1w ≈ {900/SCALE/(2*HIDDEN*0.5):.4f} → well within ±{CLIP}")
