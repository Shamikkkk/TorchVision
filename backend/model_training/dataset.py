"""
PyTorch Dataset and FEN-encoding utilities.

FEN → (board_tensor, scalar_tensor) encoding:
  board_tensor  : float32 (21, 8, 8)  — AlphaZero-style input planes
      Planes  0–5 : White  P N B R Q K  (1.0 if piece present)
      Planes  6–11: Black  p n b r q k  (1.0 if piece present)
      Plane  12   : threefold-repetition flag ≥1 (always 0.0 when encoding
                    from a bare FEN — game history is not available)
      Plane  13   : threefold-repetition flag ≥2 (same caveat)
      Plane  14   : side to move (1.0 = White, 0.0 = Black)
      Plane  15   : total move count normalised (fullmove_number / 200)
      Plane  16   : White kingside castling right  (1.0 / 0.0)
      Plane  17   : White queenside castling right (1.0 / 0.0)
      Plane  18   : Black kingside castling right  (1.0 / 0.0)
      Plane  19   : Black queenside castling right (1.0 / 0.0)
      Plane  20   : 50-move counter normalised (halfmove_clock / 50)
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

from .architecture import encode_move

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
    """Return a float32 (21, 8, 8) board tensor for the given FEN.

    Planes 12–13 (threefold repetition) are left at 0.0 because a bare FEN
    carries no game-history information.  Update them externally when a full
    move history is available.
    """
    board = chess.Board(fen)
    t = torch.zeros(21, 8, 8, dtype=torch.float32)

    # Planes 0–11: piece positions
    for sq, piece in board.piece_map().items():
        rank = sq >> 3   # sq // 8  (0 = rank 1)
        file = sq & 7    # sq %  8  (0 = file a)
        plane = _PIECE_PLANE[piece.piece_type]
        if piece.color == chess.BLACK:
            plane += 6
        t[plane, rank, file] = 1.0

    # Planes 12–13: threefold repetition — always 0.0 from a bare FEN

    # Plane 14: side to move
    if board.turn == chess.WHITE:
        t[14] = 1.0

    # Plane 15: total move count normalised
    t[15] = board.fullmove_number / 200.0

    # Planes 16–19: castling rights
    if board.has_kingside_castling_rights(chess.WHITE):
        t[16] = 1.0
    if board.has_queenside_castling_rights(chess.WHITE):
        t[17] = 1.0
    if board.has_kingside_castling_rights(chess.BLACK):
        t[18] = 1.0
    if board.has_queenside_castling_rights(chess.BLACK):
        t[19] = 1.0

    # Plane 20: 50-move counter normalised
    t[20] = board.halfmove_clock / 50.0

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


class ChessDataset(Dataset[tuple[tuple[Tensor, Tensor], float, int]]):
    """
    Loads a CSV of (fen, eval_centipawns, best_move) rows produced by parse.py.

    Each item: ((board_tensor, scalar_tensor), eval_score, move_index)
      move_index : int in [0, 4672) — AlphaZero encoding of the best move
    """

    def __init__(self, csv_path: str | Path) -> None:
        self._data: list[tuple[str, float, str]] = []
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 2:
                    # best_move column is optional — older CSVs only have fen,eval_cp
                    uci = row[2] if len(row) >= 3 else ""
                    self._data.append((row[0], float(row[1]), uci))

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx: int) -> tuple[tuple[Tensor, Tensor], float, int] | None:
        fen, score, uci = self._data[idx]
        try:
            board_t  = fen_to_tensor(fen)
            scalar_t = torch.tensor(fen_to_scalars(fen), dtype=torch.float32)
        except Exception:
            return None
        if uci:
            try:
                move_idx = encode_move(chess.Move.from_uci(uci))
            except Exception:
                return None
        else:
            move_idx = -1  # no policy label; CrossEntropyLoss(ignore_index=-1) skips it
        # Normalise centipawn eval to ~[-1, 1] so MSELoss trains on a sensible scale.
        # Both positions_sf_deep.csv and positions_combined.csv store raw centipawns.
        return (board_t, scalar_t), score / 600.0, move_idx
