"""Train NNUE from self-play (.plain) or Stockfish-labeled CSV data.

Architecture: 768 -> 256x2 -> 1 (matches engine/src/nnue.rs)
  - Feature transformer: shared Linear(768, 256)
  - Two perspectives: STM and NSTM, concatenated -> 512
  - Output: Linear(512, 1) -> raw centipawns
  - Activation: CReLU (clamp 0..1)

Loss: MSE(output, target_cp)
  target_cp = score_cp (STM-relative centipawns)

After training, quantizes weights and writes engine/pyro.nnue.

Usage:
  cd backend && source venv/Scripts/activate
  python -m scripts.train_nnue_rust --plain data/selfplay_rust.plain
  python -m scripts.train_nnue_rust --csv data/lichess_positions.csv
"""

import argparse
import csv
import math
import os
import struct
import sys

import chess
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, random_split


# ---------------------------------------------------------------------------
# Constants (must match engine/src/nnue.rs)
# ---------------------------------------------------------------------------

INPUT_SIZE = 768
HIDDEN_SIZE = 256
QA = 255
QB = 64
SCALE = 400.0

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


def fen_to_features(fen) -> tuple[torch.Tensor, torch.Tensor]:
    """Convert FEN to (white_features, black_features) 768-dim binary tensors."""
    if isinstance(fen, str):
        board = chess.Board(fen)
    else:
        board = fen
    wf = torch.zeros(INPUT_SIZE, dtype=torch.float32)
    bf = torch.zeros(INPUT_SIZE, dtype=torch.float32)

    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        pt = piece.piece_type - 1  # chess.PAWN=1..chess.KING=6 -> 0..5

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


EVAL_CLIP = 2000  # clamp eval_cp to [-2000, 2000]


def parse_csv_file(path: str) -> list[dict]:
    """Parse CSV with fen,eval_cp columns (Stockfish centipawn labels)."""
    positions = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            score = float(row["eval_cp"])
            score = max(-EVAL_CLIP, min(EVAL_CLIP, score))
            positions.append({"fen": row["fen"], "score": int(score)})
    return positions


MAX_PIECES = 32  # max active features per perspective


def fen_to_indices(fen: str) -> tuple[np.ndarray, np.ndarray, bool]:
    """Convert FEN to (white_indices, black_indices, white_to_move).

    Returns arrays of active feature indices (padded to MAX_PIECES with -1).
    Much more memory-efficient than dense 768-dim tensors.
    """
    board = chess.Board(fen)
    w_idx = []
    b_idx = []

    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        pt = piece.piece_type - 1

        w_idx.append(feature_index(color, pt, square))
        b_idx.append(feature_index(1 - color, pt, square ^ 56))

    # Pad to MAX_PIECES with -1
    while len(w_idx) < MAX_PIECES:
        w_idx.append(-1)
    while len(b_idx) < MAX_PIECES:
        b_idx.append(-1)

    return (np.array(w_idx[:MAX_PIECES], dtype=np.int16),
            np.array(b_idx[:MAX_PIECES], dtype=np.int16),
            board.turn == chess.WHITE)


class NNUEDataset(Dataset):
    """Dataset for NNUE training — pre-computes sparse feature indices."""

    def __init__(self, positions: list[dict]):
        n = len(positions)
        # Store sparse indices (int16) and targets — ~0.3GB for 5M positions
        self.stm_indices = np.zeros((n, MAX_PIECES), dtype=np.int16)
        self.nstm_indices = np.zeros((n, MAX_PIECES), dtype=np.int16)
        self.targets = np.zeros(n, dtype=np.float32)

        for i, pos in enumerate(positions):
            w_idx, b_idx, white_to_move = fen_to_indices(pos["fen"])
            score_cp = pos["score"]  # white-relative centipawns

            if white_to_move:
                self.stm_indices[i] = w_idx
                self.nstm_indices[i] = b_idx
                self.targets[i] = score_cp  # already STM-relative
            else:
                self.stm_indices[i] = b_idx
                self.nstm_indices[i] = w_idx
                self.targets[i] = -score_cp  # flip for black STM

            if (i + 1) % 500_000 == 0:
                print(f"  Encoded {i+1:,}/{n:,} positions...", flush=True)

        print(f"  Encoded all {n:,} positions", flush=True)

    def __len__(self):
        return len(self.targets)

    def __getitem__(self, idx):
        # Return sparse indices + target — collate_fn builds dense tensors
        return (self.stm_indices[idx], self.nstm_indices[idx],
                self.targets[idx])


def collate_sparse(batch):
    """Custom collate: convert sparse indices to dense feature tensors (vectorized)."""
    stm_idx, nstm_idx, targets = zip(*batch)
    bsz = len(batch)

    # Stack into (bsz, MAX_PIECES) arrays
    stm_arr = np.stack(stm_idx)    # (bsz, 32) int16
    nstm_arr = np.stack(nstm_idx)  # (bsz, 32) int16

    stm_feat = torch.zeros(bsz, INPUT_SIZE, dtype=torch.float32)
    nstm_feat = torch.zeros(bsz, INPUT_SIZE, dtype=torch.float32)
    tgt = torch.tensor(targets, dtype=torch.float32).unsqueeze(1)

    # Vectorized scatter: create row indices and valid column indices
    rows = np.repeat(np.arange(bsz), MAX_PIECES)
    stm_flat = stm_arr.flatten().astype(np.int32)
    nstm_flat = nstm_arr.flatten().astype(np.int32)

    # Mask out padding (-1)
    stm_valid = stm_flat >= 0
    nstm_valid = nstm_flat >= 0

    stm_feat[rows[stm_valid], stm_flat[stm_valid]] = 1.0
    nstm_feat[rows[nstm_valid], nstm_flat[nstm_valid]] = 1.0

    return stm_feat, nstm_feat, tgt


