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


# ---------------------------------------------------------------------------
# Tal-style evaluation
# ---------------------------------------------------------------------------

TAL_AGGRESSION: float = 1.5

_ATTACK_BONUS: dict[int, int] = {
    chess.QUEEN:  40,
    chess.ROOK:   25,
    chess.BISHOP: 20,
    chess.KNIGHT: 20,
    chess.PAWN:   10,
}


def _king_attack_bonus(board: chess.Board, color: chess.Color) -> float:
    """Bonus for pieces of *color* that attack squares in the enemy king zone."""
    enemy = not color
    king_sq = board.king(enemy)
    if king_sq is None:
        return 0.0
    kf = chess.square_file(king_sq)
    kr = chess.square_rank(king_sq)

    # 3×3 zone around the enemy king
    zone = {
        chess.square(f, r)
        for f in range(max(0, kf - 1), min(8, kf + 2))
        for r in range(max(0, kr - 1), min(8, kr + 2))
    }

    # Unique (square, piece_type) pairs that attack any zone square
    attackers: set[tuple[int, int]] = set()
    for zone_sq in zone:
        for sq in board.attackers(color, zone_sq):
            piece = board.piece_at(sq)
            if piece:
                attackers.add((sq, piece.piece_type))

    if not attackers:
        return 0.0
    total = sum(_ATTACK_BONUS.get(pt, 0) for _, pt in attackers)
    return float(total * len(attackers))


def _open_file_bonus(board: chess.Board, color: chess.Color) -> float:
    """Bonus for open/semi-open files near the enemy king."""
    enemy = not color
    king_sq = board.king(enemy)
    if king_sq is None:
        return 0.0
    kf = chess.square_file(king_sq)

    bonus = 0.0
    for f in range(max(0, kf - 1), min(8, kf + 2)):
        mask = chess.BB_FILES[f]
        own_pawn   = bool(board.pieces(chess.PAWN, color)   & mask)
        enemy_pawn = bool(board.pieces(chess.PAWN, not color) & mask)
        if not own_pawn and not enemy_pawn:
            bonus += 50.0   # fully open
        elif not own_pawn:
            bonus += 30.0   # semi-open (attacker has no pawn here)
    return bonus


def _pawn_storm_bonus(board: chess.Board, color: chess.Color) -> float:
    """Bonus for pawns of *color* storming the enemy king's flank."""
    enemy = not color
    king_sq = board.king(enemy)
    if king_sq is None:
        return 0.0
    kf = chess.square_file(king_sq)

    bonus = 0.0
    for sq in board.pieces(chess.PAWN, color):
        f = chess.square_file(sq)
        if abs(f - kf) > 2:
            continue
        r = chess.square_rank(sq)
        rank = r if color == chess.WHITE else (7 - r)
        if rank == 4:    # 5th rank
            bonus += 20.0
        elif rank == 5:  # 6th rank
            bonus += 35.0
    return bonus


def _piece_activity_bonus(board: chess.Board, color: chess.Color) -> float:
    """Bonus for active, aggressive piece placement."""
    enemy = not color
    king_sq = board.king(enemy)
    seventh_rank_idx = 6 if color == chess.WHITE else 1

    bonus = 0.0
    for sq, piece in board.piece_map().items():
        if piece.color != color:
            continue
        r = chess.square_rank(sq)
        rank = r if color == chess.WHITE else (7 - r)

        if piece.piece_type == chess.KNIGHT and rank in (4, 5):
            bonus += 15.0
        elif piece.piece_type == chess.ROOK and r == seventh_rank_idx:
            bonus += 25.0
        elif piece.piece_type == chess.QUEEN and king_sq is not None:
            if chess.square_distance(sq, king_sq) <= 3:
                bonus += 30.0
    return bonus


def _king_safety_penalty(board: chess.Board, color: chess.Color) -> float:
    """Bonus for *color* based on the enemy king's lack of safety."""
    enemy = not color
    king_sq = board.king(enemy)
    if king_sq is None:
        return 0.0
    kf = chess.square_file(king_sq)
    kr = chess.square_rank(king_sq)

    bonus = 0.0

    # Pawn shield: rank immediately in front of the enemy king
    shield_rank = (kr + 1) if enemy == chess.WHITE else (kr - 1)
    if 0 <= shield_rank <= 7:
        shield_sqs = [
            chess.square(f, shield_rank)
            for f in range(max(0, kf - 1), min(8, kf + 2))
        ]
        pawn_count = sum(
            1 for s in shield_sqs
            if (p := board.piece_at(s)) and p.piece_type == chess.PAWN and p.color == enemy
        )
        if pawn_count == 0:
            bonus += 50.0

    # King stuck in center after losing castling rights
    if kf in (3, 4):
        if not (board.has_kingside_castling_rights(enemy) or
                board.has_queenside_castling_rights(enemy)):
            bonus += 60.0

    return bonus


def _tal_bonuses(board: chess.Board) -> float:
    """Net Tal-style bonus from White's perspective."""
    def _side(color: chess.Color) -> float:
        return (
            _king_attack_bonus(board, color)
            + _open_file_bonus(board, color)
            + _pawn_storm_bonus(board, color)
            + _piece_activity_bonus(board, color)
            + _king_safety_penalty(board, color)
        )
    return _side(chess.WHITE) - _side(chess.BLACK)


def tal_style_eval(board: chess.Board) -> int:
    """
    Tal-style evaluation: PST base + aggression bonuses × TAL_AGGRESSION.

    Rewards attacking the enemy king, open files toward it, pawn storms,
    active pieces, and penalises an unsafe enemy king.
    """
    base = evaluate(board)
    if base in (INF, -INF):
        return base  # don't dilute mate scores
    return int(base + _tal_bonuses(board) * TAL_AGGRESSION)


def hand_crafted_eval(board: chess.Board) -> int:
    """Alias for the plain PST evaluator (used by the fine-tuning script)."""
    return evaluate(board)
