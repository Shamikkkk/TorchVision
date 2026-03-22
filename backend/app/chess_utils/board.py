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
