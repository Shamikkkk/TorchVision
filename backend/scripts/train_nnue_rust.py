"""Train NNUE on self-play data in nnue-pytorch plain text format.

Architecture: 768 → 256×2 → 1 (matches engine/src/nnue.rs)
  - Feature transformer: shared Linear(768, 256)
  - Two perspectives: STM and NSTM, concatenated → 512
  - Output: Linear(512, 1) → scalar
  - Activation: CReLU (clamp 0..1)

Loss: MSE(sigmoid(output), target)
  target = 0.5 * sigmoid(score / 400) + 0.5 * game_result_01

After training, quantizes weights and writes engine/pyro.nnue.

Usage:
  cd backend && source venv/Scripts/activate
  python -m scripts.train_nnue_rust --plain data/selfplay_rust.plain
"""

import argparse
import math
import os
import struct
import sys

import chess
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split


# ---------------------------------------------------------------------------
# Constants (must match engine/src/nnue.rs)
# ---------------------------------------------------------------------------

INPUT_SIZE = 768
HIDDEN_SIZE = 256
QA = 255
QB = 64
SCALE = 400

MAGIC = bytes([0x4E, 0x4E, 0x55, 0x45])  # "NNUE"
VERSION = 1

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(SCRIPT_DIR, "..", "..", "engine")
MODELS_DIR = os.path.join(SCRIPT_DIR, "..", "models")
DEFAULT_PLAIN = os.path.join(SCRIPT_DIR, "..", "data", "selfplay_rust.plain")
DEFAULT_OUTPUT = os.path.join(MODELS_DIR, "nnue_rust.pt")
NNUE_OUTPUT = os.path.join(ENGINE_DIR, "pyro.nnue")


# ---------------------------------------------------------------------------
# Feature encoding (matches engine/src/nnue.rs feature_index)
# ---------------------------------------------------------------------------

def feature_index(color_idx: int, piece_type: int, square: int) -> int:
    """color_idx: 0=friendly, 1=opponent. piece_type: 0-5. square: 0-63."""
    return color_idx * 384 + piece_type * 64 + square


def fen_to_features(fen: str) -> tuple[torch.Tensor, torch.Tensor]:
    """Convert FEN to (white_features, black_features) 768-dim binary tensors."""
    board = chess.Board(fen)
    wf = torch.zeros(INPUT_SIZE, dtype=torch.float32)
    bf = torch.zeros(INPUT_SIZE, dtype=torch.float32)

    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        pt = piece.piece_type - 1  # chess.PAWN=1..chess.KING=6 → 0..5

        # White perspective: friendly=0, opponent=1
        wf[feature_index(color, pt, square)] = 1.0
        # Black perspective: mirror sq, flip color
        bf[feature_index(1 - color, pt, square ^ 56)] = 1.0

    return wf, bf


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def parse_plain_file(path: str) -> list[dict]:
    """Parse nnue-pytorch plain text format into list of position dicts."""
    positions = []
    current = {}

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line == "e":
                if "fen" in current:
                    positions.append(current)
                current = {}
            elif line.startswith("fen "):
                current["fen"] = line[4:]
            elif line.startswith("move "):
                current["move"] = line[5:]
            elif line.startswith("score "):
                current["score"] = int(line[6:])
            elif line.startswith("ply "):
                current["ply"] = int(line[4:])
            elif line.startswith("result "):
                current["result"] = int(line[7:])

    return positions


