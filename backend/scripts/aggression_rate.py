"""
G9 STEP 1 — aggression-rate metric.
Parse a PGN, replay each game, flag any played move where the playing side is
"Pyro" and the move is a sacrifice. Report fraction of games with >=1 such move.

Sacrifice := a capture where the captured piece is defended after the move AND
(captured_val - capturer_val) <= -150. This is a SEE proxy: full SEE would
recurse through the exchange chain, but for "did Pyro played a piece down"
the 2-ply approximation is faithful — it counts genuine investments and rejects
free captures, even trades, and winning trades.

Pyro is identified by the [White] / [Black] header containing "Pyro" (case-insensitive).
Multiple files can be passed; results are aggregated.

Usage:
  python backend/scripts/aggression_rate.py <pgn_file> [pgn_file...]
"""
import sys
from pathlib import Path
import chess
import chess.pgn

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PIECE_VAL = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20_000,
}

SAC_THRESHOLD = -150

def see_proxy(board: chess.Board, move: chess.Move) -> int:
    """Return naive 2-ply SEE: captured_val if undefended after; otherwise
    captured_val - capturer_val. Returns 0 for non-captures."""
    if not board.is_capture(move):
        return 0

    if board.is_en_passant(move):
        captured_val = PIECE_VAL[chess.PAWN]
    else:
        target = board.piece_at(move.to_square)
        if target is None:
            return 0
        captured_val = PIECE_VAL[target.piece_type]

    capturer = board.piece_at(move.from_square)
    if capturer is None:
        return 0
    capturer_val = PIECE_VAL[capturer.piece_type]

    board.push(move)
    defenders = board.attackers(board.turn, move.to_square)
    board.pop()

    if not defenders:
        return captured_val
    return captured_val - capturer_val


def is_pyro(name: str) -> bool:
    return "pyro" in (name or "").lower()


def king_zone_squares(king_sq: int) -> set:
    """3x3 zone around a king square (clamped)."""
    f = chess.square_file(king_sq)
    r = chess.square_rank(king_sq)
    out = set()
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                out.add(chess.square(nf, nr))
    return out


def analyze_pgn(path: Path):
    games = 0
    games_with_sac = 0
    games_with_kz_sac = 0
    total_pyro_moves = 0
    total_pyro_sacs = 0
    total_pyro_kz_sacs = 0
    sac_examples = []  # (file, game_idx, ply, san, see_proxy, kz_flag)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        idx = 0
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            idx += 1
            white = game.headers.get("White", "")
            black = game.headers.get("Black", "")
            w_is_pyro = is_pyro(white)
            b_is_pyro = is_pyro(black)
            if not (w_is_pyro or b_is_pyro):
                continue
            games += 1

            board = game.board()
            this_game_sacs = 0
            this_game_kz_sacs = 0
            for ply_idx, move in enumerate(game.mainline_moves()):
                stm_white = board.turn
                pyro_to_move = (stm_white and w_is_pyro) or ((not stm_white) and b_is_pyro)
                if pyro_to_move:
                    total_pyro_moves += 1
                    s = see_proxy(board, move)
                    if s <= SAC_THRESHOLD:
                        total_pyro_sacs += 1
                        this_game_sacs += 1
                        # King-zone test: to-square in enemy king's 3x3 zone
                        enemy_king_sq = board.king(not stm_white)
                        in_kz = (enemy_king_sq is not None and
                                 move.to_square in king_zone_squares(enemy_king_sq))
                        if in_kz:
                            total_pyro_kz_sacs += 1
                            this_game_kz_sacs += 1
                        if len(sac_examples) < 10:
                            try:
                                san = board.san(move)
                            except Exception:
                                san = move.uci()
                            sac_examples.append((path.name, idx, ply_idx + 1, san, s, in_kz))
                board.push(move)
            if this_game_sacs > 0:
                games_with_sac += 1
            if this_game_kz_sacs > 0:
                games_with_kz_sac += 1
    return (games, games_with_sac, games_with_kz_sac,
            total_pyro_moves, total_pyro_sacs, total_pyro_kz_sacs, sac_examples)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python aggression_rate.py <pgn_file> [pgn_file...]")
        sys.exit(2)

    total_games = 0
    total_with_sac = 0
    total_with_kz_sac = 0
    total_moves = 0
    total_sacs = 0
    total_kz_sacs = 0
    all_examples = []

    print(f"{'file':<50}  {'games':>5} {'sac%':>6} {'kz_sac%':>8} {'sacs/g':>7} {'kz/g':>6}")
    print("-" * 92)
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"skip {p}: not found")
            continue
        g, ws, wks, m, s, kzs, ex = analyze_pgn(p)
        rate = (ws / g) if g else 0.0
        kz_rate = (wks / g) if g else 0.0
        spg = (s / g) if g else 0.0
        kspg = (kzs / g) if g else 0.0
        print(f"{p.name:<50}  {g:>5} {100*rate:>5.1f}% {100*kz_rate:>7.1f}% {spg:>7.2f} {kspg:>6.2f}")
        total_games += g
        total_with_sac += ws
        total_with_kz_sac += wks
        total_moves += m
        total_sacs += s
        total_kz_sacs += kzs
        all_examples.extend(ex)

    if total_games:
        agg = total_with_sac / total_games
        kz_agg = total_with_kz_sac / total_games
        print()
        print(f"AGGREGATE  games={total_games}  pyro_moves={total_moves}")
        print(f"  aggression_rate         = {100*agg:.1f}%   ({total_with_sac} games with >=1 sac)")
        print(f"  king_zone_sac_rate      = {100*kz_agg:.1f}%   ({total_with_kz_sac} games with >=1 KZ sac)  ← G9 target")
        print(f"  sacs_per_game           = {total_sacs/total_games:.2f}   ({total_sacs} total)")
        print(f"  kz_sacs_per_game        = {total_kz_sacs/total_games:.2f}   ({total_kz_sacs} total)  ← G9 target")

    if all_examples:
        print("\nFirst sac examples (KZ = in enemy king zone):")
        for file, idx, ply, san, s, kz in all_examples[:10]:
            marker = " [KZ]" if kz else ""
            print(f"  {file}  game {idx} ply {ply}: {san}  (see_proxy={s}){marker}")
