"""WDL-clean subset filter — Stage 3 step (c) (July 2026, approved plan §2).

Non-destructive: reads the SF18-relabeled corpus and writes a SUBSET that
drops draw-labeled positions with |white-POV eval| >= threshold (the
"winning-but-drawn" non-conversions, ~14% of draw labels in the pilot).
Eval training uses the FULL corpus; the one-shot WDL retry uses this one.

Usage:
    python -m scripts.filter_wdl_clean --input C:/torch_data/selfplay_v2_sf18.plain \
        --output C:/torch_data/selfplay_v2_sf18_wdlclean.plain
"""

import argparse
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="Drop draw-labeled high-eval positions")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--threshold", type=int, default=400,
                    help="drop draws with |white-POV eval| >= this (default 400)")
    args = ap.parse_args()

    kept = dropped = bad = 0
    t0 = time.time()
    with open(args.input, encoding="utf-8") as fin, \
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            p = line.split("|")
            if len(p) != 3:
                bad += 1
                continue
            try:
                ev = int(p[1].strip())
                rw = float(p[2].strip())
            except ValueError:
                bad += 1
                continue
            if rw == 0.5:
                stm_w = p[0].split()[1] == "w"
                evw = ev if stm_w else -ev
                if abs(evw) >= args.threshold:
                    dropped += 1
                    continue
            fout.write(line)
            kept += 1

    total = kept + dropped
    print(f"done in {(time.time()-t0)/60:.1f} min: kept {kept:,}  "
          f"dropped {dropped:,} ({100*dropped/max(total,1):.2f}%)  bad {bad:,}")
    print("gate: dropped fraction expected 2-6% of corpus; zero non-draw lines dropped by construction")


if __name__ == "__main__":
    main()