class NNUEDataset(Dataset):
    """Dataset for NNUE training from parsed plain text positions."""

    def __init__(self, positions: list[dict]):
        self.positions = positions

    def __len__(self):
        return len(self.positions)

    def __getitem__(self, idx):
        pos = self.positions[idx]
        fen = pos["fen"]
        score_cp = pos["score"]       # white-relative centipawns
        result = pos["result"]        # 1=white wins, 0=draw, -1=black wins

        # Parse FEN for side to move
        board = chess.Board(fen)
        white_to_move = board.turn == chess.WHITE

        # Features
        wf, bf = fen_to_features(fen)

        # STM / NSTM perspectives
        if white_to_move:
            stm_feat, nstm_feat = wf, bf
        else:
            stm_feat, nstm_feat = bf, wf

        # WDL interpolation target
        # sigmoid(score / 400) maps cp to [0, 1] (white perspective)
        wdl = 1.0 / (1.0 + math.exp(-score_cp / 400.0))
        game_result_01 = (result + 1.0) / 2.0  # -1→0, 0→0.5, 1→1
        target = 0.5 * wdl + 0.5 * game_result_01

        # Flip to STM perspective: if black to move, target = 1 - target
        if not white_to_move:
            target = 1.0 - target

        return stm_feat, nstm_feat, torch.tensor([target], dtype=torch.float32)


# ---------------------------------------------------------------------------
# Model (768 → 256×2 → 1, matching Rust engine)
# ---------------------------------------------------------------------------

class RustNNUE(nn.Module):
    """768→256→1 NNUE matching engine/src/nnue.rs architecture."""

    def __init__(self):
        super().__init__()
        self.ft = nn.Linear(INPUT_SIZE, HIDDEN_SIZE)   # shared feature transformer
        self.out = nn.Linear(HIDDEN_SIZE * 2, 1)       # output layer

    def forward(self, stm_feat, nstm_feat):
        """
        stm_feat:  (batch, 768) — side-to-move features
        nstm_feat: (batch, 768) — opponent features
        Returns (batch, 1) raw logit (apply sigmoid for probability).
        """
        stm = self.ft(stm_feat).clamp(0.0, 1.0)     # CReLU
        nstm = self.ft(nstm_feat).clamp(0.0, 1.0)    # CReLU
        x = torch.cat([stm, nstm], dim=-1)            # (batch, 512)
        return self.out(x)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args):
    print(f"Loading data from {args.plain}...")
    positions = parse_plain_file(args.plain)
    print(f"Loaded {len(positions):,} positions")

    if len(positions) < 100:
        print("ERROR: Need at least 100 positions to train")
        sys.exit(1)

    dataset = NNUEDataset(positions)

    # 90/10 split
    val_size = max(1, len(dataset) // 10)
    train_size = len(dataset) - val_size
    train_ds, val_ds = random_split(
        dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42),
    )
    print(f"Train: {train_size:,}  Val: {val_size:,}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=0, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    model = RustNNUE().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss()

    os.makedirs(MODELS_DIR, exist_ok=True)
    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, args.epochs + 1):
        # --- Train ---
        model.train()
        train_loss_sum = 0.0
        train_batches = 0

        for stm, nstm, target in train_loader:
            stm, nstm, target = stm.to(device), nstm.to(device), target.to(device)

            output = model(stm, nstm)
            pred = torch.sigmoid(output)
            loss = loss_fn(pred, target)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss_sum += loss.item()
            train_batches += 1

        train_loss = train_loss_sum / max(train_batches, 1)

        # --- Validate ---
        model.eval()
        val_loss_sum = 0.0
        val_batches = 0

        with torch.no_grad():
            for stm, nstm, target in val_loader:
                stm, nstm, target = stm.to(device), nstm.to(device), target.to(device)

                output = model(stm, nstm)
                pred = torch.sigmoid(output)
                loss = loss_fn(pred, target)

                val_loss_sum += loss.item()
                val_batches += 1

        val_loss = val_loss_sum / max(val_batches, 1)

        print(f"Epoch {epoch:3d}/{args.epochs}  "
              f"train_loss={train_loss:.6f}  val_loss={val_loss:.6f}"
              f"{'  *best*' if val_loss < best_val_loss else ''}")

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), DEFAULT_OUTPUT)
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                print(f"Early stopping at epoch {epoch} (patience={args.patience})")
                break

    print(f"\nBest val_loss: {best_val_loss:.6f}")
    print(f"Saved: {os.path.abspath(DEFAULT_OUTPUT)}")
    return DEFAULT_OUTPUT