# ---------------------------------------------------------------------------
# Model (768 -> 256x2 -> 1, matching Rust engine)
# ---------------------------------------------------------------------------

PIECE_VALUES = {0: 100, 1: 320, 2: 330, 3: 500, 4: 900, 5: 0}  # P N B R Q K
DIVISOR = 5000.0


class RustNNUE(nn.Module):
    """768->256->1 NNUE matching engine/src/nnue.rs architecture."""

    def __init__(self, material_init: bool = True):
        super().__init__()
        self.ft = nn.Linear(INPUT_SIZE, HIDDEN_SIZE)   # shared feature transformer
        self.out = nn.Linear(HIDDEN_SIZE * 2, 1)       # output layer
        nn.init.zeros_(self.out.bias)

        if material_init:
            self._init_material_weights()

    def _init_material_weights(self):
        """Initialize ft weights with material knowledge (like init_nnue_weights.py).

        Each piece feature gets a uniform weight across all hidden neurons
        proportional to its material value / DIVISOR. Small noise breaks symmetry.
        Output weights: STM positive, NSTM negative.
        """
        with torch.no_grad():
            self.ft.weight.zero_()
            self.ft.bias.zero_()

            for color_idx in range(2):
                sign = 1.0 if color_idx == 0 else -1.0
                for pt in range(6):
                    val = PIECE_VALUES[pt] * sign / DIVISOR
                    for sq in range(64):
                        feat_idx = color_idx * 384 + pt * 64 + sq
                        self.ft.weight[:, feat_idx] = val

            # Small noise to break symmetry
            self.ft.weight.add_(torch.randn_like(self.ft.weight) * 0.005)

            # Output weights: DIVISOR / HIDDEN_SIZE
            # ft outputs piece_val/DIVISOR per neuron, 256 neurons sum to
            # 256 * piece_val/DIVISOR.  We need out_w * that = piece_val,
            # so out_w = DIVISOR / 256 = 19.53.
            out_float = DIVISOR / HIDDEN_SIZE
            self.out.weight.zero_()
            self.out.weight[0, :HIDDEN_SIZE] = out_float    # STM positive
            self.out.weight[0, HIDDEN_SIZE:] = -out_float   # NSTM negative
            self.out.bias.zero_()

    def forward(self, stm_feat, nstm_feat):
        """
        stm_feat:  (batch, 768) -- side-to-move features
        nstm_feat: (batch, 768) -- opponent features
        Returns (batch, 1) raw centipawn-scale output.
        """
        stm = self.ft(stm_feat).clamp(0.0, 1.0)     # CReLU
        nstm = self.ft(nstm_feat).clamp(0.0, 1.0)    # CReLU
        x = torch.cat([stm, nstm], dim=-1)            # (batch, 512)
        return self.out(x)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args):
    if args.csv:
        print(f"Loading CSV from {args.csv}...", flush=True)
        positions = parse_csv_file(args.csv)
    else:
        print(f"Loading data from {args.plain}...", flush=True)
        positions = parse_plain_file(args.plain)
    print(f"Loaded {len(positions):,} positions", flush=True)

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
    print(f"Train: {train_size:,}  Val: {val_size:,}", flush=True)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=0, drop_last=True, collate_fn=collate_sparse)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=0, collate_fn=collate_sparse)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}", flush=True)

    if args.resume and os.path.isfile(DEFAULT_OUTPUT):
        print(f"Resuming from {DEFAULT_OUTPUT}", flush=True)
        model = RustNNUE(material_init=False)
        model.load_state_dict(torch.load(DEFAULT_OUTPUT, map_location="cpu", weights_only=True))
        model = model.to(device)
    else:
        print("Initializing with material knowledge", flush=True)
        model = RustNNUE(material_init=True).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

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
            loss = F.mse_loss(output, target)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1000.0)
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
                loss = F.mse_loss(output, target)

                val_loss_sum += loss.item()
                val_batches += 1

        val_loss = val_loss_sum / max(val_batches, 1)

        print(f"Epoch {epoch:3d}/{args.epochs}  "
              f"train_loss={train_loss:.6f}  val_loss={val_loss:.6f}"
              f"{'  *best*' if val_loss < best_val_loss else ''}", flush=True)

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
    # NOTE: Rust eval does output / (QA * QB) (no SCALE multiply)
    # because our model outputs centipawns directly
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
        ft_w_t = ft_w_q.T  # (768, 256) -- now [INPUT_SIZE][HIDDEN_SIZE]
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
    parser = argparse.ArgumentParser(description="Train NNUE on self-play or Stockfish data")
    parser.add_argument("--plain", type=str, default=None,
                        help="Path to .plain training data")
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to CSV with fen,eval_cp columns")
    parser.add_argument("--epochs", type=int, default=30, help="Max epochs")
    parser.add_argument("--batch-size", type=int, default=16384, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--patience", type=int, default=5, help="Early stopping patience")
    parser.add_argument("--resume", action="store_true", help="Resume from existing nnue_rust.pt")
    parser.add_argument("--no-export", action="store_true", help="Skip pyro.nnue export")
    args = parser.parse_args()

    if not args.csv and not args.plain:
        args.plain = DEFAULT_PLAIN

    data_path = args.csv or args.plain
    if not os.path.isfile(data_path):
        print(f"Data file not found: {data_path}")
        sys.exit(1)

    model_path = train(args)

    if not args.no_export:
        export_nnue(model_path)


if __name__ == "__main__":
    main()
