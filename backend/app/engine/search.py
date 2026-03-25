"""
Minimax search with alpha-beta pruning.

The search is colour-agnostic: White maximises, Black minimises.
``eval_fn`` is a plug-in — pass hand_crafted_eval for Phase 1,
a neural-network callable for Phase 4.  The function signature is:
    eval_fn(board: chess.Board) -> int | float   (centipawns, White-positive)
"""

from __future__ import annotations

import chess
from typing import Callable

from .evaluate import tal_style_eval, evaluate, INF

EvalFn = Callable[[chess.Board], "int | float"]

_DEFAULT_DEPTH = 4


def _order_moves(board: chess.Board) -> list[chess.Move]:
    """Captures first (rough MVV-LVA proxy), quiet moves after.

    Good move ordering is the single biggest driver of alpha-beta efficiency.
    Captures are statistically more likely to be good moves, so examining them
    first raises alpha / lowers beta quickly and prunes more branches.
    """
    captures: list[chess.Move] = []
    quiets: list[chess.Move] = []
    for move in board.legal_moves:
        (captures if board.is_capture(move) else quiets).append(move)
    return captures + quiets


def _minimax(
    board: chess.Board,
    depth: int,
    alpha: float,
    beta: float,
    maximizing: bool,
    eval_fn: EvalFn,
) -> tuple[float, chess.Move | None]:
    """
    Returns (score, best_move).

    score is from White's perspective throughout the tree.
    best_move is None at leaf nodes (no move was made).
    """
    if depth == 0 or board.is_game_over():
        return eval_fn(board), None

    best_move: chess.Move | None = None

    if maximizing:  # White's turn — maximise score
        best: float = float("-inf")
        for move in _order_moves(board):
            is_tactical = board.is_capture(move) or board.gives_check(move)
            board.push(move)
            next_depth = depth if is_tactical else depth - 1
            score, _ = _minimax(board, next_depth, alpha, beta, False, eval_fn)
            board.pop()
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                break  # β cut-off: Black already has a better option elsewhere
        return best, best_move

    else:  # Black's turn — minimise score
        best = float("inf")
        for move in _order_moves(board):
            is_tactical = board.is_capture(move) or board.gives_check(move)
            board.push(move)
            next_depth = depth if is_tactical else depth - 1
            score, _ = _minimax(board, next_depth, alpha, beta, True, eval_fn)
            board.pop()
            if score < best:
                best, best_move = score, move
            beta = min(beta, score)
            if alpha >= beta:
                break  # α cut-off: White already has a better option elsewhere
        return best, best_move


def best_move(
    fen: str,
    depth: int = _DEFAULT_DEPTH,
    eval_fn: EvalFn = tal_style_eval,
) -> tuple[str, float]:
    """
    Return ``(uci_move, centipawn_score)`` for the best move at ``depth``.

    Score is from White's perspective (positive = White better).
    Falls back to the first legal move if the position is game-over.
    """
    board = chess.Board(fen)
    legal = list(board.legal_moves)
    if not legal:
        return "", 0.0

    score, move = _minimax(
        board,
        depth,
        float("-inf"),
        float("inf"),
        board.turn == chess.WHITE,
        eval_fn,
    )

    if move is None:
        # Shouldn't happen for non-terminal positions, but be safe.
        move = legal[0]

    return move.uci(), float(score)
