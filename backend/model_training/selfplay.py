"""
Self-play data generation and AlphaZero-style training loop for ChessNet.

Each iteration:
  1. Play GAMES_PER_ITER games against itself using MCTS.
  2. Add the labelled positions to a fixed-size replay buffer.
  3. Train on a random sample from the buffer for TRAIN_STEPS steps.
  4. Save a checkpoint.

After enough iterations the model improves purely through self-play —
no classical engine labels needed.

Usage (from backend/ with venv active):
    python -m model_training.selfplay
    python -m model_training.selfplay --iterations 100 --simulations 200
    python -m model_training.selfplay --resume          # load existing weights

Training targets per position:
  value  — game result from White's perspective, scaled to centipawns
           (+CP_SCALE = White wins, -CP_SCALE = Black wins, 0 = draw)
  policy — normalised MCTS visit distribution π over legal moves
           (soft cross-entropy: loss = -Σ π_i · log p_i)
"""

from __future__ import annotations

import argparse
import collections
import logging
import random
import sys
import time
from pathlib import Path

import chess
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

# Add backend/ to sys.path so app.engine is importable from model_training/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.engine.mcts import BatchedMCTS                    # noqa: E402

from .architecture import ChessNet, POLICY_SIZE, encode_move    # noqa: E402
from .dataset import fen_to_tensor, fen_to_scalars              # noqa: E402

logger = logging.getLogger(__name__)

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "models" / "torch_chess.pt"

# ── Hyperparameters ──────────────────────────────────────────────────────────
GAMES_PER_ITER      = 5
REPLAY_CAPACITY     = 10_000
TRAIN_STEPS         = 5        # mini-batch gradient steps per iteration
TRAIN_BATCH_SIZE    = 256
LR                  = 1e-4
POLICY_LOSS_WEIGHT  = 0.5      # total = value_loss + weight * policy_loss
TEMP_THRESHOLD      = 30       # use temperature=1 for first N half-moves, then 0
MAX_GAME_MOVES      = 200      # hard cap to prevent draws going on forever
_CP_SCALE           = 2000.0   # centipawns scale for value targets


# ── Neural-engine adapter ────────────────────────────────────────────────────

class _ModelEngine:
    """Thin wrapper so BatchedMCTS can drive a bare ``ChessNet`` directly.

    Mirrors the ``_nn_evaluate`` / ``_nn_evaluate_batch`` interface that
    ``TorchEngine`` exposes, but operates on the model in-process without
    loading from disk.
    """

    def __init__(self, model: ChessNet, device: torch.device) -> None:
        self._model  = model
        self._device = device

    def _nn_evaluate(
        self, board: chess.Board
    ) -> tuple[float, dict[chess.Move, float]]:
        from .architecture import decode_policy

        fen = board.fen()
        bt  = fen_to_tensor(fen).unsqueeze(0).to(self._device)
        st  = torch.tensor(
            fen_to_scalars(fen), dtype=torch.float32
        ).unsqueeze(0).to(self._device)

        with torch.no_grad():
            value_t, policy_t = self._model(bt, st)

        cp    = float(value_t.item())
        value = max(-1.0, min(1.0, cp / _CP_SCALE))
        if board.turn == chess.BLACK:
            value = -value

        return value, decode_policy(policy_t[0], board)

    def _nn_evaluate_batch(
        self,
        boards: list[chess.Board],
    ) -> tuple[list[float], list[dict[chess.Move, float]]]:
        from .architecture import decode_policy

        bt = torch.stack(
            [fen_to_tensor(b.fen()) for b in boards]
        ).to(self._device)
        st = torch.stack([
            torch.tensor(fen_to_scalars(b.fen()), dtype=torch.float32)
            for b in boards
        ]).to(self._device)

        with torch.no_grad():
            values_t, policies_t = self._model(bt, st)

        values: list[float] = []
        for i, board in enumerate(boards):
            cp = float(values_t[i].item())
            v  = max(-1.0, min(1.0, cp / _CP_SCALE))
            if board.turn == chess.BLACK:
                v = -v
            values.append(v)

        policies = [
            decode_policy(policies_t[i], board) for i, board in enumerate(boards)
        ]
        return values, policies


# ── Self-play game generation ────────────────────────────────────────────────

