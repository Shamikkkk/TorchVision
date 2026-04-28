"""Plain-text summary and diagnostics for a train_metrics_*.csv file.

Usage:
  cd backend
  python -m scripts.plot_train_metrics models/train_metrics_20260430_080000.csv
"""

import csv
import datetime
import io
import statistics
import sys
from pathlib import Path

# Force UTF-8 output — Windows consoles default to cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m scripts.plot_train_metrics <csv_path>")

    path = sys.argv[1]
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        sys.exit(f"File not found: {path}")

    if not rows:
        sys.exit("CSV is empty — no epochs logged yet.")

    epochs        = [int(r["epoch"])          for r in rows]
    train_losses  = [float(r["train_loss"])   for r in rows]
    val_losses    = [float(r["val_loss"])     for r in rows]
    lrs           = [float(r["learning_rate"]) for r in rows]
    epoch_times   = [float(r["epoch_seconds"]) for r in rows]
    wall_clocks   = [r["wall_clock_iso"]      for r in rows]
    pos_seen      = [int(r["positions_seen"]) for r in rows]

    n = len(rows)
    total_seconds = sum(epoch_times)

    # Derive start time from filename if possible; fall back to first wall_clock - duration.
    stem = Path(path).stem
    try:
        ts_str = stem.split("train_metrics_")[1]
        start_dt = datetime.datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
    except (IndexError, ValueError):
        start_dt = (datetime.datetime.fromisoformat(wall_clocks[0])
                    - datetime.timedelta(seconds=epoch_times[0]))

    end_dt = datetime.datetime.fromisoformat(wall_clocks[-1])
    pos_per_epoch = pos_seen[0]

    print(f"\nTraining run : {start_dt:%Y-%m-%d %H:%M:%S} → {end_dt:%Y-%m-%d %H:%M:%S}"
          f"  ({fmt_duration(total_seconds)})")
    print(f"Epochs       : {n}")
    print(f"Positions    : {pos_seen[-1]:,}  ({n} epochs × {pos_per_epoch:,})")
    print(f"Total time   : {fmt_duration(total_seconds)}")
    print()

    # ── Table ──────────────────────────────────────────────────────────
    hdr = f"{'Epoch':>5}  {'train_loss':>10}  {'val_loss':>9}  {'train/val':>9}  {'lr':>8}  {'time':>6}"
    print(hdr)
    print("─" * len(hdr))
    for i in range(n):
        ratio = train_losses[i] / max(val_losses[i], 1e-12)
        print(f"{epochs[i]:>5}  {train_losses[i]:>10.6f}  {val_losses[i]:>9.6f}"
              f"  {ratio:>9.2f}  {lrs[i]:>8.2e}  {epoch_times[i]:>5.0f}s")
    print()

    # ── Summary ────────────────────────────────────────────────────────
    best_idx = val_losses.index(min(val_losses))
    print(f"Final train_loss : {train_losses[-1]:.6f}")
    print(f"Final val_loss   : {val_losses[-1]:.6f}")
    print(f"Best val_loss    : {val_losses[best_idx]:.6f}  (epoch {epochs[best_idx]})")
    if n >= 5:
        last5 = val_losses[-5:]
        pct = (last5[-1] - last5[0]) / max(abs(last5[0]), 1e-12) * 100
        label = "converged" if abs(pct) < 2.0 else "still moving"
        print(f"val_loss Δ last 5 epochs : {pct:+.1f}%  ({label})")
    print()

    # ── Diagnostics ────────────────────────────────────────────────────
    if n < 2:
        print("Diagnostics: need 2+ epochs for trend analysis.")
        return

    print("Diagnostics:")

    # 1. val_loss monotonically decreasing over first half
    half = max(2, n // 2)
    first_half = val_losses[:half]
    regressions = sum(1 for a, b in zip(first_half, first_half[1:]) if b >= a)
    if regressions == 0:
        print(f"  ✓ val_loss decreased monotonically through first {half} epochs")
    else:
        print(f"  ⚠ val_loss had {regressions} non-decreasing step(s) in first {half} epochs")

    # 2. Final train/val ratio
    final_ratio = train_losses[-1] / max(val_losses[-1], 1e-12)
    if 0.5 <= final_ratio <= 2.0:
        print(f"  ✓ Final train/val ratio {final_ratio:.2f} in [0.5, 2.0]  (no overfitting signal)")
    elif final_ratio > 2.0:
        print(f"  ⚠ Final train/val ratio {final_ratio:.2f} > 2.0  (possible overfitting)")
    else:
        print(f"  ⚠ Final train/val ratio {final_ratio:.2f} < 0.5  (possible underfitting)")

    # 3. Epoch time stability (±20% of mean)
    mean_t = statistics.mean(epoch_times)
    lo, hi = min(epoch_times), max(epoch_times)
    if hi <= mean_t * 1.2 and lo >= mean_t * 0.8:
        print(f"  ✓ Epoch time stable  ({lo:.0f}–{hi:.0f}s, mean {mean_t:.0f}s)")
    else:
        print(f"  ⚠ Epoch time drift: {lo:.0f}–{hi:.0f}s  (mean {mean_t:.0f}s)"
              f"  — possible memory pressure or thermal throttling")


if __name__ == "__main__":
    main()
