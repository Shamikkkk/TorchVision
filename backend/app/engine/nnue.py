"""
NNUE (Efficiently Updatable Neural Network) evaluator for Pyro.

Architecture: 768 → 256 → 32 → 32 → 1
  Input : 768 binary features (2 colors × 6 piece types × 64 squares)
  Activation: ClippedReLU (clamp 0–1)
  Output: centipawn score from the side-to-move's perspective, scaled by 1/600

The feature transformer (ft) is shared and applied independently to both
the side-to-move's features and the opponent's features.  The two 256-dim
outputs are concatenated (→ 512) before the dense output layers.

Inference path: pure numpy matmuls — no PyTorch overhead per call.
  After loading, weights are extracted from the PyTorch model as numpy
  arrays.  Each evaluate() call is ~0.05 ms, fast enough for minimax search.

Training path: NNUEModel (PyTorch) is kept alive for train_nnue.py.
  The PyTorch model is never called during search — only the numpy arrays are.

Training:  python -m model_training.train_nnue --csv data/positions.csv
Inference: NNUEEvaluator.evaluate(board) → centipawns (White-positive)
"""

from __future__ import annotations

from pathlib import Path

import chess
import numpy as np
import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Feature encoding
# ---------------------------------------------------------------------------

def feature_index(color: int, piece_type: int, square: int) -> int:
    """
    Map (color, piece_type, square) to a flat feature index in [0, 767].

    color      : 0 = White, 1 = Black
    piece_type : 0-5  (pawn=0 … king=5; python-chess piece_type - 1)
    square     : 0-63 (python-chess square convention, a1=0 … h8=63)
    """
    return color * 384 + piece_type * 64 + square