def _get_result(board: chess.Board) -> float:
    """Return game outcome from White's perspective: +1 / 0 / -1."""
    result = board.result()
    if result == "1-0":
        return 1.0
    if result == "0-1":
        return -1.0
    return 0.0   # draw or unfinished


def generate_selfplay_game(
    model: ChessNet,
    device: torch.device,
    num_simulations: int = 100,
    batch_size: int = 8,
    temp_threshold: int = TEMP_THRESHOLD,
) -> list[dict]:
    """Play one full game using MCTS self-play and return labelled positions.

    Each position dict contains:
      ``fen``    — board position before the move
      ``policy`` — normalised MCTS visit distribution {chess.Move: float}
      ``result`` — game outcome from White's perspective (+1 / 0 / -1),
                   identical for every position in the game

    Temperature schedule (AlphaZero-style):
      • First ``temp_threshold`` half-moves: temperature = 1.0 (sample to explore)
      • Remaining moves: temperature = 0.0 (pick most-visited move)
    """
    engine = _ModelEngine(model, device)
    mcts   = BatchedMCTS(engine, num_simulations=num_simulations, batch_size=batch_size)
    board  = chess.Board()
    positions: list[dict] = []

    for move_num in range(MAX_GAME_MOVES):
        if board.is_game_over():
            break

        temperature = 1.0 if move_num < temp_threshold else 0.0
        move, visit_probs = mcts.search_with_policy(board.fen(), temperature=temperature)

        if move == chess.Move.null() or not visit_probs:
            break

        positions.append({"fen": board.fen(), "policy": visit_probs})
        board.push(move)

    result = _get_result(board)
    for pos in positions:
        pos["result"] = result

    logger.info(
        "Game finished: %d moves, result=%.0f (%s)",
        len(positions),
        result,
        board.result(),
    )
    return positions


# ── Training on self-play positions ─────────────────────────────────────────

def _policy_to_tensor(visit_probs: dict[chess.Move, float]) -> Tensor:
    """Convert a {move: probability} dict to a (POLICY_SIZE,) float tensor."""
    t = torch.zeros(POLICY_SIZE, dtype=torch.float32)
    for move, prob in visit_probs.items():
        t[encode_move(move)] = prob
    return t


def train_on_positions(
    model: ChessNet,
    positions: list[dict],
    device: torch.device,
    batch_size: int = TRAIN_BATCH_SIZE,
    steps: int = TRAIN_STEPS,
) -> tuple[float, float, float]:
    """Run ``steps`` gradient steps on a random sample from ``positions``.

    Value target:  ``result * CP_SCALE``  (centipawns from White's perspective)
    Policy target: soft cross-entropy with MCTS visit distribution π
                   loss = -Σ π_i · log softmax(logits)_i

    Returns:
        (total_loss, value_loss, policy_loss) averaged over all mini-batches.
    """
    if not positions:
        return 0.0, 0.0, 0.0

    # Pre-build tensors on CPU; move to device per mini-batch.
    board_tensors  = torch.stack([fen_to_tensor(p["fen"])                  for p in positions])
    scalar_tensors = torch.stack([
        torch.tensor(fen_to_scalars(p["fen"]), dtype=torch.float32)
        for p in positions
    ])
    value_targets  = torch.tensor(
        [p["result"] * _CP_SCALE for p in positions], dtype=torch.float32
    ).unsqueeze(1)
    policy_targets = torch.stack([_policy_to_tensor(p["policy"]) for p in positions])

    criterion_value = nn.MSELoss()
    optimiser       = torch.optim.Adam(model.parameters(), lr=LR)
    n               = len(positions)
    indices         = list(range(n))

    total_v = total_p = total_t = 0.0
    n_steps = 0

    model.train()
    for _ in range(steps):
        random.shuffle(indices)
        for start in range(0, n, batch_size):
            idx = indices[start : start + batch_size]
            if not idx:
                continue

            bt = board_tensors[idx].to(device)
            st = scalar_tensors[idx].to(device)
            vt = value_targets[idx].to(device)
            pt = policy_targets[idx].to(device)

            optimiser.zero_grad()
            value_pred, policy_pred = model(bt, st)

            v_loss = criterion_value(value_pred, vt)
            # Soft cross-entropy: −Σ π_i · log p_i
            # (equivalent to KL(π ‖ softmax(logits)) up to a constant)
            p_loss = -(pt * F.log_softmax(policy_pred, dim=-1)).sum(dim=-1).mean()
            loss   = v_loss + POLICY_LOSS_WEIGHT * p_loss

            loss.backward()
            optimiser.step()

            total_v += v_loss.item()
            total_p += p_loss.item()
            total_t += loss.item()
            n_steps += 1

    model.eval()
    if n_steps == 0:
        return 0.0, 0.0, 0.0
    return total_t / n_steps, total_v / n_steps, total_p / n_steps


