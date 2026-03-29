"""
NNUE training script.

Reads positions.csv (must have 'fen' and 'eval_cp' columns), trains the
768 → 256 → 32 → 32 → 1 network, and saves the best checkpoint to
backend/models/nnue.pt.

Usage (from backend/):
    python -m model_training.train_nnue --csv data/positions.csv

The CSV is produced by model_training.parse or model_training.stream_parse.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ------------------------------------------------------------------
# Ensure backend/ is on sys.path so app.engine.nnue is importable
# when this script is run as  python -m model_training.train_nnue
# ------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import chess                                          # noqa: E402
import pandas as pd                                   # noqa: E402
import torch                                          # noqa: E402
import torch.nn as nn                                 # noqa: E402
from torch.utils.data import DataLoader, Dataset, random_split  # noqa: E402

from app.engine.nnue import NNUEModel, board_to_features  # noqa: E402  # type: ignore[import]

# ------------------------------------------------------------------
# Hyper-parameters
# ------------------------------------------------------------------
_SCALE   = 600.0   # centipawns → normalised target  (matches NNUEEvaluator)
_EPOCHS  = 50
_BATCH   = 4096
_LR      = 1e-3
_OUT     = _BACKEND / "models" / "nnue.pt"


# ------------------------------------------------------------------
# Dataset
# ------------------------------------------------------------------

class NNUEDataset(Dataset):
    """
    Lazy-loading dataset: features are computed on-the-fly in __getitem__
    to avoid holding ~3 GB of pre-computed tensors in RAM.

    Targets are stored in normalised STM-perspective units (÷ 600, sign
    flipped for Black-to-move positions so the model always learns
    'positive = current side is better').
    """

    def __init__(self, fens: list[str], evals: list[float]) -> None:
        self.fens  = fens
        self.evals = evals   # White-perspective, already divided by _SCALE

    def __len__(self) -> int:
        return len(self.fens)

    def __getitem__(
        self, idx: int
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        fen    = self.fens[idx]
        target = self.evals[idx]
        board  = chess.Board(fen)
        wf, bf = board_to_features(board)
        if board.turn == chess.WHITE:
            stm, opp = wf, bf
        else:
            stm, opp = bf, wf
            target   = -target    # flip to STM perspective
        return stm, opp, torch.tensor(target, dtype=torch.float32)


# ------------------------------------------------------------------
# Training loop
# ------------------------------------------------------------------

def _train(csv_path: str) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[nnue] Device: {device}")

    # --- Load and filter data ---
    df = pd.read_csv(csv_path, usecols=["fen", "eval_cp"])
    df.dropna(inplace=True)
    df = df[df["eval_cp"].abs() < 3000]    # drop unreliable extreme evals
    fens  = df["fen"].tolist()
    evals = (df["eval_cp"] / _SCALE).tolist()
    print(f"[nnue] Loaded {len(fens):,} positions from {csv_path}")

    # --- 90 / 10 split ---
    full_ds  = NNUEDataset(fens, evals)
    val_size = max(1, int(len(full_ds) * 0.1))
    trn_size = len(full_ds) - val_size
    trn_ds, val_ds = random_split(full_ds, [trn_size, val_size])
    print(f"[nnue] Train: {trn_size:,}  Val: {val_size:,}")

    trn_loader = DataLoader(trn_ds, batch_size=_BATCH, shuffle=True,  num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=_BATCH, shuffle=False, num_workers=0)

    # --- Model, optimiser, loss ---
    model   = NNUEModel().to(device)
    opt     = torch.optim.Adam(model.parameters(), lr=_LR)
    loss_fn = nn.MSELoss()

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    best_val = float("inf")

    for epoch in range(1, _EPOCHS + 1):
        t0 = time.monotonic()

        # Train
        model.train()
        trn_loss = 0.0
        for stm, opp, targets in trn_loader:
            stm, opp, targets = stm.to(device), opp.to(device), targets.to(device)
            opt.zero_grad()
            preds = model(stm, opp).squeeze(-1)
            loss  = loss_fn(preds, targets)
            loss.backward()
            opt.step()
            trn_loss += loss.item() * len(targets)
        trn_loss /= trn_size

        # Validate
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for stm, opp, targets in val_loader:
                stm, opp, targets = stm.to(device), opp.to(device), targets.to(device)
                preds     = model(stm, opp).squeeze(-1)
                val_loss += loss_fn(preds, targets).item() * len(targets)
        val_loss /= val_size

        elapsed = time.monotonic() - t0
        mem_str = ""
        if torch.cuda.is_available():
            mem = torch.cuda.memory_allocated() / 1024 ** 2
            print(f"[nnue] GPU memory: {mem:.0f}MB")
            mem_str = f" | gpu={mem:.0f}MB"
        print(
            f"[nnue] Epoch {epoch:2d}/{_EPOCHS}"
            f" | train={trn_loss:.4f} val={val_loss:.4f}"
            f" | {elapsed:.0f}s{mem_str}"
        )

        if val_loss < best_val:
            best_val = val_loss
            torch.save(model.state_dict(), str(_OUT))

        torch.cuda.empty_cache()

    print(f"[nnue] Done. Best val={best_val:.4f}  →  {_OUT}")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train NNUE evaluator")
    parser.add_argument("--csv", required=True, help="Path to positions.csv")
    args = parser.parse_args()
    _train(args.csv)
