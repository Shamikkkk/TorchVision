"""
ChessNet — convolutional residual network for chess position evaluation.

Input:
  board_tensor  : (B, 12, 8, 8) float32  — one plane per piece×color
  scalar_tensor : (B,  7)       float32  — side-to-move, castling, ep

Output:
  (B, 1) float32 — centipawn evaluation from White's perspective

Architecture:
  Stem  → 4 ResBlocks → Flatten → concat scalars → MLP head → scalar
  ~1.3 M parameters
"""

import torch
import torch.nn as nn
from torch import Tensor


class _ResBlock(nn.Module):
    """Standard pre-activation residual block with two 3×3 convolutions."""

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: Tensor) -> Tensor:
        return self.relu(self.net(x) + x)


class ChessNet(nn.Module):
    """
    Full evaluation network.

    Call signature:
        score = net(board_tensor, scalar_tensor)   # → (B, 1)
    """

    CHANNELS    = 64
    NUM_BLOCKS  = 4
    SCALAR_DIM  = 7
    HIDDEN      = 256
    HIDDEN2     = 64

    def __init__(self) -> None:
        super().__init__()

        flat_dim = self.CHANNELS * 8 * 8  # 4096
        head_in  = flat_dim + self.SCALAR_DIM  # 4103

        # Convolutional stem
        self.stem = nn.Sequential(
            nn.Conv2d(12, self.CHANNELS, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(self.CHANNELS),
            nn.ReLU(inplace=True),
        )

        # Residual tower
        self.res_blocks = nn.Sequential(
            *[_ResBlock(self.CHANNELS) for _ in range(self.NUM_BLOCKS)]
        )

        # MLP head
        self.head = nn.Sequential(
            nn.Linear(head_in, self.HIDDEN),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(self.HIDDEN, self.HIDDEN2),
            nn.ReLU(inplace=True),
            nn.Linear(self.HIDDEN2, 1),
        )

    def forward(self, board: Tensor, scalars: Tensor) -> Tensor:
        x = self.stem(board)            # (B, 64, 8, 8)
        x = self.res_blocks(x)          # (B, 64, 8, 8)
        x = x.flatten(start_dim=1)      # (B, 4096)
        x = torch.cat([x, scalars], dim=1)  # (B, 4103)
        return self.head(x)             # (B, 1)