# ── Checkpoint management ────────────────────────────────────────────────────

def save_checkpoint(
    model: ChessNet,
    iteration: int,
    checkpoints_dir: Path,
) -> None:
    """Write a per-iteration checkpoint and overwrite the main weights file."""
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    iter_path = checkpoints_dir / f"selfplay_iter_{iteration:04d}.pt"
    torch.save(model.state_dict(), str(iter_path))
    # Overwrite the main weights file so the live engine picks up the update.
    _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), str(_WEIGHTS_PATH))
    logger.info("Checkpoint saved → %s", iter_path)


# ── Main training loop ───────────────────────────────────────────────────────

def selfplay_training_loop(
    model: ChessNet,
    device: torch.device,
    num_iterations: int = 50,
    games_per_iter: int = GAMES_PER_ITER,
    num_simulations: int = 100,
    replay_capacity: int = REPLAY_CAPACITY,
    checkpoints_dir: Path = Path("data/selfplay_checkpoints"),
) -> None:
    """Iterative self-play + training loop.

    Each iteration:
      1. Generate ``games_per_iter`` games; add positions to ``replay_buffer``.
      2. Train on ``list(replay_buffer)`` (keeps at most ``replay_capacity``
         positions — oldest are evicted automatically by the deque).
      3. Save a checkpoint.
    """
    replay_buffer: collections.deque[dict] = collections.deque(maxlen=replay_capacity)

    for iteration in range(num_iterations):
        t0 = time.monotonic()

        # ── 1. Generate games ────────────────────────────────────────────────
        new_positions = 0
        for g in range(games_per_iter):
            game_positions = generate_selfplay_game(
                model, device, num_simulations=num_simulations
            )
            replay_buffer.extend(game_positions)
            new_positions += len(game_positions)

        # ── 2. Train ─────────────────────────────────────────────────────────
        total_loss, v_loss, p_loss = train_on_positions(
            model, list(replay_buffer), device
        )

        # ── 3. Checkpoint ────────────────────────────────────────────────────
        save_checkpoint(model, iteration, checkpoints_dir)

        elapsed = time.monotonic() - t0
        print(
            f"[selfplay] Iter {iteration + 1:3d}/{num_iterations} | "
            f"{games_per_iter} games, {new_positions} pos | "
            f"buffer={len(replay_buffer):,} | "
            f"loss={total_loss:.4f} (v={v_loss:.2f} p={p_loss:.4f}) | "
            f"{elapsed:.1f}s"
        )


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="AlphaZero-style self-play training for ChessNet."
    )
    parser.add_argument("--iterations",  type=int,  default=50,
                        help="Number of self-play iterations (default: 50)")
    parser.add_argument("--simulations", type=int,  default=100,
                        help="MCTS simulations per move (default: 100)")
    parser.add_argument("--games",       type=int,  default=GAMES_PER_ITER,
                        help=f"Games per iteration (default: {GAMES_PER_ITER})")
    parser.add_argument("--checkpoints", type=Path,
                        default=Path("data/selfplay_checkpoints"),
                        help="Directory for per-iteration checkpoints")
    parser.add_argument("--resume",      action="store_true",
                        help="Load existing weights from models/torch_chess.pt")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[selfplay] Device: {device}")

    model = ChessNet().to(device)
    if args.resume and _WEIGHTS_PATH.exists():
        state = torch.load(str(_WEIGHTS_PATH), map_location=device)
        model.load_state_dict(state, strict=False)
        print(f"[selfplay] Resumed from {_WEIGHTS_PATH}")
    else:
        if args.resume:
            print(f"[selfplay] No checkpoint found at {_WEIGHTS_PATH} — starting fresh")
        else:
            print("[selfplay] Training from random initialisation")
    model.eval()

    selfplay_training_loop(
        model,
        device,
        num_iterations=args.iterations,
        games_per_iter=args.games,
        num_simulations=args.simulations,
        checkpoints_dir=args.checkpoints,
    )


if __name__ == "__main__":
    main()
