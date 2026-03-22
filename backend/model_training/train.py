"""
Train ChessNet on a positions CSV produced by parse.py.

Usage (from backend/):
    python -m model_training.train --csv data/positions.csv

The best validation-loss checkpoint is saved to:
    backend/models/torch_chess.pt

Training progress is printed every epoch.
Loss curves are written to:
    data/loss_curves.csv
"""

import argparse
import csv
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from .architecture import ChessNet
from .dataset import ChessDataset

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "models" / "torch_chess.pt"
_LOSS_CSV     = Path("data/loss_curves.csv")

# ── Hyperparameters ─────────────────────────────────────────────────────────
BATCH_SIZE   = 256
EPOCHS       = 10
LR_INIT      = 1e-3
LR_FACTOR    = 0.5       # ReduceLROnPlateau factor
LR_PATIENCE  = 2         # epochs without improvement before LR drop
VAL_FRACTION = 0.05      # 5% held out for validation
NUM_WORKERS  = 0         # set >0 on Linux for faster data loading


def collate(batch):  # type: ignore[no-untyped-def]
    """Custom collate to handle ((board, scalar), score) tuples."""
    (boards, scalars), scores = zip(*batch)
    return (
        torch.stack(boards),
        torch.stack(scalars),
        torch.tensor(scores, dtype=torch.float32).unsqueeze(1),
    )


def train(csv_path: Path) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train] Device: {device}")

    # ── Dataset split ────────────────────────────────────────────────────────
    full_ds = ChessDataset(csv_path)
    n_val   = max(1, int(len(full_ds) * VAL_FRACTION))
    n_train = len(full_ds) - n_val
    train_ds, val_ds = random_split(full_ds, [n_train, n_val])
    print(f"[train] Dataset: {n_train:,} train / {n_val:,} val")

    train_loader = DataLoader(
        train_ds, batch_size=BATCH_SIZE, shuffle=True,
        collate_fn=collate, num_workers=NUM_WORKERS, pin_memory=(device.type == "cuda"),
    )
    val_loader = DataLoader(
        val_ds, batch_size=BATCH_SIZE, shuffle=False,
        collate_fn=collate, num_workers=NUM_WORKERS,
    )

    # ── Model, loss, optimiser ───────────────────────────────────────────────
    model = ChessNet().to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[train] ChessNet: {n_params:,} parameters")

    criterion = nn.MSELoss()
    optimiser = torch.optim.Adam(model.parameters(), lr=LR_INIT)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimiser, factor=LR_FACTOR, patience=LR_PATIENCE, verbose=True
    )

    # ── Training loop ────────────────────────────────────────────────────────
    best_val_loss = float("inf")
    _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    loss_rows: list[tuple[int, float, float]] = []

    for epoch in range(1, EPOCHS + 1):
        t0 = time.monotonic()
        model.train()
        train_loss = 0.0

        for boards, scalars, targets in train_loader:
            boards  = boards.to(device)
            scalars = scalars.to(device)
            targets = targets.to(device)

            optimiser.zero_grad()
            preds = model(boards, scalars)
            loss  = criterion(preds, targets)
            loss.backward()
            optimiser.step()
            train_loss += loss.item() * len(targets)

        train_loss /= n_train

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for boards, scalars, targets in val_loader:
                boards  = boards.to(device)
                scalars = scalars.to(device)
                targets = targets.to(device)
                preds   = model(boards, scalars)
                val_loss += criterion(preds, targets).item() * len(targets)
        val_loss /= n_val

        scheduler.step(val_loss)
        elapsed = time.monotonic() - t0
        loss_rows.append((epoch, train_loss, val_loss))

        print(
            f"[train] Epoch {epoch:2d}/{EPOCHS} | "
            f"train_loss={train_loss:.2f}  val_loss={val_loss:.2f} | "
            f"{elapsed:.1f}s"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), str(_WEIGHTS_PATH))
            print(f"[train]   ✓ saved best model (val_loss={val_loss:.2f}) → {_WEIGHTS_PATH}")

    # ── Save loss curves ─────────────────────────────────────────────────────
    _LOSS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOSS_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch", "train_loss", "val_loss"])
        w.writerows(loss_rows)

    print(f"[train] Training complete. Best val_loss={best_val_loss:.2f}")
    print(f"[train] Weights → {_WEIGHTS_PATH}")
    print(f"[train] Loss curves → {_LOSS_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ChessNet on labelled positions.")
    parser.add_argument(
        "--csv", type=Path, default=Path("data/positions.csv"),
        help="Positions CSV from parse.py (default: data/positions.csv)"
    )
    args = parser.parse_args()

    if not args.csv.exists():
        import sys
        print(f"[train] ERROR: CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    train(args.csv)


if __name__ == "__main__":
    main()
