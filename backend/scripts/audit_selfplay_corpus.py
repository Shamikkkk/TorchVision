"""Corpus auditor for self-play .plain data (Session 2b, July 2026).

Runs the audit battery that caught the v1 corpus defects:
  1. result distribution — position-level AND game-level (draw share,
     white/black balance with binomial significance)
  2. label-inversion check — positions with |white-POV eval| >= threshold
     must agree with the game result (~100%)
  3. fake-draw check — fraction of draw-labeled positions with
     |eval| >= 400 (v1: huge; v2 target: near zero)
  4. variety — distinct boards among early-game positions AND distinct
     game signatures (first-5-recorded-position hash; v1: ~30 for the
     whole corpus, v2 target: ~= number of games)
  5. per-game stats — recorded positions/game, length distribution

Games are detected as contiguous runs (result change or fullmove reset),
which is exact for shard files written game-block-at-a-time.

Usage:
    python -m scripts.audit_selfplay_corpus --input C:/torch_data/selfplay_v2_pilot.shard*.plain
    python -m scripts.audit_selfplay_corpus --input C:/torch_data/selfplay_v2_pilot.shard*.plain --max-lines 500000
"""

import argparse
import glob
import sys
from collections import Counter

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INVERSION_EVAL = 700     # |white-POV eval| above which result must agree
FAKE_DRAW_EVAL = 400     # draw-labeled positions above this are "fake draws"


def parse_line(line):
    p = line.strip().split("|")
    if len(p) != 3:
        return None
    fen = p[0].strip()
    try:
        ev = int(p[1].strip())
        rw = float(p[2].strip())
    except ValueError:
        return None
    fs = fen.split()
    if len(fs) < 6 or fs[1] not in "wb":
        return None
    stm_w = fs[1] == "w"
    fm = int(fs[5]) if fs[5].isdigit() else 0
    return fen, fs[0], stm_w, ev, rw, fm


def main():
    ap = argparse.ArgumentParser(description="Audit a self-play .plain corpus")
    ap.add_argument("--input", required=True, help="path or glob of .plain files")
    ap.add_argument("--max-lines", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    files = sorted(glob.glob(args.input))
    if not files:
        sys.exit(f"no files match {args.input}")
    print(f"auditing {len(files)} file(s)")

    n_pos = 0
    res_pos = Counter()
    inv_checked = inv_bad = 0
    draw_hi_eval = draw_total = 0
    early_boards = Counter()
    game_sigs = Counter()
    game_results = Counter()
    game_lens = []
    bad_lines = 0

    for path in files:
        prev_rw = prev_fm = None
        cur_fens = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if args.max_lines and n_pos >= args.max_lines:
                    break
                rec = parse_line(line)
                if rec is None:
                    bad_lines += 1
                    continue
                fen, board_part, stm_w, ev, rw, fm = rec
                evw = ev if stm_w else -ev
                n_pos += 1
                res_pos[rw] += 1

                if abs(evw) >= INVERSION_EVAL:
                    inv_checked += 1
                    if (evw > 0 and rw == 0.0) or (evw < 0 and rw == 1.0):
                        inv_bad += 1
                if rw == 0.5:
                    draw_total += 1
                    if abs(evw) >= FAKE_DRAW_EVAL:
                        draw_hi_eval += 1
                if fm <= 7:
                    early_boards[board_part + (" w" if stm_w else " b")] += 1

                new_game = prev_rw is not None and (rw != prev_rw or fm < prev_fm - 2)
                if new_game:
                    if len(cur_fens) >= 5:
                        game_sigs[hash(tuple(cur_fens[:5]))] += 1
                        game_results[prev_rw] += 1
                        game_lens.append(len(cur_fens))
                    cur_fens = []
                cur_fens.append(board_part)
                prev_rw, prev_fm = rw, fm
        # flush last game of file
        if len(cur_fens) >= 5 and prev_rw is not None:
            game_sigs[hash(tuple(cur_fens[:5]))] += 1
            game_results[prev_rw] += 1
            game_lens.append(len(cur_fens))

    print(f"\npositions: {n_pos:,}   (bad lines: {bad_lines})")

    print("\n--- 1. result distribution ---")
    for v, name in [(1.0, "white win"), (0.5, "draw"), (0.0, "black win")]:
        print(f"  positions {name:9s}: {res_pos[v]:>10,}  ({100*res_pos[v]/max(n_pos,1):.1f}%)")
    ng = sum(game_results.values())
    w, d, b = game_results[1.0], game_results[0.5], game_results[0.0]
    print(f"  games: {ng:,}  W {w:,} ({100*w/max(ng,1):.1f}%)  "
          f"D {d:,} ({100*d/max(ng,1):.1f}%)  B {b:,} ({100*b/max(ng,1):.1f}%)")
    dec = w + b
    if dec > 0:
        # normal approx binomial test of white share among decisive games
        z = (w - dec / 2) / (0.5 * np.sqrt(dec))
        print(f"  white share of decisive: {100*w/dec:.1f}%  (z = {z:+.2f} vs 50%)")
    draw_share = d / max(ng, 1)
    print(f"  GATE draws<25%: {'PASS' if draw_share < 0.25 else 'FAIL'} ({100*draw_share:.1f}%)")

    print("\n--- 2. label inversions (|white-POV eval| >= "
          f"{INVERSION_EVAL}) ---")
    print(f"  checked {inv_checked:,}  inverted {inv_bad:,}"
          f"  ({100*inv_bad/max(inv_checked,1):.3f}%)")
    print(f"  GATE zero inversions: {'PASS' if inv_bad == 0 else 'FAIL'}")

    print(f"\n--- 3. fake draws (draw label, |eval| >= {FAKE_DRAW_EVAL}) ---")
    print(f"  {draw_hi_eval:,} / {draw_total:,} draw-labeled positions"
          f"  ({100*draw_hi_eval/max(draw_total,1):.2f}%)")
    print(f"  GATE < 2%: {'PASS' if draw_hi_eval < 0.02*max(draw_total,1) else 'FAIL'}")

    print("\n--- 4. variety ---")
    print(f"  early positions (fullmove<=7): {sum(early_boards.values()):,}"
          f"  DISTINCT: {len(early_boards):,}")
    top = early_boards.most_common(1)
    if top:
        print(f"  most-repeated early board: {top[0][1]:,}x")
    print(f"  game signatures: {ng:,}  DISTINCT: {len(game_sigs):,}"
          f"  (ratio {len(game_sigs)/max(ng,1):.3f})")
    reps = [c for c in game_sigs.values() if c > 1]
    print(f"  duplicated signatures: {len(reps):,} (max replay {max(reps) if reps else 1})")
    print(f"  GATE distinct~=games (ratio>0.99): "
          f"{'PASS' if len(game_sigs) > 0.99*max(ng,1) else 'FAIL'}")

    if game_lens:
        gl = np.array(game_lens)
        print(f"\n--- 5. recorded positions per game ---")
        print(f"  mean {gl.mean():.1f}  median {np.median(gl):.0f}  "
              f"p95 {np.percentile(gl,95):.0f}  max {gl.max()}")


if __name__ == "__main__":
    main()
