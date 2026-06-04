"""Diagnose NNUE training issues.

Three checks:
  1. Data distribution: eval and result variance in training data
  2. CReLU saturation: fraction of hidden pre-activations outside [0, 1]
  3. Output distribution: what the trained model actually predicts

Usage:
    cd backend && source venv/Scripts/activate
    python -m scripts.diagnose_saturation
    python -m scripts.diagnose_saturation --plain data/selfplay_d6_combined.plain --n 50000
"""

import argparse
import os
import sys
import random

import numpy as np
import torch
import torch.nn as nn
import chess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, ".."))

# Import shared definitions from trainer
from scripts.train_nnue_rust import (
    RustNNUE, parse_pipe_file, parse_plain_file, _detect_format,
    LOSS_SCALE, LAMBDA, INPUT_SIZE, HIDDEN_SIZE,
    feature_index, EVAL_CLIP, DEFAULT_OUTPUT, DEFAULT_PLAIN
)

MODELS_DIR = os.path.join(SCRIPT_DIR, "..", "models")
DEFAULT_N = 20_000


def sample_lines(path: str, n: int) -> list[str]:
    """Reservoir-sample n lines from a potentially huge file."""
    reservoir = []
    with open(path, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            if len(reservoir) < n:
                reservoir.append(line)
            else:
                j = random.randint(0, i)
                if j < n:
                    reservoir[j] = line
    return reservoir


def parse_sampled_lines(lines: list[str], fmt: str) -> list[dict]:
    positions = []
    for line in lines:
        if fmt == "pipe":
            parts = line.split("|")
            if len(parts) != 3:
                continue
            try:
                fen = parts[0].strip()
                eval_stm = int(parts[1].strip())
                result_white = float(parts[2].strip())
            except ValueError:
                continue
            eval_stm = max(-EVAL_CLIP, min(EVAL_CLIP, eval_stm))
            active_color = fen.split()[1]
            white_to_move = active_color == "w"
            score_white = eval_stm if white_to_move else -eval_stm
            positions.append({
                "fen": fen,
                "score": score_white,
                "eval_stm": eval_stm,
                "result_white": result_white,
                "white_to_move": white_to_move,
            })
    return positions


def check1_data_distribution(positions: list[dict]):
    print("=" * 60)
    print("CHECK 1: Training data distribution")
    print("=" * 60)
    n = len(positions)

    evals = [p["eval_stm"] for p in positions]
    results_stm = []
    for p in positions:
        if p["white_to_move"]:
            results_stm.append(p["result_white"])
        else:
            results_stm.append(1.0 - p["result_white"])

    # WDL targets
    wdl_targets = []
    for p, r_stm in zip(positions, results_stm):
        eval_t = 1.0 / (1.0 + np.exp(-p["eval_stm"] / LOSS_SCALE))
        wdl_t = LAMBDA * eval_t + (1.0 - LAMBDA) * r_stm
        wdl_targets.append(wdl_t)

    evals_arr = np.array(evals)
    results_arr = np.array(results_stm)
    wdl_arr = np.array(wdl_targets)

    print(f"\nSample size: {n:,}")

    print(f"\nEval (STM, centipawns):")
    print(f"  mean={evals_arr.mean():.1f}  std={evals_arr.std():.1f}")
    print(f"  min={evals_arr.min()}  p5={np.percentile(evals_arr,5):.0f}  "
          f"p25={np.percentile(evals_arr,25):.0f}  median={np.median(evals_arr):.0f}  "
          f"p75={np.percentile(evals_arr,75):.0f}  p95={np.percentile(evals_arr,95):.0f}  "
          f"max={evals_arr.max()}")
    print(f"  |eval| <= 50:  {(np.abs(evals_arr)<=50).mean()*100:.1f}%")
    print(f"  |eval| <= 100: {(np.abs(evals_arr)<=100).mean()*100:.1f}%")
    print(f"  |eval| > 500:  {(np.abs(evals_arr)>500).mean()*100:.1f}%")

    print(f"\nResult (STM perspective, 0=loss, 0.5=draw, 1=win):")
    rc = {0.0: 0, 0.5: 0, 1.0: 0}
    for r in results_stm:
        rc[round(r, 1)] = rc.get(round(r, 1), 0) + 1
    for k in sorted(rc):
        print(f"  result={k}: {rc[k]/n*100:.1f}%")
    print(f"  mean={results_arr.mean():.3f}  std={results_arr.std():.3f}")

    print(f"\nWDL target (sigmoid-blended, what the model trains on):")
    print(f"  mean={wdl_arr.mean():.4f}  std={wdl_arr.std():.4f}  "
          f"var={wdl_arr.var():.6f}")
    print(f"  min={wdl_arr.min():.4f}  max={wdl_arr.max():.4f}")
    print(f"  Targets in [0.45, 0.55]: {((wdl_arr>=0.45)&(wdl_arr<=0.55)).mean()*100:.1f}%")
    print(f"  Targets in [0.40, 0.60]: {((wdl_arr>=0.40)&(wdl_arr<=0.60)).mean()*100:.1f}%")

    # If variance is near-zero, loss-near-zero is explained by degenerate data
    if wdl_arr.std() < 0.02:
        print(f"\n  *** WARNING: WDL target std={wdl_arr.std():.4f} < 0.02.")
        print(f"      Nearly all targets cluster at {wdl_arr.mean():.4f}.")
        print(f"      The network can achieve near-zero loss just by outputting a constant.")
        print(f"      This is the DATA DEGENERACY problem, not saturation.")
    elif wdl_arr.std() < 0.05:
        print(f"\n  *** CAUTION: WDL target std={wdl_arr.std():.4f} is low.")
        print(f"      Low variance data makes saturation hard to detect from loss alone.")
    else:
        print(f"\n  Data variance looks healthy (std={wdl_arr.std():.4f}).")

    return wdl_arr


def check2_crelu_saturation(positions: list[dict], model_path: str, device: torch.device):
    print("\n" + "=" * 60)
    print("CHECK 2: CReLU saturation in trained model")
    print("=" * 60)

    if not os.path.isfile(model_path):
        print(f"Model not found: {model_path}")
        print("Skipping saturation check.")
        return None

    model = RustNNUE(material_init=False)
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model = model.to(device)
    model.eval()

    print(f"Loaded: {model_path}")

    # Build feature tensors for sample positions
    batch_size = min(len(positions), 4096)
    sample = random.sample(positions, batch_size)

    stm_feats = torch.zeros(batch_size, INPUT_SIZE)
    nstm_feats = torch.zeros(batch_size, INPUT_SIZE)

    for i, pos in enumerate(sample):
        board = chess.Board(pos["fen"])
        for sq, piece in board.piece_map().items():
            color = 0 if piece.color == chess.WHITE else 1
            pt = piece.piece_type - 1
            widx = feature_index(color, pt, sq)
            bidx = feature_index(1 - color, pt, sq ^ 56)
            stm_feats[i, widx] = 1.0
            nstm_feats[i, bidx] = 1.0

    stm_feats = stm_feats.to(device)
    nstm_feats = nstm_feats.to(device)

    with torch.no_grad():
        stm_pre = model.ft(stm_feats)      # (batch, 256) before CReLU
        nstm_pre = model.ft(nstm_feats)    # (batch, 256) before CReLU
        all_pre = torch.cat([stm_pre, nstm_pre], dim=0).cpu().numpy()  # (2*batch, 256)
        outputs = model(stm_feats, nstm_feats).cpu().numpy()  # (batch, 1)

    total_units = all_pre.size
    saturated_high = (all_pre > 1.0).sum()
    saturated_low = (all_pre < 0.0).sum()
    in_range = total_units - saturated_high - saturated_low

    print(f"\nFT pre-activation analysis ({batch_size} positions × 256 neurons × 2 perspectives):")
    print(f"  Total units: {total_units:,}")
    print(f"  < 0.0 (dead):     {saturated_low:,}  ({saturated_low/total_units*100:.1f}%)")
    print(f"  in [0.0, 1.0]:    {in_range:,}  ({in_range/total_units*100:.1f}%)")
    print(f"  > 1.0 (sat high): {saturated_high:,}  ({saturated_high/total_units*100:.1f}%)")
    print(f"\n  Pre-activation stats:")
    print(f"    mean={all_pre.mean():.4f}  std={all_pre.std():.4f}")
    print(f"    min={all_pre.min():.4f}  max={all_pre.max():.4f}")
    print(f"    p5={np.percentile(all_pre,5):.4f}  p95={np.percentile(all_pre,95):.4f}")

    sat_total = (saturated_high + saturated_low) / total_units * 100
    if sat_total > 50:
        print(f"\n  *** SATURATION CONFIRMED: {sat_total:.1f}% of neurons are outside [0,1].")
        print(f"      Gradient flow is blocked for these neurons.")
        print(f"      This is the primary training failure mode.")
    elif sat_total > 20:
        print(f"\n  *** MODERATE SATURATION: {sat_total:.1f}% of neurons outside [0,1].")
        print(f"      This can impede learning but may not be the primary cause.")
    else:
        print(f"\n  Saturation fraction {sat_total:.1f}% is within normal bounds.")

    # Weight statistics
    ft_w = model.ft.weight.detach().cpu().numpy()
    ft_b = model.ft.bias.detach().cpu().numpy()
    out_w = model.out.weight.detach().cpu().numpy()
    print(f"\nWeight statistics:")
    print(f"  ft.weight: mean={ft_w.mean():.6f}  std={ft_w.std():.6f}  "
          f"max_abs={np.abs(ft_w).max():.6f}")
    print(f"  ft.bias:   mean={ft_b.mean():.6f}  std={ft_b.std():.6f}  "
          f"max_abs={np.abs(ft_b).max():.6f}")
    print(f"  out.weight: mean={out_w.mean():.6f}  std={out_w.std():.6f}  "
          f"max_abs={np.abs(out_w).max():.6f}")

    # Output statistics
    print(f"\nModel output (centipawns, before sigmoid):")
    print(f"  mean={outputs.mean():.2f}  std={outputs.std():.2f}")
    print(f"  min={outputs.min():.2f}  max={outputs.max():.2f}")
    print(f"  Outputs near zero (|out| < 10): {(np.abs(outputs) < 10).mean()*100:.1f}%")
    print(f"  Outputs near zero (|out| < 50): {(np.abs(outputs) < 50).mean()*100:.1f}%")

    sig_out = 1.0 / (1.0 + np.exp(-outputs / LOSS_SCALE))
    print(f"\n  Sigmoid(out/400):")
    print(f"    mean={sig_out.mean():.4f}  std={sig_out.std():.4f}")

    return all_pre, outputs


def check3_qualitative(positions: list[dict], model_path: str, device: torch.device):
    print("\n" + "=" * 60)
    print("CHECK 3: Qualitative eval samples")
    print("=" * 60)

    if not os.path.isfile(model_path):
        return

    model = RustNNUE(material_init=False)
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model = model.to(device)
    model.eval()

    # Test some known positions
    test_fens = [
        ("Starting position",
         "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 0),
        ("White up a queen (~900cp)",
         "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1", 900),
        ("Black up a queen (~-900cp)",
         "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", -900),
        ("White up a rook (~500cp)",
         "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQk - 0 1", 500),
        ("Endgame K+R vs K",
         "8/8/8/3k4/8/3K4/8/7R w - - 0 1", 1000),
    ]

    print(f"\n{'Position':<30} {'Expected(cp)':>12} {'NNUE(cp)':>10} {'Match?'}")
    print("-" * 65)

    for name, fen, expected in test_fens:
        board = chess.Board(fen)
        wf = torch.zeros(INPUT_SIZE)
        bf = torch.zeros(INPUT_SIZE)
        for sq, piece in board.piece_map().items():
            color = 0 if piece.color == chess.WHITE else 1
            pt = piece.piece_type - 1
            wf[feature_index(color, pt, sq)] = 1.0
            bf[feature_index(1 - color, pt, sq ^ 56)] = 1.0

        if board.turn == chess.WHITE:
            stm, nstm = wf.unsqueeze(0), bf.unsqueeze(0)
        else:
            stm, nstm = bf.unsqueeze(0), wf.unsqueeze(0)

        with torch.no_grad():
            out = model(stm.to(device), nstm.to(device)).item()

        direction = "ok" if (expected == 0 and abs(out) < 100) or \
                            (expected > 0 and out > 0) or \
                            (expected < 0 and out < 0) else "WRONG SIGN"
        print(f"{name:<30} {expected:>12}  {out:>10.1f}  {direction}")


def main():
    parser = argparse.ArgumentParser(description="Diagnose NNUE training saturation")
    parser.add_argument("--plain", default=None, help="Path to .plain data file")
    parser.add_argument("--model", default=DEFAULT_OUTPUT, help="Path to trained .pt model")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="Positions to sample")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    data_path = args.plain or DEFAULT_PLAIN
    # Try combined file first
    combined = os.path.join(SCRIPT_DIR, "..", "data", "selfplay_d6_combined.plain")
    if args.plain is None and os.path.isfile(combined):
        data_path = combined
        print(f"Using combined data: {combined}")
    elif not os.path.isfile(data_path):
        print(f"Data not found: {data_path}")
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    print(f"Sampling {args.n:,} positions from {data_path}...")

    fmt = _detect_format(data_path)
    print(f"Format: {fmt}")

    lines = sample_lines(data_path, args.n)
    positions = parse_sampled_lines(lines, fmt)
    print(f"Parsed {len(positions):,} valid positions")

    wdl_arr = check1_data_distribution(positions)
    pre_acts, outputs = check2_crelu_saturation(positions, args.model, device)
    check3_qualitative(positions, args.model, device)

    print("\n" + "=" * 60)
    print("DIAGNOSIS SUMMARY")
    print("=" * 60)

    issues = []
    if wdl_arr is not None and wdl_arr.std() < 0.05:
        issues.append(f"DATA DEGENERACY: WDL std={wdl_arr.std():.4f} (targets clustered near {wdl_arr.mean():.3f})")

    if pre_acts is not None:
        sat_pct = ((pre_acts > 1.0) | (pre_acts < 0.0)).mean() * 100
        if sat_pct > 20:
            issues.append(f"CRELU SATURATION: {sat_pct:.1f}% of neurons saturated")

    if outputs is not None:
        if outputs.std() < 5:
            issues.append(f"COLLAPSED OUTPUT: model std={outputs.std():.2f}cp (outputs ~constant)")

    if issues:
        print("\nProblems found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nNo critical issues found. Consider re-running SPRT.")


if __name__ == "__main__":
    main()
