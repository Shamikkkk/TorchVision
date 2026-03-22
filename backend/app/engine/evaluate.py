"""
Hand-crafted chess evaluation function.

Returns a centipawn score from White's perspective:
  positive → White is better
  negative → Black is better

Piece-Square Tables are indexed by python-chess square convention:
  square 0 = a1 (rank 1, file a)  — rank 1 at the bottom
  square 63 = h8 (rank 8, file h) — rank 8 at the top

Usage:
  WHITE piece on sq  →  PST[sq]
  BLACK piece on sq  →  PST[sq ^ 56]   (flips rank; a1↔a8, h1↔h8, etc.)
"""

import chess

INF: int = 100_000  # larger than any real eval — used for mate scores

PIECE_VALUES: dict[int, int] = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20_000,
}

# fmt: off
# Each table is 64 ints, a1=index 0 … h8=index 63 (python-chess square order).
# Written visually rank 1 at top, rank 8 at bottom — matches a board viewed from
# White's side with rank 1 nearest to the viewer.

PAWN_PST: list[int] = [
     0,  0,  0,  0,  0,  0,  0,  0,   # rank 1 (no pawns start/end here)
     5, 10, 10,-20,-20, 10, 10,  5,   # rank 2 (penalty on d/e to push forward)
     5, -5,-10,  0,  0,-10, -5,  5,   # rank 3
     0,  0,  0, 20, 20,  0,  0,  0,   # rank 4 (center bonus)
     5,  5, 10, 25, 25, 10,  5,  5,   # rank 5
    10, 10, 20, 30, 30, 20, 10, 10,   # rank 6
    50, 50, 50, 50, 50, 50, 50, 50,   # rank 7 (near promotion)
     0,  0,  0,  0,  0,  0,  0,  0,   # rank 8 (promotion handled elsewhere)
]

KNIGHT_PST: list[int] = [
    -50,-40,-30,-30,-30,-30,-40,-50,   # rank 1
    -40,-20,  0,  5,  5,  0,-20,-40,   # rank 2
    -30,  5, 10, 15, 15, 10,  5,-30,   # rank 3
    -30,  0, 15, 20, 20, 15,  0,-30,   # rank 4
    -30,  5, 15, 20, 20, 15,  5,-30,   # rank 5
    -30,  0, 10, 15, 15, 10,  0,-30,   # rank 6
    -40,-20,  0,  0,  0,  0,-20,-40,   # rank 7
    -50,-40,-30,-30,-30,-30,-40,-50,   # rank 8
]

BISHOP_PST: list[int] = [
    -20,-10,-10,-10,-10,-10,-10,-20,   # rank 1
    -10,  5,  0,  0,  0,  0,  5,-10,   # rank 2
    -10, 10, 10, 10, 10, 10, 10,-10,   # rank 3
    -10,  0, 10, 10, 10, 10,  0,-10,   # rank 4
    -10,  5,  5, 10, 10,  5,  5,-10,   # rank 5
    -10,  0,  5, 10, 10,  5,  0,-10,   # rank 6
    -10,  0,  0,  0,  0,  0,  0,-10,   # rank 7
    -20,-10,-10,-10,-10,-10,-10,-20,   # rank 8
]

ROOK_PST: list[int] = [
     0,  0,  0,  5,  5,  0,  0,  0,   # rank 1 (connect on open d/e files)
    -5,  0,  0,  0,  0,  0,  0, -5,   # rank 2
    -5,  0,  0,  0,  0,  0,  0, -5,   # rank 3
    -5,  0,  0,  0,  0,  0,  0, -5,   # rank 4
    -5,  0,  0,  0,  0,  0,  0, -5,   # rank 5
    -5,  0,  0,  0,  0,  0,  0, -5,   # rank 6
     5, 10, 10, 10, 10, 10, 10,  5,   # rank 7 (7th-rank rook is powerful)
     0,  0,  0,  0,  0,  0,  0,  0,   # rank 8
]

QUEEN_PST: list[int] = [
    -20,-10,-10, -5, -5,-10,-10,-20,   # rank 1
    -10,  0,  5,  0,  0,  0,  0,-10,   # rank 2
    -10,  5,  5,  5,  5,  5,  0,-10,   # rank 3
      0,  0,  5,  5,  5,  5,  0, -5,   # rank 4
     -5,  0,  5,  5,  5,  5,  0, -5,   # rank 5
    -10,  0,  5,  5,  5,  5,  0,-10,   # rank 6
    -10,  0,  0,  0,  0,  0,  0,-10,   # rank 7
    -20,-10,-10, -5, -5,-10,-10,-20,   # rank 8
]

KING_MGS_PST: list[int] = [
     20, 30, 10,  0,  0, 10, 30, 20,   # rank 1 (castle, don't centralise)
     20, 20,  0,  0,  0,  0, 20, 20,   # rank 2
    -10,-20,-20,-20,-20,-20,-20,-10,   # rank 3
    -20,-30,-30,-40,-40,-30,-30,-20,   # rank 4
    -30,-40,-40,-50,-50,-40,-40,-30,   # rank 5
    -30,-40,-40,-50,-50,-40,-40,-30,   # rank 6
    -30,-40,-40,-50,-50,-40,-40,-30,   # rank 7
    -30,-40,-40,-50,-50,-40,-40,-30,   # rank 8
]
# fmt: on

_PST: dict[int, list[int]] = {
    chess.PAWN:   PAWN_PST,
    chess.KNIGHT: KNIGHT_PST,
    chess.BISHOP: BISHOP_PST,
    chess.ROOK:   ROOK_PST,
    chess.QUEEN:  QUEEN_PST,
    chess.KING:   KING_MGS_PST,
}


def evaluate(board: chess.Board) -> int:
    """
    Static evaluation of ``board`` in centipawns from White's perspective.

    Mate scores: ±INF (100 000 cp) so the search can find them decisively.
    """
    if board.is_checkmate():
        # The side whose turn it is has been checkmated.
        return -INF if board.turn == chess.WHITE else INF
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score: int = 0
    for sq, piece in board.piece_map().items():
        pst = _PST[piece.piece_type]
        # Mirror rank for Black so both sides share the same PST layout.
        pst_sq = sq if piece.color == chess.WHITE else (sq ^ 56)
        val = PIECE_VALUES[piece.piece_type] + pst[pst_sq]
        if piece.color == chess.WHITE:
            score += val
        else:
            score -= val
    return score
