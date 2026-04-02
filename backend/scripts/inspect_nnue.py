"""
Inspect a trained NNUE model to diagnose evaluation quality.

Checks:
  1. Layer shapes and weight statistics (are weights dead/exploding?)
  2. Evaluation on 10 hand-crafted positions vs tal_style_eval
  3. Correlation analysis on 100 random positions from lichess_positions.csv

Run from backend/:
    python scripts/inspect_nnue.py
    python scripts/inspect_nnue.py --model models/nnue_selfplay.pt
    python scripts/inspect_nnue.py --model models/nnue_selfplay.pt --csv data/lichess_positions.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import torch

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import chess  # noqa: E402
from app.engine.nnue import NNUEModel, board_to_features  # noqa: E402
from app.engine.evaluate import tal_style_eval             # noqa: E402

_DEFAULT_MODEL = "models/nnue_selfplay.pt"
_DEFAULT_CSV   = "data/lichess_positions.csv"
_CP_TRAIN      = 600.0    # scale used during training (eval_cp / 600 = target)
_CP_EVALUATOR  = 1500.0   # scale used by NNUEEvaluator at inference time
_SAMPLE_N      = 100      # positions for correlation analysis

# ---------------------------------------------------------------------------
# Sample positions
# ---------------------------------------------------------------------------

_POSITIONS = [
    ("Starting position",
     "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("After 1.e4 e5",
     "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"),
    ("Middlegame (Ruy Lopez)",
     "r1bqkb1r/pppp1ppp/2n2n2/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("White queen sacrificed for pawn (White hugely losing)",
     "rnb1kbnr/pppp1ppp/8/4p3/4P3/8/PPPPPPPP/RNB1KBNR w KQkq - 0 3"),
    ("White up rook (clearly winning for White)",
     "4k3/8/8/8/8/8/PPPP4/4K2R w K - 0 1"),
    ("White up 3 pawns (endgame)",
     "8/5k2/8/PPP5/8/8/8/4K3 w - - 0 1"),
    ("K+R vs K (White winning endgame)",
     "8/8/8/4k3/8/4K3/8/7R w - - 0 1"),
    ("Stalemate-ish (Black king cornered, White to move)",
     "7k/6Q1/5K2/8/8/8/8/8 w - - 0 1"),
    ("Completely equal pawns endgame",
     "8/pppp4/8/8/8/8/PPPP4/8 w - - 0 1"),
    ("Black massively ahead (4 queens)",
     "qqqq4/qqqq4/8/8/8/8/8/4K3 w - - 0 1"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nnue_raw(model: NNUEModel, board: chess.Board) -> float:
    """Raw model output (normalised units, STM-positive)."""
    wf, bf = board_to_features(board)
    stm, opp = (wf, bf) if board.turn == chess.WHITE else (bf, wf)
    with torch.no_grad():
        return float(model(stm.unsqueeze(0), opp.unsqueeze(0)).item())


def _sep(char: str = "-", width: int = 68) -> None:
    print(char * width)


def _stat_line(name: str, tensor: torch.Tensor) -> None:
    t = tensor.float()
    dead = (t.abs() < 1e-4).sum().item()
    print(
        f"  {name:<20s}  shape={tuple(tensor.shape)}"
        f"  mean={t.mean():.4f}  std={t.std():.4f}"
        f"  min={t.min():.4f}  max={t.max():.4f}"
        f"  near-zero={dead}"
    )


# ---------------------------------------------------------------------------
# Section 1 -- weight statistics
# ---------------------------------------------------------------------------

def inspect_weights(model: NNUEModel) -> None:
    _sep("=")
    print("SECTION 1 -- Layer weight statistics")
    _sep("=")

    layers = [
        ("ft.weight",  model.ft.weight),
        ("ft.bias",    model.ft.bias),
        ("l1.weight",  model.l1.weight),
        ("l1.bias",    model.l1.bias),
        ("l2.weight",  model.l2.weight),
        ("l2.bias",    model.l2.bias),
        ("l3.weight",  model.l3.weight),
        ("l3.bias",    model.l3.bias),
    ]

    total_params = 0
    for name, param in layers:
        _stat_line(name, param.data)
        total_params += param.numel()
    print(f"\n  Total parameters: {total_params:,}")

    # Diagnosis
    print()
    all_weights = torch.cat([p.data.flatten() for _, p in layers])
    global_std = all_weights.std().item()
    global_max = all_weights.abs().max().item()
    near_zero_pct = (all_weights.abs() < 1e-4).float().mean().item() * 100

    print("  Diagnosis:")
    if global_std < 0.01:
        print(f"  [!] Very low std ({global_std:.5f}) -- model may be undertrained or collapsed")
    elif global_std > 5.0:
        print(f"  [!] Very high std ({global_std:.4f}) -- possible training instability")
    else:
        print(f"  [OK] Weight std looks reasonable ({global_std:.4f})")

    if near_zero_pct > 50:
        print(f"  [!] {near_zero_pct:.1f}% of weights near zero -- many dead neurons")
    else:
        print(f"  [OK] {near_zero_pct:.1f}% of weights near zero")

    if global_max > 50:
        print(f"  [!] Max weight magnitude = {global_max:.2f} -- possible explosion")
    else:
        print(f"  [OK] Max weight magnitude = {global_max:.4f}")


# ---------------------------------------------------------------------------
# Section 2 -- sample position evaluation
# ---------------------------------------------------------------------------

def inspect_positions(model: NNUEModel) -> None:
    _sep("=")
    print("SECTION 2 -- Sample position evaluation")
    _sep("=")
    print(
        f"  {'Position':<44s}"
        f"  {'Raw':>7s}"
        f"  {'x600cp':>8s}"
        f"  {'x1500cp':>8s}"
        f"  {'tal_cp':>8s}"
        f"  {'sign_ok':>7s}"
    )
    _sep()

    sign_mismatches = 0
    for label, fen in _POSITIONS:
        try:
            board = chess.Board(fen)
        except ValueError as e:
            print(f"  [BAD FEN] {label}: {e}")
            continue

        raw     = _nnue_raw(model, board)
        cp_600  = raw * _CP_TRAIN
        cp_1500 = raw * _CP_EVALUATOR
        tal_cp  = tal_style_eval(board)

        # Sign agreement: do both agree on who is winning? (ignore near-zero)
        if abs(cp_600) > 10 and abs(tal_cp) > 10:
            sign_ok = (cp_600 > 0) == (tal_cp > 0)
        else:
            sign_ok = None   # too close to call

        sign_str = ("yes" if sign_ok else "NO !!") if sign_ok is not None else "~even"
        if sign_ok is False:
            sign_mismatches += 1

        short_label = label[:43]
        print(
            f"  {short_label:<44s}"
            f"  {raw:>7.4f}"
            f"  {cp_600:>8.1f}"
            f"  {cp_1500:>8.1f}"
            f"  {tal_cp:>8.1f}"
            f"  {sign_str:>7s}"
        )

    print()
    print(f"  Scale note: training used /600, NNUEEvaluator uses x1500 -- 2.5x mismatch!")
    print(f"  Sign mismatches (NNUE vs tal_style_eval): {sign_mismatches}/{len(_POSITIONS)}")
    if sign_mismatches > len(_POSITIONS) // 3:
        print("  [!] High sign-mismatch rate -- NNUE may be predicting backwards")
    else:
        print("  [OK] Sign agreement is acceptable")


# ---------------------------------------------------------------------------
# Section 3 -- correlation on CSV sample
# ---------------------------------------------------------------------------

def inspect_correlation(model: NNUEModel, csv_path: Path, n: int) -> None:
    _sep("=")
    print(f"SECTION 3 -- Correlation analysis ({n} random positions from {csv_path.name})")
    _sep("=")

    if not csv_path.exists():
        print(f"  [SKIP] {csv_path} not found -- skipping correlation analysis.")
        return

    # Load and sample rows
    rows: list[tuple[str, float]] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        label_col = header[1].strip() if header and len(header) > 1 else "result"
        for row in reader:
            if len(row) >= 2 and row[0].strip():
                try:
                    rows.append((row[0].strip(), float(row[1])))
                except ValueError:
                    pass

    if not rows:
        print("  [SKIP] No valid rows found.")
        return

    sample = random.sample(rows, min(n, len(rows)))
    print(f"  Sampling {len(sample)} of {len(rows):,} rows  |  label: {label_col}")
    print()

    nnue_scores: list[float] = []
    tal_scores:  list[float] = []
    csv_labels:  list[float] = []
    sign_agree   = 0
    sign_total   = 0
    parse_errors = 0

    for fen, label in sample:
        try:
            board = chess.Board(fen)
        except ValueError:
            parse_errors += 1
            continue

        raw    = _nnue_raw(model, board)
        nnue_cp = raw * _CP_TRAIN          # use training scale for fair comparison
        tal_cp  = float(tal_style_eval(board))

        nnue_scores.append(nnue_cp)
        tal_scores.append(tal_cp)
        csv_labels.append(label)

        if abs(nnue_cp) > 10 and abs(tal_cp) > 10:
            sign_total += 1
            if (nnue_cp > 0) == (tal_cp > 0):
                sign_agree += 1

    if parse_errors:
        print(f"  FEN parse errors skipped: {parse_errors}")

    n_valid = len(nnue_scores)
    if n_valid < 2:
        print("  [SKIP] Not enough valid positions for statistics.")
        return

    # Mean absolute difference
    mad = sum(abs(a - b) for a, b in zip(nnue_scores, tal_scores)) / n_valid

    # Pearson correlation (manual, no numpy dependency beyond what torch gives)
    def _pearson(xs: list[float], ys: list[float]) -> float:
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
        den_y = sum((y - my) ** 2 for y in ys) ** 0.5
        return num / (den_x * den_y) if den_x * den_y > 0 else 0.0

    corr_nnue_tal = _pearson(nnue_scores, tal_scores)

    # Correlation of NNUE with CSV label
    if label_col == "eval_cp":
        corr_nnue_csv = _pearson(nnue_scores, csv_labels)
        corr_label    = "NNUE vs CSV eval_cp"
    else:
        # result [0,1] -> [-1,1] for comparison
        csv_norm = [v * 2 - 1 for v in csv_labels]
        corr_nnue_csv = _pearson(nnue_scores, csv_norm)
        corr_label    = "NNUE vs CSV result (remapped)"

    sign_pct = sign_agree / sign_total * 100 if sign_total > 0 else 0.0

    # NNUE output range
    nnue_min = min(nnue_scores)
    nnue_max = max(nnue_scores)
    nnue_mean = sum(nnue_scores) / n_valid
    tal_min  = min(tal_scores)
    tal_max  = max(tal_scores)

    print(f"  {'Metric':<40s}  {'Value':>10s}")
    _sep()
    print(f"  {'Positions analysed':<40s}  {n_valid:>10d}")
    print(f"  {'Pearson r (NNUE x600 vs tal_style_eval)':<40s}  {corr_nnue_tal:>10.4f}")
    print(f"  {corr_label:<40s}  {corr_nnue_csv:>10.4f}")
    print(f"  {'Mean absolute difference (cp)':<40s}  {mad:>10.1f}")
    print(f"  {'Sign agreement (|score|>10cp)':<40s}  {sign_pct:>9.1f}%")
    print()
    print(f"  NNUE x600 range : [{nnue_min:.1f}, {nnue_max:.1f}]  mean={nnue_mean:.1f}")
    print(f"  tal_style range : [{tal_min:.1f}, {tal_max:.1f}]")
    print()

    # Diagnosis
    print("  Diagnosis:")
    if abs(corr_nnue_tal) < 0.2:
        print(f"  [!] Very low correlation with tal_style_eval ({corr_nnue_tal:.4f})")
        print("      NNUE is not learning position quality -- check training data/labels")
    elif abs(corr_nnue_tal) < 0.5:
        print(f"  [~] Moderate correlation ({corr_nnue_tal:.4f}) -- room for improvement")
    else:
        print(f"  [OK] Good correlation with tal_style_eval ({corr_nnue_tal:.4f})")

    if abs(corr_nnue_csv) < 0.2:
        print(f"  [!] Low correlation with training labels ({corr_nnue_csv:.4f})")
        print("      Model did not learn from this data -- check loss/normalisation")
    else:
        print(f"  [OK] Correlation with training labels ({corr_nnue_csv:.4f})")

    if sign_pct < 60:
        print(f"  [!] Sign agreement only {sign_pct:.1f}% -- NNUE often wrong on who is winning")
    else:
        print(f"  [OK] Sign agreement {sign_pct:.1f}%")

    if abs(nnue_mean) > 200:
        print(f"  [!] NNUE mean score {nnue_mean:.1f}cp -- strong systematic bias")
    else:
        print(f"  [OK] NNUE mean score {nnue_mean:.1f}cp -- no large systematic bias")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect NNUE weights and evaluate diagnostic positions."
    )
    parser.add_argument(
        "--model", default=_DEFAULT_MODEL,
        help=f"Path to NNUE weights (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--csv", default=_DEFAULT_CSV,
        help=f"CSV for correlation analysis (default: {_DEFAULT_CSV})",
    )
    parser.add_argument(
        "--sample", type=int, default=_SAMPLE_N,
        help=f"Positions to sample for correlation (default: {_SAMPLE_N})",
    )
    args = parser.parse_args()

    model_path = _BACKEND_DIR / args.model
    csv_path   = _BACKEND_DIR / args.csv

    if not model_path.exists():
        print(f"ERROR: model not found at {model_path}")
        sys.exit(1)

    print()
    _sep("=")
    print("NNUE INSPECTOR")
    print(f"  Model : {model_path}")
    print(f"  CSV   : {csv_path}")
    _sep("=")
    print()

    model = NNUEModel()
    state = torch.load(str(model_path), map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    print(f"Loaded {model_path.name}  ({sum(p.numel() for p in model.parameters()):,} params)")
    print()

    inspect_weights(model)
    print()
    inspect_positions(model)
    print()
    inspect_correlation(model, csv_path, args.sample)
    print()
    _sep("=")
    print("Inspection complete.")
    _sep("=")


if __name__ == "__main__":
    main()
