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
BATCH_SIZE        = 256
EPOCHS            = 10
LR_INIT           = 1e-3
LR_FACTOR         = 0.5       # ReduceLROnPlateau factor
LR_PATIENCE       = 2         # epochs without improvement before LR drop
VAL_FRACTION      = 0.05      # 5% held out for validation
NUM_WORKERS       = 0         # set >0 on Linux for faster data loading
POLICY_LOSS_WEIGHT = 0.5      # total_loss = value_loss + weight * policy_loss


def collate(batch):  # type: ignore[no-untyped-def]
    """Custom collate to handle ((board, scalar), score, move_idx) tuples.

    Filters out None items returned by ChessDataset.__getitem__ when
    encode_move fails on an invalid UCI string.
    """
    batch = [item for item in batch if item is not None]
    if not batch:
        return None
    # __getitem__ returns ((board_t, scalar_t), score, move_idx).
    # Flatten to (board_t, scalar_t, score, move_idx) before zipping so the
    # nested tuple doesn't confuse zip's unpacking.
    boards, scalars, scores, move_indices = zip(*[
        (b, s, sc, mi) for (b, s), sc, mi in batch
    ])
    return (
        torch.stack(boards),
        torch.stack(scalars),
        torch.tensor(scores, dtype=torch.float32).unsqueeze(1),
        torch.tensor(move_indices, dtype=torch.long),
    )


def train(csv_path: Path) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train] Device: {device}")
    if torch.cuda.is_available():
        print(f"[train] GPU: {torch.cuda.get_device_name(0)}")

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

    # ── Model, losses, optimiser ─────────────────────────────────────────────
    model = ChessNet().to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[train] ChessNet: {n_params:,} parameters")

    criterion_value  = nn.MSELoss()
    criterion_policy = nn.CrossEntropyLoss()
    optimiser = torch.optim.Adam(model.parameters(), lr=LR_INIT)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimiser, factor=LR_FACTOR, patience=LR_PATIENCE
    )

    # ── Training loop ────────────────────────────────────────────────────────
    best_val_loss = float("inf")
    _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    loss_rows: list[tuple[int, float, float, float, float, float, float]] = []

    for epoch in range(1, EPOCHS + 1):
        t0 = time.monotonic()
        model.train()
        train_value_loss = 0.0
        train_policy_loss = 0.0

        for batch in train_loader:
            if batch is None:
                continue
            boards, scalars, value_targets, policy_targets = batch
            boards         = boards.to(device)
            scalars        = scalars.to(device)
            value_targets  = value_targets.to(device)
            policy_targets = policy_targets.to(device)

            optimiser.zero_grad()
            value, policy = model(boards, scalars)

            v_loss = criterion_value(value, value_targets)
            p_loss = criterion_policy(policy, policy_targets)
            loss   = v_loss + POLICY_LOSS_WEIGHT * p_loss

            loss.backward()
            optimiser.step()

            n = len(value_targets)
            train_value_loss  += v_loss.item() * n
            train_policy_loss += p_loss.item() * n

        train_value_loss  /= n_train
        train_policy_loss /= n_train
        train_total_loss   = train_value_loss + POLICY_LOSS_WEIGHT * train_policy_loss

        # Validation
        model.eval()
        val_value_loss = 0.0
        val_policy_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                if batch is None:
                    continue
                boards, scalars, value_targets, policy_targets = batch
                boards         = boards.to(device)
                scalars        = scalars.to(device)
                value_targets  = value_targets.to(device)
                policy_targets = policy_targets.to(device)

                value, policy = model(boards, scalars)
                n = len(value_targets)
                val_value_loss  += criterion_value(value, value_targets).item() * n
                val_policy_loss += criterion_policy(policy, policy_targets).item() * n

        val_value_loss  /= n_val
        val_policy_loss /= n_val
        val_total_loss   = val_value_loss + POLICY_LOSS_WEIGHT * val_policy_loss

        scheduler.step(val_total_loss)
        elapsed = time.monotonic() - t0
        loss_rows.append((
            epoch,
            train_total_loss, train_value_loss, train_policy_loss,
            val_total_loss,   val_value_loss,   val_policy_loss,
        ))

        print(
            f"[train] Epoch {epoch:2d}/{EPOCHS} | "
            f"train={train_total_loss:.4f} (v={train_value_loss:.2f} p={train_policy_loss:.4f})  "
            f"val={val_total_loss:.4f} (v={val_value_loss:.2f} p={val_policy_loss:.4f}) | "
            f"{elapsed:.1f}s"
        )

        if val_total_loss < best_val_loss:
            best_val_loss = val_total_loss
            torch.save(model.state_dict(), str(_WEIGHTS_PATH))
            print(f"[train]   ✓ saved best model (val_loss={val_total_loss:.4f}) → {_WEIGHTS_PATH}")

    # ── Save loss curves ─────────────────────────────────────────────────────
    _LOSS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOSS_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "epoch",
            "train_loss", "train_value_loss", "train_policy_loss",
            "val_loss",   "val_value_loss",   "val_policy_loss",
        ])
        w.writerows(loss_rows)

    print(f"[train] Training complete. Best val_loss={best_val_loss:.4f}")
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