def board_to_features(board: chess.Board) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Return two 768-dim binary feature tensors (torch, float32).
    Used by the training pipeline (train_nnue.py).
    """
    wf = torch.zeros(768)
    bf = torch.zeros(768)
    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        pt    = piece.piece_type - 1
        wf[feature_index(color, pt, square)]           = 1.0
        bf[feature_index(1 - color, pt, square ^ 56)] = 1.0
    return wf, bf


def board_to_features_numpy(board: chess.Board) -> tuple[np.ndarray, np.ndarray]:
    """
    Return two 768-dim binary feature arrays (numpy float32).
    Used by the fast inference path inside minimax search.
    """
    wf = np.zeros(768, dtype=np.float32)
    bf = np.zeros(768, dtype=np.float32)
    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        pt    = piece.piece_type - 1
        wf[feature_index(color, pt, square)]           = 1.0
        bf[feature_index(1 - color, pt, square ^ 56)] = 1.0
    return wf, bf


# ---------------------------------------------------------------------------
# Network (PyTorch — used for training only)
# ---------------------------------------------------------------------------

def clipped_relu(x: torch.Tensor) -> torch.Tensor:
    return x.clamp(0.0, 1.0)


class NNUEModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.ft = nn.Linear(768, 256)    # feature transformer (shared)
        self.l1 = nn.Linear(512, 32)     # 512 = 256 × 2 perspectives
        self.l2 = nn.Linear(32, 32)
        self.l3 = nn.Linear(32, 1)

    def forward(
        self,
        white_feat: torch.Tensor,
        black_feat: torch.Tensor,
    ) -> torch.Tensor:
        """
        white_feat: (batch, 768) — side-to-move features
        black_feat: (batch, 768) — opponent features
        Returns (batch, 1) score in normalised units (× 600 = centipawns).
        """
        w = clipped_relu(self.ft(white_feat))
        b = clipped_relu(self.ft(black_feat))
        x = torch.cat([w, b], dim=-1)
        x = clipped_relu(self.l1(x))
        x = clipped_relu(self.l2(x))
        return self.l3(x)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

_CP_SCALE = 1500.0


class NNUEEvaluator:
    """
    Loads NNUEModel weights once, extracts them as contiguous numpy arrays,
    and performs inference entirely in numpy — no PyTorch overhead per call.

    The PyTorch model (self.model) is retained in memory for training
    compatibility but is never invoked during search.
    """

    _use_numpy: bool = False

    def __init__(self, model_path: str = "models/nnue.pt") -> None:
        self.model: NNUEModel | None = None
        path = Path(model_path)
        if path.exists():
            # Load on CPU — training script uses its own device selection.
            self.model = NNUEModel()
            self.model.load_state_dict(
                torch.load(str(path), map_location="cpu")
            )
            self.model.eval()
            self._extract_numpy_weights()
            self._use_numpy = True
            print(f"[nnue] Loaded weights from {path} (numpy inference active)")
        else:
            print(f"[nnue] No weights at {path} — evaluator inactive")

    def _extract_numpy_weights(self) -> None:
        """Copy all layer weights/biases to contiguous float32 numpy arrays."""
        assert self.model is not None

        def _w(layer: nn.Linear) -> np.ndarray:
            return np.ascontiguousarray(layer.weight.detach().numpy())

        def _b(layer: nn.Linear) -> np.ndarray:
            return np.ascontiguousarray(layer.bias.detach().numpy())

        self.ft_weight = _w(self.model.ft)   # (256, 768)
        self.ft_bias   = _b(self.model.ft)   # (256,)
        self.l1_weight = _w(self.model.l1)   # (32, 512)
        self.l1_bias   = _b(self.model.l1)   # (32,)
        self.l2_weight = _w(self.model.l2)   # (32, 32)
        self.l2_bias   = _b(self.model.l2)   # (32,)
        self.l3_weight = _w(self.model.l3)   # (1, 32)
        self.l3_bias   = _b(self.model.l3)   # (1,)

    def _numpy_forward(self, wf: np.ndarray, bf: np.ndarray) -> float:
        """
        Pure numpy forward pass.  wf and bf are 1-D float32 arrays of
        length 768 representing the STM and opponent perspectives respectively.

        Returns the raw network output (scalar, normalised units).
        """
        # Feature transformer — shared weights applied to each perspective
        w = np.clip(wf @ self.ft_weight.T + self.ft_bias, 0.0, 1.0)   # (256,)
        b = np.clip(bf @ self.ft_weight.T + self.ft_bias, 0.0, 1.0)   # (256,)
        # Concatenate: side-to-move first
        x = np.concatenate([w, b])                                      # (512,)
        # Output layers
        x = np.clip(x @ self.l1_weight.T + self.l1_bias, 0.0, 1.0)    # (32,)
        x = np.clip(x @ self.l2_weight.T + self.l2_bias, 0.0, 1.0)    # (32,)
        x = x @ self.l3_weight.T + self.l3_bias                        # (1,)
        return float(x[0])

    @property
    def available(self) -> bool:
        return self._use_numpy

    def evaluate(self, board: chess.Board) -> float | None:
        """
        Returns centipawns, White-positive.
        Returns None if no weights are loaded (caller should fall back).
        """
        if not self.available:
            return None
        wf, bf = board_to_features_numpy(board)
        if board.turn == chess.WHITE:
            stm, opp = wf, bf
        else:
            # Side-to-move (Black) goes first; flip perspectives
            stm, opp = bf, wf
        score = self._numpy_forward(stm, opp)
        # Model output is STM-perspective; convert to White-positive centipawns.
        # White-to-move: STM=White, so +cp is already White-positive.
        # Black-to-move: STM=Black, so negate to flip to White-positive.
        cp = score * _CP_SCALE
        return cp if board.turn == chess.WHITE else -cp


# ---------------------------------------------------------------------------
# Global singleton — loaded once at import time
# ---------------------------------------------------------------------------

nnue = NNUEEvaluator(
    model_path=str(Path(__file__).parent.parent.parent / "models" / "nnue.pt")
)
