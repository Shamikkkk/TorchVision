"""
Train NNUE on position data with either eval_cp or result labels.

Supported input CSV formats:

  Lichess (eval_cp):          fen, eval_cp
    eval_cp: centipawns, White-positive (e.g. 250.0, -130.0)
    Produced by model_training/stream_parse.py

  Self-play (result):         fen, result
    result: 1.0=White won, 0.5=draw, 0.0=Black won
    Produced by scripts/generate_selfplay.py

Label type is auto-detected from the CSV header -- no flag needed.

Normalisation:
  eval_cp  ->  clamp(eval_cp / 600, -1, 1)  [same scale as ChessNet]
  result   ->  result x 2 - 1               [maps [0,1] -> [-1,1]]
  Both are then negated when it is Black's turn (STM perspective).

Architecture:  NNUEModel  (app/engine/nnue.py)
    768 -> 256 -> 32 -> 32 -> 1   (ClippedReLU activations)
    Two inputs: (STM features, opponent features) each (batch, 768)

Loss:      MSE( output, stm_target )   -- direct regression, no sigmoid

Saves:     backend/models/nnue_selfplay.pt   (best val-loss checkpoint)

Run from backend/:
    # Lichess centipawn data (recommended):
    python scripts/train_nnue_selfplay.py --csv data/lichess_positions.csv

    # Self-play W/D/L data:
    python scripts/train_nnue_selfplay.py --csv data/selfplay_positions.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

# Ensure backend/ is on sys.path so `app` is importable.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import chess  # noqa: E402
from app.engine.nnue import NNUEModel, board_to_features  # noqa: E402

_DEFAULT_CSV    = "data/lichess_positions.csv"
_DEFAULT_OUTPUT = "models/nnue_selfplay.pt"
_BATCH_SIZE     = 2048
_MAX_EPOCHS     = 30
_PATIENCE       = 5
_LR             = 0.001
_VAL_SPLIT      = 0.1
_CP_NORM        = 600.0   # divide eval_cp by this to reach ~[-1, 1]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class NNUEDataset(Dataset[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]):
    """
    Encodes (fen, raw_label) pairs for NNUEModel training.

    Each item: (stm_feat, opp_feat, stm_target)
      stm_feat   -- (768,) float32, side-to-move perspective
      opp_feat   -- (768,) float32, opponent perspective (mirrored)
      stm_target -- float32 scalar in [-1, 1]; positive = STM is winning

    label_type="eval_cp":
        raw_label is centipawns (White-positive).
        Normalised to [-1, 1] via / _CP_NORM, then negated for Black to move.

    label_type="result":
        raw_label is 1.0 / 0.5 / 0.0 (White's result).
        Remapped [0,1] -> [-1,1] via x 2 - 1, then negated for Black to move.

    Using STM-first input order matches NNUEEvaluator's inference convention,
    so saved weights are immediately compatible without any weight surgery.
    """

    def __init__(self, rows: list[tuple[str, float]], label_type: str) -> None:
        self._rows       = rows
        self._label_type = label_type

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(
        self, idx: int
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        fen, raw = self._rows[idx]
        board    = chess.Board(fen)
        wf, bf   = board_to_features(board)   # White-perspective, Black-perspective

        if self._label_type == "eval_cp":
            # Centipawns are White-positive; normalise and clamp to [-1, 1].
            target = max(-1.0, min(1.0, raw / _CP_NORM))
        else:
            # result in {0.0, 0.5, 1.0} from White's perspective -> remap to [-1, 1].
            target = raw * 2.0 - 1.0

        # Convert to STM perspective: negate when Black is to move, because
        # the NNUEEvaluator always returns a score relative to the side to move.
        if board.turn == chess.BLACK:
            target    = -target
            stm_feat, opp_feat = bf, wf
        else:
            stm_feat, opp_feat = wf, bf

        return stm_feat, opp_feat, torch.tensor(target, dtype=torch.float32)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_csv(path: Path) -> tuple[list[tuple[str, float]], str]:
    """
    Read the CSV and detect the label type from the header.

    Returns (rows, label_type) where label_type is "eval_cp" or "result".
    Malformed rows are silently skipped.
    """
    rows: list[tuple[str, float]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        # Detect label column name from header; default to "result" for legacy files.
        label_col  = header[1].strip() if header and len(header) > 1 else "result"
        label_type = "eval_cp" if label_col == "eval_cp" else "result"
        for row in reader:
            if len(row) < 2 or not row[0].strip():
                continue
            try:
                rows.append((row[0].strip(), float(row[1])))
            except ValueError:
                continue
    return rows, label_type


# ---------------------------------------------------------------------------
# Train / eval helpers
# ---------------------------------------------------------------------------

def _run_epoch(
    model: NNUEModel,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer | None,
    device: torch.device,
) -> float:
    """
    Run one train or eval epoch.  Pass optimizer=None for eval.
    Returns mean MSE loss over all samples.

    No sigmoid is applied -- targets are already in [-1, 1] and the model
    output is trained as a direct regression (centipawn-normalised).
    """
    is_train = optimizer is not None
    model.train(is_train)
    total_loss    = 0.0
    total_samples = 0

    ctx = torch.enable_grad() if is_train else torch.no_grad()
    with ctx:
        for stm_feat, opp_feat, target in loader:
            stm_feat = stm_feat.to(device)
            opp_feat = opp_feat.to(device)
            target   = target.to(device)

            output = model(stm_feat, opp_feat).squeeze(1)   # (batch,)
            loss   = F.mse_loss(output, target)              # direct regression

            if is_train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss    += loss.item() * len(target)
            total_samples += len(target)

    return total_loss / total_samples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train NNUEModel on eval_cp (Lichess) or result (self-play) labels."
    )
    parser.add_argument(
        "--csv", default=_DEFAULT_CSV,
        help=f"Input CSV path (default: {_DEFAULT_CSV})",
    )
    parser.add_argument(
        "--output", default=_DEFAULT_OUTPUT,
        help=f"Output weights path (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument("--epochs",   type=int,   default=_MAX_EPOCHS)
    parser.add_argument("--batch",    type=int,   default=_BATCH_SIZE)
    parser.add_argument("--lr",       type=float, default=_LR)
    parser.add_argument("--patience", type=int,   default=_PATIENCE)
    args = parser.parse_args()

    csv_path    = Path(args.csv)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Load and split data
    # ------------------------------------------------------------------
    print(f"Loading {csv_path}...")
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found.")
        sys.exit(1)

    rows, label_type = _load_csv(csv_path)
    if not rows:
        print("ERROR: No valid rows loaded. Check the CSV format.")
        sys.exit(1)

    print(f"Loaded {len(rows):,} positions  |  label type: {label_type} (centipawns)"
          if label_type == "eval_cp"
          else f"Loaded {len(rows):,} positions  |  label type: {label_type} (W/D/L result)")

    random.shuffle(rows)
    val_size   = max(1, int(len(rows) * _VAL_SPLIT))
    val_rows   = rows[:val_size]
    train_rows = rows[val_size:]
    print(f"Split: {len(train_rows):,} train / {len(val_rows):,} val")

    # Sanity-check label distribution
    if label_type == "eval_cp":
        vals = [r for _, r in rows]
        mean_cp = sum(vals) / len(vals)
        clipped = sum(1 for v in vals if abs(v) >= 600)
        print(f"eval_cp stats: mean={mean_cp:.1f}cp  |  clipped (>=600cp): {clipped:,}")
    else:
        wins   = sum(1 for _, r in rows if r == 1.0)
        draws  = sum(1 for _, r in rows if r == 0.5)
        losses = sum(1 for _, r in rows if r == 0.0)
        print(f"Result dist: W={wins:,} D={draws:,} L={losses:,}")

    # ------------------------------------------------------------------
    # DataLoaders -- num_workers=0 avoids Windows multiprocessing issues
    # ------------------------------------------------------------------
    train_loader = DataLoader(
        NNUEDataset(train_rows, label_type),
        batch_size=args.batch, shuffle=True, num_workers=0,
    )
    val_loader = DataLoader(
        NNUEDataset(val_rows, label_type),
        batch_size=args.batch, shuffle=False, num_workers=0,
    )

    # ------------------------------------------------------------------
    # Model, optimiser
    # ------------------------------------------------------------------
    device    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model     = NNUEModel().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    print(f"\nDevice: {device}")
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {param_count:,}")
    print(f"Batch size: {args.batch}  |  LR: {args.lr}  |  Max epochs: {args.epochs}\n")

    # ------------------------------------------------------------------
    # Training loop
    # ------------------------------------------------------------------
    best_val_loss  = float("inf")
    patience_count = 0

    for epoch in range(1, args.epochs + 1):
        train_loss = _run_epoch(model, train_loader, optimizer, device)
        val_loss   = _run_epoch(model, val_loader,   None,      device)

        marker = ""
        if val_loss < best_val_loss:
            best_val_loss  = val_loss
            patience_count = 0
            torch.save(model.state_dict(), output_path)
            marker = " *"
        else:
            patience_count += 1

        patience_str = (
            f"  (patience {patience_count}/{args.patience})"
            if patience_count > 0 else ""
        )
        print(
            f"Epoch {epoch:2d}/{args.epochs} | "
            f"train={train_loss:.4f}  val={val_loss:.4f}"
            f"{marker}{patience_str}"
        )

        if patience_count >= args.patience:
            print(
                f"\nEarly stopping -- no val improvement for {args.patience} epochs."
            )
            break

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\nBest val loss: {best_val_loss:.4f}")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
