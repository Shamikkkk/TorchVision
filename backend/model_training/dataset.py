"""
PyTorch Dataset and FEN-encoding utilities.

FEN → (board_tensor, scalar_tensor) encoding:
  board_tensor  : float32 (12, 8, 8)
      12 planes = 6 piece types × 2 colors
      Planes 0–5 : White  P N B R Q K
      Planes 6–11: Black  p n b r q k
      Cell value: 1.0 if piece present, 0.0 otherwise.
      Rank 0 of the tensor = rank 1 of the board (a1 corner at [*, 0, 0]).

  scalar_tensor : float32 (7,)
      [0]   side to move  (1.0 = White, 0.0 = Black)
      [1–4] castling rights (White-K, White-Q, Black-k, Black-q)
      [5]   en-passant file (0–7, or -1 encoded as 0 with [6]=0)
      [6]   en-passant available flag (1.0 / 0.0)
"""

from __future__ import annotations

import csv
from pathlib import Path

import chess
import torch
from torch import Tensor
from torch.utils.data import Dataset

# piece_type (1-based, chess.PAWN=1 … chess.KING=6) → plane offset within color block
_PIECE_PLANE = {
    chess.PAWN:   0,
    chess.KNIGHT: 1,
    chess.BISHOP: 2,
    chess.ROOK:   3,
    chess.QUEEN:  4,
    chess.KING:   5,
}


def fen_to_tensor(fen: str) -> Tensor:
    """Return a float32 (12, 8, 8) board tensor for the given FEN."""
    board = chess.Board(fen)
    t = torch.zeros(12, 8, 8, dtype=torch.float32)
    for sq, piece in board.piece_map().items():
        rank = sq >> 3   # sq // 8  (0 = rank 1)
        file = sq & 7    # sq %  8  (0 = file a)
        plane = _PIECE_PLANE[piece.piece_type]
        if piece.color == chess.BLACK:
            plane += 6
        t[plane, rank, file] = 1.0
    return t


def fen_to_scalars(fen: str) -> list[float]:
    """Return a 7-element float list of scalar features for the given FEN."""
    board = chess.Board(fen)
    cr = board.castling_rights
    ep_sq = board.ep_square  # None or a python-chess square

    side = 1.0 if board.turn == chess.WHITE else 0.0
    wk = 1.0 if cr & chess.BB_H1 else 0.0
    wq = 1.0 if cr & chess.BB_A1 else 0.0
    bk = 1.0 if cr & chess.BB_H8 else 0.0
    bq = 1.0 if cr & chess.BB_A8 else 0.0

    if ep_sq is not None:
        ep_file = float(chess.square_file(ep_sq))
        ep_flag = 1.0
    else:
        ep_file = 0.0
        ep_flag = 0.0

    return [side, wk, wq, bk, bq, ep_file, ep_flag]


class ChessDataset(Dataset[tuple[tuple[Tensor, Tensor], float]]):
    """
    Loads a CSV of (fen, eval_centipawns) rows produced by parse.py.

    Each item: ((board_tensor, scalar_tensor), eval_score)
    """

    def __init__(self, csv_path: str | Path) -> None:
        self._data: list[tuple[str, float]] = []
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 2:
                    self._data.append((row[0], float(row[1])))

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx: int) -> tuple[tuple[Tensor, Tensor], float]:
        fen, score = self._data[idx]
        board_t = fen_to_tensor(fen)
        scalar_t = torch.tensor(fen_to_scalars(fen), dtype=torch.float32)
        return (board_t, scalar_t), score
