"""
ChessNet — convolutional residual network for chess position evaluation.

Input:
  board_tensor  : (B, 21, 8, 8) float32  — AlphaZero-style input planes
  scalar_tensor : (B,  7)       float32  — side-to-move, castling, ep

Output:
  value  : (B, 1)    float32 — centipawn evaluation from White's perspective
  policy : (B, 4672) float32 — raw move logits (apply softmax externally)

Architecture:
  Stem → 8 ResBlocks → two heads:
    Value head  : Flatten → concat scalars → MLP → scalar
    Policy head : Conv2d(64→2, 1×1) → BN → ReLU → Flatten → Linear(128→4672)
  ~2.1 M parameters

Move encoding (AlphaZero, 4672 = 64 squares × 73 planes):
  Planes  0–55 : queen-type moves (8 directions × 7 distances)
  Planes 56–63 : knight moves (8 offsets)
  Planes 64–72 : underpromotions (3 directions × 3 pieces: R/B/N)
  Index = from_square * 73 + plane
  Queen promotions use the matching queen-type plane; all other promotions
  (rook, bishop, knight) use underpromotion planes 64–72.
"""

import chess
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

# ── Move-encoding constants ──────────────────────────────────────────────────

_NUM_SQ           = 64
_QUEEN_PLANES     = 56   # 8 directions × 7 distances
_KNIGHT_PLANES    = 8
_UNDERPROMO_PLANES = 9   # 3 directions × 3 pieces (R/B/N)
_TOTAL_PLANES     = _QUEEN_PLANES + _KNIGHT_PLANES + _UNDERPROMO_PLANES  # 73
POLICY_SIZE       = _NUM_SQ * _TOTAL_PLANES  # 4672

# Queen-move directions: (file_delta, rank_delta) in order N NE E SE S SW W NW
_QUEEN_DIRS = [
    ( 0,  1),  # 0 N
    ( 1,  1),  # 1 NE
    ( 1,  0),  # 2 E
    ( 1, -1),  # 3 SE
    ( 0, -1),  # 4 S
    (-1, -1),  # 5 SW
    (-1,  0),  # 6 W
    (-1,  1),  # 7 NW
]
_QUEEN_DIR_IDX: dict[tuple[int, int], int] = {d: i for i, d in enumerate(_QUEEN_DIRS)}

# Knight offsets
_KNIGHT_OFFSETS = [
    ( 1,  2), ( 2,  1), ( 2, -1), ( 1, -2),
    (-1, -2), (-2, -1), (-2,  1), (-1,  2),
]
_KNIGHT_OFFSET_IDX: dict[tuple[int, int], int] = {
    d: i for i, d in enumerate(_KNIGHT_OFFSETS)
}

# Underpromotion piece indices (queen promotion falls through to queen planes)
_UNDERPROMO_PIECE_IDX: dict[int, int] = {
    chess.ROOK: 0, chess.BISHOP: 1, chess.KNIGHT: 2,
}


def _sign(x: int) -> int:
    return 0 if x == 0 else (1 if x > 0 else -1)


def encode_move(move: chess.Move) -> int:
    """Map a chess.Move to an index in [0, 4672).

    Index = from_square * 73 + plane, where planes are:
      0–55  queen-type (8 dirs × 7 distances)
      56–63 knight (8 offsets)
      64–72 underpromotion (3 directions × 3 pieces R/B/N)
    """
    from_sq   = move.from_square
    fd        = chess.square_file(move.to_square) - chess.square_file(from_sq)
    rd        = chess.square_rank(move.to_square) - chess.square_rank(from_sq)

    # Underpromotion (rook / bishop / knight only; queen falls through)
    if move.promotion is not None and move.promotion != chess.QUEEN:
        dir_idx   = fd + 1                          # {-1,0,+1} → {0,1,2}
        piece_idx = _UNDERPROMO_PIECE_IDX[move.promotion]
        plane     = _QUEEN_PLANES + _KNIGHT_PLANES + dir_idx * 3 + piece_idx
        return from_sq * _TOTAL_PLANES + plane

    # Knight moves
    knight_key = (fd, rd)
    if knight_key in _KNIGHT_OFFSET_IDX:
        plane = _QUEEN_PLANES + _KNIGHT_OFFSET_IDX[knight_key]
        return from_sq * _TOTAL_PLANES + plane

    # Queen-type moves (including queen promotions, king, rook, bishop, pawn)
    unit    = (_sign(fd), _sign(rd))
    dir_idx = _QUEEN_DIR_IDX[unit]
    plane   = dir_idx * 7 + (max(abs(fd), abs(rd)) - 1)
    return from_sq * _TOTAL_PLANES + plane


def decode_policy(
    policy_logits: Tensor,
    board: chess.Board,
) -> dict[chess.Move, float]:
    """Return {move: probability} for all legal moves.

    Masks out illegal moves, applies softmax over the legal subset,
    and renormalises so probabilities sum to 1.

    Args:
        policy_logits: raw (4672,) or (1, 4672) tensor from ChessNet
        board: current position (determines the legal-move mask)
    """
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return {}
    logits  = policy_logits.flatten()
    indices = torch.tensor(
        [encode_move(m) for m in legal_moves],
        dtype=torch.long,
        device=logits.device,
    )
    probs = F.softmax(logits[indices], dim=0)
    return {m: p.item() for m, p in zip(legal_moves, probs)}


# ── Network ──────────────────────────────────────────────────────────────────

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
    Full evaluation + policy network.

    Call signature:
        value, policy = net(board_tensor, scalar_tensor)
        # value  → (B, 1)
        # policy → (B, 4672)  raw logits; apply softmax externally
    """

    CHANNELS   = 64
    NUM_BLOCKS = 8
    SCALAR_DIM = 7
    HIDDEN     = 256
    HIDDEN2    = 64

    def __init__(self) -> None:
        super().__init__()

        flat_dim = self.CHANNELS * 8 * 8      # 4096
        head_in  = flat_dim + self.SCALAR_DIM  # 4103

        # Convolutional stem
        self.stem = nn.Sequential(
            nn.Conv2d(21, self.CHANNELS, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(self.CHANNELS),
            nn.ReLU(inplace=True),
        )

        # Residual tower
        self.res_blocks = nn.Sequential(
            *[_ResBlock(self.CHANNELS) for _ in range(self.NUM_BLOCKS)]
        )

        # Value head: flatten → concat scalars → MLP → scalar
        self.head = nn.Sequential(
            nn.Linear(head_in, self.HIDDEN),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(self.HIDDEN, self.HIDDEN2),
            nn.ReLU(inplace=True),
            nn.Linear(self.HIDDEN2, 1),
        )

        # Policy head: 1×1 conv to compress, then linear to 4672 logits
        self.policy_head = nn.Sequential(
            nn.Conv2d(self.CHANNELS, 2, kernel_size=1, bias=False),
            nn.BatchNorm2d(2),
            nn.ReLU(inplace=True),
            nn.Flatten(),                       # (B, 2*8*8) = (B, 128)
            nn.Linear(2 * 8 * 8, POLICY_SIZE),  # (B, 4672)
        )

    def forward(self, board: Tensor, scalars: Tensor) -> tuple[Tensor, Tensor]:
        x = self.stem(board)           # (B, 64, 8, 8)
        x = self.res_blocks(x)         # (B, 64, 8, 8)

        # Value head
        v      = x.flatten(start_dim=1)           # (B, 4096)
        v      = torch.cat([v, scalars], dim=1)   # (B, 4103)
        value  = self.head(v)                      # (B, 1)

        # Policy head
        policy = self.policy_head(x)               # (B, 4672)

        return value, policy
