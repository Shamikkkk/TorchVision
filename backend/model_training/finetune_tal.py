"""
Fine-tune Pyro on Mikhail Tal's games.

Usage:
    python -m model_training.finetune_tal --pgn data/tal_games.pgn

This script:
1. Loads existing torch_chess.pt weights if available
   (fine-tuning is much faster than training from scratch)
2. Parses all of Tal's games from the PGN file
3. Extracts positions with Tal-style weighting:
   - Sacrifice positions: 3x weight
   - King attack positions: 2x weight
   - Normal positions: 1x weight
4. Labels each position using tal_style_eval
5. Fine-tunes with lower learning rate (lr=1e-4)
6. Saves to backend/models/torch_chess.pt
"""

import argparse
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

import chess
import chess.pgn
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

# Add backend/ to sys.path so both app and model_training are importable.
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.chess_utils.board import is_sacrifice          # noqa: E402
from app.engine.evaluate import tal_style_eval          # noqa: E402
from model_training.architecture import ChessNet        # noqa: E402
from model_training.dataset import fen_to_scalars, fen_to_tensor  # noqa: E402

WEIGHTS_PATH = _BACKEND / "models" / "torch_chess.pt"
BACKUP_PATH  = _BACKEND / "models" / "tal_finetuned_backup.pt"

# Hyperparameters
LR         = 1e-4
EPOCHS     = 20
BATCH_SIZE = 128
VAL_SPLIT  = 0.05

# Position weights
SACRIFICE_WEIGHT   = 3.0
KING_ATTACK_WEIGHT = 2.0
NORMAL_WEIGHT      = 1.0


def _is_king_attack_position(board: chess.Board) -> bool:
    """True if the side to move has 3+ pieces attacking the enemy king zone."""
    enemy_king = board.king(not board.turn)
    if enemy_king is None:
        return False
    kf = chess.square_file(enemy_king)
    kr = chess.square_rank(enemy_king)

    zone = {
        chess.square(f, r)
        for f in range(max(0, kf - 1), min(8, kf + 2))
        for r in range(max(0, kr - 1), min(8, kr + 2))
    }
    attacking_pieces: set[int] = set()
    for zone_sq in zone:
        for sq in board.attackers(board.turn, zone_sq):
            attacking_pieces.add(sq)
    return len(attacking_pieces) >= 3


def parse_tal_games(pgn_path: str) -> list[tuple[str, float, float]]:
    """
    Parse a PGN and return (fen, eval_score, weight) for every unique position.

    Weights:
      SACRIFICE_WEIGHT   (3.0) — Tal played a sacrifice here
      KING_ATTACK_WEIGHT (2.0) — position has a king attack setup
      NORMAL_WEIGHT      (1.0) — all other positions
    """
    positions: list[tuple[str, float, float]] = []
    seen_fens: set[str] = set()
    stats: defaultdict[str, int] = defaultdict(int)

    with open(pgn_path, encoding="utf-8", errors="ignore") as f:
        game_count = 0
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            game_count += 1

            board = game.board()
            for move in game.mainline_moves():
                fen = board.fen()
                if fen not in seen_fens:
                    seen_fens.add(fen)
                    score = float(tal_style_eval(board))

                    if is_sacrifice(board, move):
                        weight = SACRIFICE_WEIGHT
                        stats["sacrifice"] += 1
                    elif _is_king_attack_position(board):
                        weight = KING_ATTACK_WEIGHT
                        stats["king_attack"] += 1
                    else:
                        weight = NORMAL_WEIGHT
                        stats["normal"] += 1

                    positions.append((fen, score, weight))
                board.push(move)

            if game_count % 100 == 0:
                print(
                    f"[tal] Parsed {game_count} games, "
                    f"{len(positions)} positions so far…"
                )

    print(f"[tal] Done: {game_count} games, {len(positions)} unique positions")
    print(
        f"[tal] Sacrifice: {stats['sacrifice']}, "
        f"King attack: {stats['king_attack']}, "
        f"Normal: {stats['normal']}"
    )
    return positions


class TalDataset(Dataset):  # type: ignore[type-arg]
    def __init__(self, data: list[tuple[str, float, float]]) -> None:
        self.data = data

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int):  # type: ignore[override]
        fen, score, weight = self.data[idx]
        board_t  = fen_to_tensor(fen)
        scalar_t = torch.tensor(fen_to_scalars(fen), dtype=torch.float32)
        target   = torch.tensor([score], dtype=torch.float32)
        return (board_t, scalar_t), target, weight


