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

_MAX_KILLER_DEPTH = 20
# Two killer slots per depth — quiet moves that recently caused a beta cutoff.
_killers: list[list[chess.Move | None]] = [[None, None] for _ in range(_MAX_KILLER_DEPTH)]

# History heuristic: quiet moves that caused beta cutoffs get a score boost.
# Key: (piece_type, to_square).  Value: accumulated depth² reward.
_history: dict[tuple[int, int], int] = {}

_NULL_MOVE_R = 2   # null-move reduction


def _store_killer(depth: int, move: chess.Move, board: chess.Board) -> None:
    if depth >= _MAX_KILLER_DEPTH:
        return
    slot = _killers[depth]
    if slot[0] != move:          # don't duplicate
        slot[1] = slot[0]
        slot[0] = move
    # History: reward this quiet move proportional to depth² so deep cutoffs
    # count more than shallow ones.
    piece = board.piece_at(move.from_square)
    if piece:
        key = (piece.piece_type, move.to_square)
        _history[key] = _history.get(key, 0) + depth * depth


class _TimeUp(Exception):
    """Raised internally to unwind the search tree when the deadline is hit."""


def _order_moves(
    board: chess.Board, depth: int
) -> tuple[list[chess.Move], set[chess.Move]]:
    """Captures first, then killer moves, then remaining quiet moves.

    Returns ``(ordered_moves, killer_set)`` so callers can check killer
    membership in O(1) without recomputing it (needed for LMR guards).

    Good move ordering is the single biggest driver of alpha-beta efficiency.
    Captures are statistically more likely to be good moves, so examining them
    first raises alpha / lowers beta quickly and prunes more branches.
    Killers are quiet moves that recently caused a beta cutoff at this depth —
    trying them early avoids searching many inferior quiet moves.
    """
    killer_set: set[chess.Move] = set()
    if depth < _MAX_KILLER_DEPTH:
        for k in _killers[depth]:
            if k is not None and board.is_legal(k):
                killer_set.add(k)

    captures: list[chess.Move] = []
    killers:  list[chess.Move] = []
    quiets:   list[chess.Move] = []
    for move in board.legal_moves:
        if board.is_capture(move):
            captures.append(move)
        elif move in killer_set:
            killers.append(move)
        else:
            quiets.append(move)

    # Sort quiet moves by history score descending — moves that caused beta
    # cutoffs in previous iterations bubble to the top.
    if quiets:
        quiets.sort(
            key=lambda m: -_history.get(
                (board.piece_at(m.from_square).piece_type, m.to_square)
                if board.piece_at(m.from_square) else (0, 0),
                0,
            )
        )

    return captures + killers + quiets, killer_set


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
    allow_null: bool = True,
) -> tuple[float, chess.Move | None]:
    """
    Returns (score, best_move).

    score is from White's perspective throughout the tree.
    best_move is None at leaf nodes (no move was made).
    Raises _TimeUp when the wall-clock deadline is exceeded.

    allow_null: False after a null move to prevent consecutive null moves.
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

    # ------------------------------------------------------------------
    # Null move pruning
    # If we skip our turn and the opponent still can't beat beta, this
    # node is already too good — prune it.
    # Conditions: depth >= 3, not in check, not in endgame (>= 10 pieces).
    # R=2 so the verification search runs at depth-1-R = depth-3.
    # ------------------------------------------------------------------
    if (allow_null
            and depth >= 3
            and not board.is_check()
            and len(board.piece_map()) >= 10):
        board.push(chess.Move.null())
        null_score, _ = _minimax(
            board, depth - 1 - _NULL_MOVE_R,
            alpha, beta,
            not maximizing,
            eval_fn, deadline,
            allow_null=False,
        )
        board.pop()
        if maximizing and null_score >= beta:
            return beta, None
        if not maximizing and null_score <= alpha:
            return alpha, None

    best_move: chess.Move | None = None
    ordered_moves, killer_set = _order_moves(board, depth)

    if maximizing:  # White's turn — maximise score
        best: float = float("-inf")
        for move_idx, move in enumerate(ordered_moves):
            is_capture = board.is_capture(move)
            # Late Move Reduction: quiet, non-killer, non-checking moves beyond
            # the first 4 are searched at depth-2 first.  Only depth >= 3 and
            # move index >= 4.  gives_check() must be called before push().
            use_lmr = (
                depth >= 3
                and move_idx >= 4
                and not is_capture
                and move not in killer_set
                and not board.gives_check(move)
            )
            board.push(move)
            if use_lmr:
                score, _ = _minimax(board, depth - 2, alpha, beta, False, eval_fn, deadline)
                # If the reduced search looks interesting, verify at full depth.
                if score > alpha:
                    score, _ = _minimax(board, depth - 1, alpha, beta, False, eval_fn, deadline)
            else:
                score, _ = _minimax(board, depth - 1, alpha, beta, False, eval_fn, deadline)
            board.pop()
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                if not is_capture:
                    _store_killer(depth, move, board)
                break  # β cut-off
    else:  # Black's turn — minimise score
        best = float("inf")
        for move_idx, move in enumerate(ordered_moves):
            is_capture = board.is_capture(move)
            use_lmr = (
                depth >= 3
                and move_idx >= 4
                and not is_capture
                and move not in killer_set
                and not board.gives_check(move)
            )
            board.push(move)
            if use_lmr:
                score, _ = _minimax(board, depth - 2, alpha, beta, True, eval_fn, deadline)
                # If the reduced search looks interesting, verify at full depth.
                if score < beta:
                    score, _ = _minimax(board, depth - 1, alpha, beta, True, eval_fn, deadline)
            else:
                score, _ = _minimax(board, depth - 1, alpha, beta, True, eval_fn, deadline)
            board.pop()
            if score < best:
                best, best_move = score, move
            beta = min(beta, score)
            if alpha >= beta:
                if not is_capture:
                    _store_killer(depth, move, board)
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
    _history.clear()
    for slot in _killers:
        slot[0] = None
        slot[1] = None

    logger.debug("Search starting depth=%d fen=%s", depth, fen[:40])
    start    = time.monotonic()
    deadline = start + _TIME_LIMIT

    # Seed with first legal move — guarantees a valid result even if depth 1
    # is interrupted before completing its first iteration.
    best_uci   = legal[0].uci()
    best_score = 0.0

    _AW_DELTA   = 50       # initial half-width of the aspiration window (cp)
    _AW_RETRIES = 3        # max widening attempts before falling back to full window
    maximizing  = board.turn == chess.WHITE
    prev_score  = 0.0      # updated after each completed depth

    for d in range(1, depth + 1):
        # Depth 1 always uses a full window to establish a reliable prev_score.
        if d == 1:
            a, b = float("-inf"), float("inf")
        else:
            a = prev_score - _AW_DELTA
            b = prev_score + _AW_DELTA

        try:
            for attempt in range(_AW_RETRIES + 1):
                score, move = _minimax(board, d, a, b, maximizing, eval_fn, deadline)

                if score <= a:
                    # Fail low — widen the lower bound and retry.
                    if attempt == _AW_RETRIES:
                        a = float("-inf")
                    else:
                        a -= _AW_DELTA * (2 ** attempt)
                elif score >= b:
                    # Fail high — widen the upper bound and retry.
                    if attempt == _AW_RETRIES:
                        b = float("inf")
                    else:
                        b += _AW_DELTA * (2 ** attempt)
                else:
                    break  # score inside window — search complete for this depth

            # Only commit results from fully-completed searches.
            if move is not None:
                best_uci   = move.uci()
                best_score = float(score)
                prev_score = best_score

        except _TimeUp:
            logger.debug("Time limit hit at depth %d — returning best so far", d)
            break

    elapsed = time.monotonic() - start
    logger.debug(
        "Search complete move=%s score=%s elapsed=%.1fs", best_uci, best_score, elapsed
    )
    logger.debug("TT size: %d entries", len(_tt))
    return best_uci, best_score
