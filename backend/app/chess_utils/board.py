import chess


def new_board() -> chess.Board:
    return chess.Board()


def apply_move(board: chess.Board, uci: str) -> tuple[bool, chess.Board]:
    """
    Apply a UCI move to a copy of the board.
    Returns (success, new_board). On failure the original board is returned unchanged.
    """
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return False, board

    if move not in board.legal_moves:
        return False, board

    new = board.copy()
    new.push(move)
    return True, new


def game_state_dict(board: chess.Board, *, resigned: bool = False) -> dict:  # type: ignore[type-arg]
    return {
        "type": "state",
        "fen": board.fen(),
        "turn": "w" if board.turn == chess.WHITE else "b",
        "status": "resigned" if resigned else _status(board),
        "last_move": board.peek().uci() if board.move_stack else None,
        "history": _build_history(board),
    }


_PIECE_VALUES: dict[int, int] = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


def uci_to_san(board: chess.Board, uci: str) -> str:
    """Convert a UCI move string to SAN notation given the board position before the move."""
    try:
        move = chess.Move.from_uci(uci)
        return board.san(move)
    except (ValueError, chess.IllegalMoveError):
        return uci


def is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Return True if the move lands on a square defended by a lower-value opponent piece."""
    moving_piece = board.piece_at(move.from_square)
    if moving_piece is None:
        return False
    moving_value = _PIECE_VALUES.get(moving_piece.piece_type, 0)
    opponent_color = not board.turn
    for attacker_sq in board.attackers(opponent_color, move.to_square):
        attacker = board.piece_at(attacker_sq)
        if attacker and _PIECE_VALUES.get(attacker.piece_type, 0) < moving_value:
            return True
    return False


def has_mate_in_one(board: chess.Board) -> bool:
    """Return True if any legal move from this position delivers checkmate."""
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def san_history(board: chess.Board) -> list[str]:
    """Return the SAN move history of the board (public wrapper)."""
    return _build_history(board)


def _build_history(board: chess.Board) -> list[str]:
    """Reconstruct SAN move history by replaying from the starting position."""
    moves = list(board.move_stack)
    temp = chess.Board()
    result: list[str] = []
    for move in moves:
        result.append(temp.san(move))
        temp.push(move)
    return result


def _status(board: chess.Board) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if (
        board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
    ):
        return "draw"
    return "ongoing"
