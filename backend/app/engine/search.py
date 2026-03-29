"""
Minimax search with alpha-beta pruning and iterative deepening.

The search is colour-agnostic: White maximises, Black minimises.
``eval_fn`` is a plug-in — pass hand_crafted_eval for Phase 1,
a neural-network callable for Phase 4.  The function signature is:
    eval_fn(board: chess.Board) -> int | float   (centipawns, White-positive)

Iterative deepening: best_move() runs depth 1 → target depth, stopping
early if the 5-second time limit is exceeded.  Each completed depth
overwrites the result, so we always return the deepest fully-searched move.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import chess

from .evaluate import tal_style_eval, INF

logger = logging.getLogger(__name__)

EvalFn = Callable[[chess.Board], "int | float"]

_DEFAULT_DEPTH = 4
_TIME_LIMIT    = 5.0   # seconds; iterative deepening stops if this is exceeded

_tt: dict[str, tuple[float, int, chess.Move | None]] = {}
_TT_MAX_SIZE = 1_000_000


class _TimeUp(Exception):
    """Raised internally to unwind the search tree when the deadline is hit."""


def _order_moves(board: chess.Board) -> list[chess.Move]:
    """Captures first (rough MVV-LVA proxy), quiet moves after.

    Good move ordering is the single biggest driver of alpha-beta efficiency.
    Captures are statistically more likely to be good moves, so examining them
    first raises alpha / lowers beta quickly and prunes more branches.
    """
    captures: list[chess.Move] = []
    quiets:   list[chess.Move] = []
    for move in board.legal_moves:
        (captures if board.is_capture(move) else quiets).append(move)
    return captures + quiets


_QS_DEPTH_LIMIT = 4   # max capture-chain depth to prevent explosion


def _quiescence(
    board: chess.Board,
    alpha: float,
    beta: float,
    maximizing: bool,
    eval_fn: EvalFn,
    deadline: float,
    qs_depth: int = 0,
) -> float:
    """
    Quiescence search — extends depth-0 nodes by searching captures only.

    Prevents the horizon effect: a position that looks good at depth 0 may
    have a hanging piece that gets taken on the next move.  The stand-pat
    score lets the side-to-move choose not to capture if the position is
    already good enough.

    ``qs_depth`` counts how many capture plies deep we are; capped at
    ``_QS_DEPTH_LIMIT`` to prevent infinite capture chains.
    """
    if time.monotonic() >= deadline:
        raise _TimeUp

    stand_pat: float = eval_fn(board)

    if qs_depth >= _QS_DEPTH_LIMIT:
        return stand_pat

    if maximizing:
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
        best = stand_pat
        for move in board.generate_pseudo_legal_captures():
            if not board.is_legal(move):
                continue
            board.push(move)
            score = _quiescence(board, alpha, beta, False, eval_fn, deadline, qs_depth + 1)
            board.pop()
            if score > best:
                best = score
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best
    else:
        if stand_pat <= alpha:
            return alpha
        beta = min(beta, stand_pat)
        best = stand_pat
        for move in board.generate_pseudo_legal_captures():
            if not board.is_legal(move):
                continue
            board.push(move)
            score = _quiescence(board, alpha, beta, True, eval_fn, deadline, qs_depth + 1)
            board.pop()
            if score < best:
                best = score
            beta = min(beta, score)
            if alpha >= beta:
                break
        return best


def _minimax(
    board: chess.Board,
    depth: int,
    alpha: float,
    beta: float,
    maximizing: bool,
    eval_fn: EvalFn,
    deadline: float,
) -> tuple[float, chess.Move | None]:
    """
    Returns (score, best_move).

    score is from White's perspective throughout the tree.
    best_move is None at leaf nodes (no move was made).
    Raises _TimeUp when the wall-clock deadline is exceeded.
    """
    if time.monotonic() >= deadline:
        raise _TimeUp

    fen_key = board.fen()
    if fen_key in _tt:
        cached_score, cached_depth, cached_move = _tt[fen_key]
        if cached_depth >= depth:
            return cached_score, cached_move

    if board.is_game_over():
        return eval_fn(board), None
    if depth == 0:
        return _quiescence(board, alpha, beta, maximizing, eval_fn, deadline), None

    best_move: chess.Move | None = None

    if maximizing:  # White's turn — maximise score
        best: float = float("-inf")
        for move in _order_moves(board):
            board.push(move)
            score, _ = _minimax(board, depth - 1, alpha, beta, False, eval_fn, deadline)
            board.pop()
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                break  # β cut-off
    else:  # Black's turn — minimise score
        best = float("inf")
        for move in _order_moves(board):
            board.push(move)
            score, _ = _minimax(board, depth - 1, alpha, beta, True, eval_fn, deadline)
            board.pop()
            if score < best:
                best, best_move = score, move
            beta = min(beta, score)
            if alpha >= beta:
                break  # α cut-off

    if len(_tt) >= _TT_MAX_SIZE:
        _tt.clear()
    _tt[fen_key] = (best, depth, best_move)
    return best, best_move


def best_move(
    fen: str,
    depth: int = _DEFAULT_DEPTH,
    eval_fn: EvalFn = tal_style_eval,
) -> tuple[str, float]:
    """
    Return ``(uci_move, centipawn_score)`` for the best move at ``depth``.

    Uses iterative deepening (depth 1 → target depth) with a 5-second time
    limit.  Each completed depth updates the result; if time runs out mid-
    search the last fully-completed depth's move is returned.

    Score is from White's perspective (positive = White better).
    Falls back to the first legal move if the position is game-over.
    """
    board = chess.Board(fen)
    legal = list(board.legal_moves)
    if not legal:
        return "", 0.0

    if board.is_repetition(2):
        return "", 0.0

    _tt.clear()

    logger.debug("Search starting depth=%d fen=%s", depth, fen[:40])
    start    = time.monotonic()
    deadline = start + _TIME_LIMIT

    # Seed with first legal move — guarantees a valid result even if depth 1
    # is interrupted before completing its first iteration.
    best_uci   = legal[0].uci()
    best_score = 0.0

    for d in range(1, depth + 1):
        try:
            score, move = _minimax(
                board, d,
                float("-inf"), float("inf"),
                board.turn == chess.WHITE,
                eval_fn, deadline,
            )
            # Only commit results from fully-completed searches.
            if move is not None:
                best_uci   = move.uci()
                best_score = float(score)
        except _TimeUp:
            logger.debug("Time limit hit at depth %d — returning best so far", d)
            break

    elapsed = time.monotonic() - start
    logger.debug(
        "Search complete move=%s score=%s elapsed=%.1fs", best_uci, best_score, elapsed
    )
    logger.debug("TT size: %d entries", len(_tt))
    return best_uci, best_score