# ---------------------------------------------------------------------------
# Quantize and export to pyro.nnue
# ---------------------------------------------------------------------------

def export_nnue(model_path: str):
    """Load trained PyTorch weights, quantize, write engine/pyro.nnue."""
    print(f"\nExporting to pyro.nnue...")

    model = RustNNUE()
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model.eval()

    # Extract float weights
    ft_weight = model.ft.weight.detach().numpy()    # (256, 768)
    ft_bias = model.ft.bias.detach().numpy()        # (256,)
    out_weight = model.out.weight.detach().numpy()   # (1, 512)
    out_bias = model.out.bias.detach().numpy()       # (1,)

    # Quantize to i16
    # ft: multiply by QA (accumulator stores values in [0, QA] range)
    ft_w_q = np.clip(np.round(ft_weight * QA), -32768, 32767).astype(np.int16)
    ft_b_q = np.clip(np.round(ft_bias * QA), -32768, 32767).astype(np.int16)
    # out: multiply by QB
    out_w_q = np.clip(np.round(out_weight.flatten() * QB), -32768, 32767).astype(np.int16)
    out_b_q = np.int16(np.clip(np.round(float(out_bias[0]) * QB), -32768, 32767))

    # Write binary file matching engine/src/nnue.rs format:
    #   ft_weights: [INPUT_SIZE][HIDDEN_SIZE] i16 LE
    #   ft_bias:    [HIDDEN_SIZE] i16 LE
    #   out_weights:[HIDDEN_SIZE * 2] i16 LE
    #   out_bias:   i16 LE
    os.makedirs(os.path.dirname(os.path.abspath(NNUE_OUTPUT)), exist_ok=True)

    with open(NNUE_OUTPUT, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", VERSION))

        # ft_weights: Rust reads [input][hidden], PyTorch stores (out, in) = (256, 768)
        # So we need to transpose: write ft_weight.T which is (768, 256)
        ft_w_t = ft_w_q.T  # (768, 256) — now [INPUT_SIZE][HIDDEN_SIZE]
        for row in range(INPUT_SIZE):
            for col in range(HIDDEN_SIZE):
                f.write(struct.pack("<h", int(ft_w_t[row, col])))

        # ft_bias
        for val in ft_b_q:
            f.write(struct.pack("<h", int(val)))

        # out_weights (512 values: first 256 = STM, next 256 = NSTM)
        for val in out_w_q:
            f.write(struct.pack("<h", int(val)))

        # out_bias
        f.write(struct.pack("<h", int(out_b_q)))

    file_size = os.path.getsize(NNUE_OUTPUT)
    print(f"Wrote {os.path.abspath(NNUE_OUTPUT)}")
    print(f"Size: {file_size:,} bytes")

    # Verify file structure
    expected = 4 + 4 + (INPUT_SIZE * HIDDEN_SIZE + HIDDEN_SIZE + HIDDEN_SIZE * 2 + 1) * 2
    assert file_size == expected, f"Size mismatch: {file_size} vs expected {expected}"
    print(f"Format verified: magic + version + {INPUT_SIZE}x{HIDDEN_SIZE} ft + {HIDDEN_SIZE} bias + {HIDDEN_SIZE*2} out + 1 bias")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train NNUE on self-play data")
    parser.add_argument("--plain", type=str, default=DEFAULT_PLAIN,
                        help="Path to .plain training data")
    parser.add_argument("--epochs", type=int, default=30, help="Max epochs")
    parser.add_argument("--batch-size", type=int, default=16384, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--patience", type=int, default=5, help="Early stopping patience")
    parser.add_argument("--no-export", action="store_true", help="Skip pyro.nnue export")
    args = parser.parse_args()

    if not os.path.isfile(args.plain):
        print(f"Data file not found: {args.plain}")
        print("Generate it first: python -m scripts.generate_selfplay_rust --games 10000")
        sys.exit(1)

    model_path = train(args)

    if not args.no_export:
        export_nnue(model_path)


if __name__ == "__main__":
    main()
