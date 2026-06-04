"""
Diagnostic: target distribution of sigmoid(eval/SCALE) on training data.

Tests whether the loss-function squashing hypothesis explains the
~572cp ceiling on NNUE eval. If a large fraction of training targets
fall in the sigmoid saturation zone (>0.92), the trainer has no
gradient to learn precise values for high evals — which would explain
the observed cap.

Compares SCALE=400 (current) vs SCALE=800 (proposed) on 100K positions.
"""

import math
import random
from pathlib import Path

DATA_PATH = Path("C:/torch_data/selfplay_sf18_d12.plain")
SAMPLE_N = 100_000
MAX_ABS_EVAL = 5000


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def sample_evals(path: Path, n: int, seed: int = 42) -> list[int]:
    """Reservoir-sample n eval_cp values, skipping mate-range."""
    rng = random.Random(seed)
    reservoir: list[int] = []
    seen = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                _fen, eval_str, _wdl = line.split(" | ")
                eval_cp = int(eval_str)
            except ValueError:
                continue
            if abs(eval_cp) > MAX_ABS_EVAL:
                continue
            seen += 1
            if len(reservoir) < n:
                reservoir.append(eval_cp)
            else:
                j = rng.randrange(seen)
                if j < n:
                    reservoir[j] = eval_cp
    return reservoir, seen


def histogram(values: list[float], n_bins: int = 10) -> list[int]:
    bins = [0] * n_bins
    for v in values:
        b = min(int(v * n_bins), n_bins - 1)
        bins[b] += 1
    return bins


def stats(values: list[float]) -> tuple[float, float]:
    n = len(values)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / n
    return m, var ** 0.5


def report(label: str, scale: int, evals: list[int]) -> None:
    targets = [sigmoid(e / scale) for e in evals]
    n = len(targets)

    bins = histogram(targets, 10)
    print(f"--- {label} (SCALE={scale}) ---")
    print("  target_sigmoid histogram (10 buckets):")
    for i, count in enumerate(bins):
        lo, hi = i / 10, (i + 1) / 10
        pct = 100.0 * count / n
        bar = "#" * int(pct / 2)
        print(f"    [{lo:.1f}, {hi:.1f}): {count:6d}  {pct:5.2f}%  {bar}")

    sat_92 = sum(1 for t in targets if t > 0.92) / n
    sat_95 = sum(1 for t in targets if t > 0.95) / n
    sat_98 = sum(1 for t in targets if t > 0.98) / n
    sat_lo_08 = sum(1 for t in targets if t < 0.08) / n
    sat_lo_05 = sum(1 for t in targets if t < 0.05) / n
    sat_lo_02 = sum(1 for t in targets if t < 0.02) / n

    m, sd = stats(targets)
    print(f"  upper saturation: >0.92 = {sat_92*100:5.2f}%   "
          f">0.95 = {sat_95*100:5.2f}%   >0.98 = {sat_98*100:5.2f}%")
    print(f"  lower saturation: <0.08 = {sat_lo_08*100:5.2f}%   "
          f"<0.05 = {sat_lo_05*100:5.2f}%   <0.02 = {sat_lo_02*100:5.2f}%")
    print(f"  total saturation (>0.92 or <0.08) : "
          f"{(sat_92 + sat_lo_08)*100:5.2f}%")
    print(f"  mean = {m:.4f}, stddev = {sd:.4f}")
    print()


def main() -> None:
    print(f"Sampling {SAMPLE_N:,} positions from {DATA_PATH} (skip |eval|>{MAX_ABS_EVAL})...")
    evals, total = sample_evals(DATA_PATH, SAMPLE_N)
    print(f"  Sampled {len(evals):,} from {total:,} candidates")
    print()

    print("Eval distribution (input space, cp):")
    abs_evals = sorted([abs(e) for e in evals])
    n = len(abs_evals)
    print(f"  10th = {abs_evals[n//10]:5d}cp   "
          f"50th = {abs_evals[n//2]:5d}cp   "
          f"90th = {abs_evals[9*n//10]:5d}cp   "
          f"max  = {abs_evals[-1]:5d}cp")
    print()

    report("CURRENT", 400, evals)
    report("PROPOSED", 800, evals)
    report("ALSO_TRY", 600, evals)


if __name__ == "__main__":
    main()
