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

# Endgame king PST: centralise, avoid edges and corners.
KING_EG_PST: list[int] = [
    -50,-30,-30,-30,-30,-30,-30,-50,   # rank 1
    -30,-20,  0,  0,  0,  0,-20,-30,   # rank 2
    -30,-10, 20, 30, 30, 20,-10,-30,   # rank 3
    -30,-10, 30, 40, 40, 30,-10,-30,   # rank 4
    -30,-10, 30, 40, 40, 30,-10,-30,   # rank 5
    -30,-10, 20, 30, 30, 20,-10,-30,   # rank 6
    -30,-20,-10,  0,  0,-10,-20,-30,   # rank 7
    -50,-40,-30,-20,-20,-30,-40,-50,   # rank 8
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

    piece_map = board.piece_map()
    is_endgame = len(piece_map) < 10

    score: int = 0
    for sq, piece in piece_map.items():
        if piece.piece_type == chess.KING and is_endgame:
            pst = KING_EG_PST
        else:
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


def _castling_bonus(board: chess.Board) -> float:
    """
    +80cp for each side that still has castling rights with king on its start square.
    Net is from White's perspective.
    """
    bonus = 0.0
    if (board.king(chess.WHITE) == chess.E1 and
            (board.has_kingside_castling_rights(chess.WHITE) or
             board.has_queenside_castling_rights(chess.WHITE))):
        bonus += 80.0
    if (board.king(chess.BLACK) == chess.E8 and
            (board.has_kingside_castling_rights(chess.BLACK) or
             board.has_queenside_castling_rights(chess.BLACK))):
        bonus -= 80.0
    return bonus


def _queen_early_penalty(board: chess.Board) -> float:
    """
    -60cp if a side moves its queen before move 10.
    Detected by queen not being on its home square (d1/d8).
    Net is from White's perspective.
    """
    if board.fullmove_number >= 10:
        return 0.0
    penalty = 0.0
    white_queens = board.pieces(chess.QUEEN, chess.WHITE)
    if white_queens and chess.D1 not in white_queens:
        penalty -= 60.0
    black_queens = board.pieces(chess.QUEEN, chess.BLACK)
    if black_queens and chess.D8 not in black_queens:
        penalty += 60.0
    return penalty


# Bonus by rank-from-own-side (0=own back rank … 7=promotion rank).
_PASSED_PAWN_BONUS: dict[int, int] = {3: 10, 4: 20, 5: 40, 6: 70}


def _passed_pawn_bonus(board: chess.Board) -> int:
    """White-positive bonus for passed pawns. Called only in endgame."""
    score = 0
    for color in (chess.WHITE, chess.BLACK):
        enemy_pawns = board.pieces(chess.PAWN, not color)
        for sq in board.pieces(chess.PAWN, color):
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            passed = True
            for esq in enemy_pawns:
                if abs(chess.square_file(esq) - f) <= 1:
                    er = chess.square_rank(esq)
                    if color == chess.WHITE and er > r:
                        passed = False
                        break
                    if color == chess.BLACK and er < r:
                        passed = False
                        break
            if passed:
                rank_from_own = r if color == chess.WHITE else (7 - r)
                bonus = _PASSED_PAWN_BONUS.get(rank_from_own, 0)
                score += bonus if color == chess.WHITE else -bonus
    return score


def _pawn_structure(board: chess.Board) -> int:
    """
    White-positive score for pawn structure.

    - Doubled pawns:  -20cp per extra pawn beyond the first on a file.
    - Isolated pawns: -15cp per pawn with no friendly pawn on an adjacent file.
    - Connected passed pawns: +30cp per passed pawn that has a friendly pawn
      on an adjacent file (the two support each other).
    """
    score = 0
    for color in (chess.WHITE, chess.BLACK):
        own_pawns   = board.pieces(chess.PAWN, color)
        enemy_pawns = board.pieces(chess.PAWN, not color)
        sign = 1 if color == chess.WHITE else -1

        # Count pawns per file for doubling / isolation checks
        file_counts: list[int] = [0] * 8
        for sq in own_pawns:
            file_counts[chess.square_file(sq)] += 1

        for sq in own_pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)

            # Doubled: penalise the extra copies (count−1 penalties per file)
            if file_counts[f] > 1:
                score -= sign * 20

            # Isolated: no friendly pawn on either adjacent file
            left  = file_counts[f - 1] if f > 0 else 0
            right = file_counts[f + 1] if f < 7 else 0
            if left == 0 and right == 0:
                score -= sign * 15

            # Connected passed pawn: passed AND has a friendly pawn next to it
            else:
                # Check whether this pawn is passed
                passed = True
                for esq in enemy_pawns:
                    ef = chess.square_file(esq)
                    er = chess.square_rank(esq)
                    if abs(ef - f) <= 1:
                        if color == chess.WHITE and er > r:
                            passed = False
                            break
                        if color == chess.BLACK and er < r:
                            passed = False
                            break
                if passed:
                    score += sign * 30

    return score


