"""Diagnostic checks 1-3 on .plain files: W/D/L distribution,
side-to-move balance, STM-conditional eval mean/stddev. Also
reservoir-samples N positions for check 4 (separate script).

Streaming, single-pass per file.
"""

import argparse
import math
import random
import sys
import time
from pathlib import Path


def stream_check(path: Path, sample_size: int, sample_path: Path | None) -> dict:
    t0 = time.time()
    total = 0
    skipped = 0
    w_wins = 0
    draws = 0
    b_wins = 0
    other_results = 0
    w2m = 0
    b2m = 0

    # Welford running mean/M2 per side
    w2m_n = 0
    w2m_mean = 0.0
    w2m_m2 = 0.0
    b2m_n = 0
    b2m_mean = 0.0
    b2m_m2 = 0.0

    # Reservoir sample (Algorithm R) — only if requested
    do_sample = sample_path is not None
    reservoir: list[str] = []
    rng = random.Random(0xCAFE)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            s = line.strip()
            if not s:
                skipped += 1
                continue
            parts = s.split("|")
            if len(parts) != 3:
                skipped += 1
                continue
            fen = parts[0].strip()
            try:
                eval_cp = int(parts[1].strip())
                result = float(parts[2].strip())
            except ValueError:
                skipped += 1
                continue

            # Side to move: char after first space in FEN
            try:
                stm_char = fen.split(" ", 2)[1]
            except IndexError:
                skipped += 1
                continue

            # Result tally
            if result == 1.0:
                w_wins += 1
            elif result == 0.5:
                draws += 1
            elif result == 0.0:
                b_wins += 1
            else:
                other_results += 1

            # Side-to-move tally + Welford for that side's eval
            if stm_char == "w":
                w2m += 1
                w2m_n += 1
                d = eval_cp - w2m_mean
                w2m_mean += d / w2m_n
                w2m_m2 += d * (eval_cp - w2m_mean)
            elif stm_char == "b":
                b2m += 1
                b2m_n += 1
                d = eval_cp - b2m_mean
                b2m_mean += d / b2m_n
                b2m_m2 += d * (eval_cp - b2m_mean)

            # Reservoir sampling (FEN only — eval/result re-readable from line if needed)
            if do_sample:
                if len(reservoir) < sample_size:
                    reservoir.append(s)
                else:
                    # total-1 because we want the index of THIS line, 0-based across kept lines
                    idx = rng.randint(0, total - 1)
                    if idx < sample_size:
                        reservoir[idx] = s

            if total % 2_000_000 == 0:
                el = time.time() - t0
                print(f"  [{path.name}] read {total:,} lines  ({total/el:,.0f}/s)",
                      flush=True)

    elapsed = time.time() - t0
    valid = total - skipped

    w2m_var = w2m_m2 / max(1, w2m_n - 1)
    b2m_var = b2m_m2 / max(1, b2m_n - 1)
    w2m_std = math.sqrt(w2m_var)
    b2m_std = math.sqrt(b2m_var)

    if do_sample:
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sample_path, "w", encoding="utf-8") as out:
            for line in reservoir:
                out.write(line + "\n")

    return {
        "path": str(path),
        "total_lines": total,
        "valid_records": valid,
        "skipped": skipped,
        "w_wins": w_wins,
        "draws": draws,
        "b_wins": b_wins,
        "other_results": other_results,
        "w2m": w2m,
        "b2m": b2m,
        "w2m_eval_n": w2m_n,
        "w2m_eval_mean": w2m_mean,
        "w2m_eval_std": w2m_std,
        "b2m_eval_n": b2m_n,
        "b2m_eval_mean": b2m_mean,
        "b2m_eval_std": b2m_std,
        "elapsed_sec": elapsed,
    }


def report(r: dict) -> None:
    print(f"\n=== {r['path']} ===")
    print(f"  Lines read   : {r['total_lines']:,} (skipped {r['skipped']:,})")
    print(f"  Valid recs   : {r['valid_records']:,}")
    print()
    print(f"  CHECK 1 — W/D/L:")
    valid = r['valid_records']
    if valid:
        print(f"    White wins : {r['w_wins']:>14,}  ({100*r['w_wins']/valid:.2f}%)")
        print(f"    Draws      : {r['draws']:>14,}  ({100*r['draws']/valid:.2f}%)")
        print(f"    Black wins : {r['b_wins']:>14,}  ({100*r['b_wins']/valid:.2f}%)")
        if r['other_results']:
            print(f"    Other      : {r['other_results']:>14,}")
        wb = r['w_wins'] + r['b_wins']
        if wb > 0:
            wr = r['w_wins'] / wb
            print(f"    W/B win-rate (excl draws): {100*wr:.2f}% white, {100*(1-wr):.2f}% black")
    print()
    print(f"  CHECK 2 — Side-to-move balance:")
    if valid:
        print(f"    White-to-move : {r['w2m']:>14,}  ({100*r['w2m']/valid:.2f}%)")
        print(f"    Black-to-move : {r['b2m']:>14,}  ({100*r['b2m']/valid:.2f}%)")
        print(f"    W2M / B2M     : {r['w2m']/max(1, r['b2m']):.4f}")
    print()
    print(f"  CHECK 3 — STM-conditional eval (centipawns from STM perspective):")
    print(f"    W2M:  n={r['w2m_eval_n']:>12,}  mean={r['w2m_eval_mean']:>+9.2f} cp  std={r['w2m_eval_std']:>9.2f}")
    print(f"    B2M:  n={r['b2m_eval_n']:>12,}  mean={r['b2m_eval_mean']:>+9.2f} cp  std={r['b2m_eval_std']:>9.2f}")
    print()
    print(f"  Elapsed: {r['elapsed_sec']:.1f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--peseto", default="data/selfplay_d6_combined.plain")
    p.add_argument("--sf18",   default="C:/torch_data/selfplay_sf18_d12.plain")
    p.add_argument("--sample-out", default="C:/torch_data/diag_sample100.txt",
                   help="Reservoir sample output (from PeSTO file) for check 4")
    p.add_argument("--sample-size", type=int, default=100)
    args = p.parse_args()

    p1 = Path(args.peseto)
    p2 = Path(args.sf18)
    sample_out = Path(args.sample_out)

    print(f"Sampling {args.sample_size} positions from {p1.name} for check 4 -> {sample_out}")
    r1 = stream_check(p1, args.sample_size, sample_out)
    r2 = stream_check(p2, 0, None)  # no sampling for sf18

    report(r1)
    report(r2)

    # JSON summary at end for downstream
    import json
    summary = {p1.name: r1, p2.name: r2}
    print()
    print("=== JSON ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
