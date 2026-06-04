"""
Gate A — verify l1w is no longer pinned at ±1.98 after loss-convention change.
Run from repo root: python backend/scripts/gate_a.py
"""
import numpy as np
from pathlib import Path
import sys

HIDDEN = 256
QA = 255.0
QB = 64.0
CLIP = 1.98

def check_weights(label, raw_path):
    data = np.fromfile(raw_path, dtype=np.float32)
    n_l0w = int(768 * HIDDEN)
    n_l0b = HIDDEN
    n_l1w = int(2 * HIDDEN)

    l0w = data[:n_l0w]
    l0b = data[n_l0w : n_l0w + n_l0b]
    l1w = data[n_l0w + n_l0b : n_l0w + n_l0b + n_l1w]
    l1b_raw = float(data[n_l0w + n_l0b + n_l1w])

    print(f"\n=== Gate A: {label} ===")
    print(f"l1w n={len(l1w)}")
    print(f"  min={l1w.min():.4f}  max={l1w.max():.4f}")
    print(f"  mean={l1w.mean():.4f}  mean_abs={np.abs(l1w).mean():.4f}  std={l1w.std():.4f}")
    sat = float(np.mean(np.abs(l1w) >= 0.95 * CLIP))
    print(f"  |w| >= 0.95xclip ({0.95*CLIP:.3f}): {100*sat:.1f}%")
    # Distribution breakdown
    for thresh in [0.01, 0.05, 0.10, 0.50, 1.00, 1.90]:
        frac = float(np.mean(np.abs(l1w) >= thresh))
        print(f"  |w| >= {thresh:.2f}: {100*frac:.1f}%")
    print(f"l1b raw: {l1b_raw:.6f}  (as % of clip: {100*abs(l1b_raw)/CLIP:.1f}%)")
    print(f"l0w mean_abs={np.abs(l0w).mean():.4f}")
    print(f"l0b mean={l0b.mean():.4f}")

    # Pass/fail
    is_binary = sat > 0.90  # old: >90% near-saturated = still binary
    if is_binary:
        print(f"\nGATE A: FAIL — l1w still {100*sat:.0f}% near-saturated. Loss change didn't take.")
        return False
    else:
        print(f"\nGATE A: PASS — l1w no longer pinned ({100*sat:.0f}% near-saturated). Continuous spread confirmed.")
        return True

if __name__ == "__main__":
    expE = Path("bullet/checkpoints/pyro-expE/pyro-expE-30/raw.bin")
    d1v3 = Path("bullet/checkpoints/pyro-d1v3/pyro-d1v3-30/raw.bin")
    check_weights("d1v3-clean (baseline)", d1v3)
    ok = check_weights("pyro-expE-30", expE)
    sys.exit(0 if ok else 1)