def _collate(batch):  # type: ignore[no-untyped-def]
    boards, scalars, targets, weights = zip(*[
        (b, s, t, w) for (b, s), t, w in batch
    ])
    return (
        torch.stack(boards),
        torch.stack(scalars),
        torch.stack(targets),
        torch.tensor(weights, dtype=torch.float32),
    )


def finetune(pgn_path: str) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[tal] Device: {device}")
    if torch.cuda.is_available():
        print(f"[tal] GPU: {torch.cuda.get_device_name(0)}")

    print(f"[tal] Parsing {pgn_path}…")
    all_positions = parse_tal_games(pgn_path)
    if not all_positions:
        print("[tal] ERROR: No positions found. Check the PGN path.")
        return

    # Train / val split
    n_val   = max(1, int(len(all_positions) * VAL_SPLIT))
    n_train = len(all_positions) - n_val
    train_data = all_positions[:n_train]
    val_data   = all_positions[n_train:]

    weights = [w for _, _, w in train_data]
    sampler = WeightedRandomSampler(
        weights=weights, num_samples=len(train_data), replacement=True
    )

    train_loader = DataLoader(
        TalDataset(train_data),
        batch_size=BATCH_SIZE,
        sampler=sampler,
        collate_fn=_collate,
    )
    val_loader = DataLoader(
        TalDataset(val_data),
        batch_size=BATCH_SIZE,
        shuffle=False,
        collate_fn=_collate,
    )

    # Load model (fine-tune existing weights or start fresh)
    model = ChessNet().to(device)
    if WEIGHTS_PATH.exists():
        print(f"[tal] Loading existing weights from {WEIGHTS_PATH}")
        state = torch.load(str(WEIGHTS_PATH), map_location="cpu")
        model.load_state_dict(state, strict=False)
        print("[tal] Fine-tuning on top of existing weights…")
        shutil.copy(str(WEIGHTS_PATH), str(BACKUP_PATH))
        print(f"[tal] Backed up existing weights to {BACKUP_PATH}")
    else:
        print("[tal] No existing weights — training Tal style from scratch…")

    criterion = nn.MSELoss()
    optimiser = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=EPOCHS)

    best_val_loss = float("inf")

    for epoch in range(1, EPOCHS + 1):
        t0 = time.monotonic()

        # --- Training ---
        model.train()
        train_loss = 0.0
        n_train_samples = 0
        for boards, scalars, targets, _weights in train_loader:
            boards  = boards.to(device)
            scalars = scalars.to(device)
            targets = targets.to(device)
            optimiser.zero_grad()
            value, _ = model(boards, scalars)
            loss = criterion(value, targets)
            loss.backward()
            optimiser.step()
            n = len(targets)
            train_loss += loss.item() * n
            n_train_samples += n
        train_loss /= n_train_samples

        # --- Validation ---
        model.eval()
        val_loss = 0.0
        n_val_samples = 0
        with torch.no_grad():
            for boards, scalars, targets, _ in val_loader:
                boards  = boards.to(device)
                scalars = scalars.to(device)
                targets = targets.to(device)
                value, _ = model(boards, scalars)
                n = len(targets)
                val_loss += criterion(value, targets).item() * n
                n_val_samples += n
        val_loss /= n_val_samples

        scheduler.step()
        elapsed = time.monotonic() - t0
        print(
            f"[tal] Epoch {epoch:2d}/{EPOCHS} | "
            f"train={train_loss:.2f}  val={val_loss:.2f} | "
            f"{elapsed:.1f}s"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), str(WEIGHTS_PATH))
            print(f"[tal]   ✓ Saved best model → {WEIGHTS_PATH}")

    print(f"\n[tal] Fine-tuning complete!")
    print(f"[tal] Best val_loss : {best_val_loss:.2f}")
    print(f"[tal] Weights saved : {WEIGHTS_PATH}")
    print(f"[tal] Backup        : {BACKUP_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune Pyro on Tal's games")
    parser.add_argument("--pgn", required=True, help="Path to Tal PGN file")
    args = parser.parse_args()
    finetune(args.pgn)