def _rook_structure(board: chess.Board) -> int:
    """
    White-positive score for rook placement.

    - Open file   (+25cp): no pawns of either color on the rook's file.
    - Semi-open   (+15cp): no own pawns, but enemy pawns present.
    - Connected   (+20cp): two same-color rooks on the same rank or file
      with no pieces between them.
    """
    score = 0
    for color in (chess.WHITE, chess.BLACK):
        sign = 1 if color == chess.WHITE else -1
        own_rooks = board.pieces(chess.ROOK, color)
        if not own_rooks:
            continue

        own_pawns   = board.pieces(chess.PAWN, color)
        enemy_pawns = board.pieces(chess.PAWN, not color)

        for sq in own_rooks:
            f = chess.square_file(sq)
            file_mask = chess.BB_FILES[f]
            has_own   = bool(own_pawns   & file_mask)
            has_enemy = bool(enemy_pawns & file_mask)

            if not has_own and not has_enemy:
                score += sign * 25   # open file
            elif not has_own:
                score += sign * 15   # semi-open file

        # Connected rooks: same rank or file, nothing between them
        rook_list = list(own_rooks)
        if len(rook_list) >= 2:
            r1, r2 = rook_list[0], rook_list[1]
            between = chess.SquareSet(chess.between(r1, r2))
            if (chess.square_file(r1) == chess.square_file(r2) or
                    chess.square_rank(r1) == chess.square_rank(r2)):
                if not (between & board.occupied):
                    score += sign * 20

    return score


def _bishop_pair_bonus(board: chess.Board) -> int:
    """
    +50cp for each side that retains both bishops.

    The bishop pair is a well-known positional advantage: two bishops cover
    all squares and become especially powerful in open positions.  Net score
    is White-positive.
    """
    score = 0
    for color in (chess.WHITE, chess.BLACK):
        if len(board.pieces(chess.BISHOP, color)) >= 2:
            score += 50 if color == chess.WHITE else -50
    return score


def tal_style_eval(board: chess.Board) -> int:
    """
    Tal-style evaluation: PST base + aggression bonuses × TAL_AGGRESSION
    + opening principles (castling rights, no early queen).
    """
    base = evaluate(board)
    if base in (INF, -INF):
        return base  # don't dilute mate scores
    opening = _castling_bonus(board) + _queen_early_penalty(board)
    endgame = _passed_pawn_bonus(board) if len(board.piece_map()) < 10 else 0
    structure = _pawn_structure(board) + _rook_structure(board) + _bishop_pair_bonus(board)
    return int(base + _tal_bonuses(board) * TAL_AGGRESSION + opening + endgame + structure)


def hand_crafted_eval(board: chess.Board) -> int:
    """Alias for the plain PST evaluator (used by the fine-tuning script)."""
    return evaluate(board)


# ---------------------------------------------------------------------------
# NNUE-backed eval (with Tal-style fallback)
# ---------------------------------------------------------------------------

def nnue_eval(board: chess.Board) -> float:
    """
    Primary eval function for minimax search.

    Uses the trained NNUE network when weights are available, falls back to
    Tal-style PST evaluation otherwise.  The fallback means the engine is
    always functional even before nnue.pt is trained.
    """
    from .nnue import nnue  # imported here to avoid a circular import at module load

    result = nnue.evaluate(board)
    if result is not None:
        return result
    return tal_style_eval(board)
