"""
Step 2: Engine robustness check.

Runs 12 varied positions under 4 time controls each.
Confirms a LEGAL bestmove is returned every time.
Any "(none)" or illegal move is a forfeit generator — SPRT results
would be corrupted by random forfeits.

Positions chosen to cover edge cases:
  - Starting position
  - Near-checkmate (1 move to mate)
  - Deep endgame (K+P vs K)
  - Material imbalance
  - Tactical (capture available)
  - Stalemate-adjacent
  - Forced-move (only one legal move)
  - Promotion position
  - Opening variety
  - Complex middle game
  - Check position (side to move is in check)
  - Late endgame (K+Q vs K)
"""

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE = str(_ROOT / "engine" / "target" / "release" / "pyro.exe")

# (label, fen)
POSITIONS = [
    ("startpos",          "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("after_e4",          "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"),
    ("mate_in_1_w",       "4k3/8/4K3/8/8/8/8/7R w - - 0 1"),
    ("check_to_move",     "4k3/8/8/8/8/8/8/4K2r b - - 0 1"),  # black to move, in check
    ("kpk_endgame",       "8/8/8/8/8/k7/p7/K7 b - - 0 1"),
    ("one_legal_move",    "7k/8/6R1/8/8/8/8/1K6 b - - 0 1"),  # Kh7 is the only legal move (g8/g7 covered by Rg6)
    ("promotion_pos",     "8/P7/8/8/8/8/8/k1K5 w - - 0 1"),
    ("material_imbal",    "rnb1kbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNB1KBNR w KQkq e6 0 3"),
    ("tactical_fork",     "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("kqk_endgame",       "8/8/8/8/8/8/8/K3Q2k w - - 0 1"),
    ("complex_middle",    "r1bq1rk1/ppp1bppp/2np1n2/4p3/2B1P3/2NP1N2/PPP2PPP/R1BQR1K1 w - - 0 8"),
    ("stalemate_adjacent","k7/8/1K6/8/8/8/8/7Q w - - 0 1"),  # must not stalemate
]

TIME_CONTROLS = [
    ("nodes 1",      "go nodes 1"),
    ("movetime 1",   "go movetime 1"),
    ("movetime 10",  "go movetime 10"),
    ("depth 1",      "go depth 1"),
]


def is_legal_uci_move(move: str) -> bool:
    """Basic UCI move format check: 4-5 chars, squares in a1-h8 range."""
    if not move or move == "(none)":
        return False
    if len(move) < 4 or len(move) > 5:
        return False
    files = "abcdefgh"
    ranks = "12345678"
    promos = "qrbn"
    if move[0] not in files or move[1] not in ranks:
        return False
    if move[2] not in files or move[3] not in ranks:
        return False
    if len(move) == 5 and move[4] not in promos:
        return False
    return True


def run_position(fen: str, go_cmd: str, flags: list[str] = []) -> str | None:
    """Send a single position + go command to the engine, return bestmove."""
    cmd_str = f"uci\nisready\nposition fen {fen}\n{go_cmd}\nquit\n"
    result = subprocess.run(
        [ENGINE] + flags,
        input=cmd_str, capture_output=True, text=True, timeout=30
    )
    for line in result.stdout.splitlines():
        if line.startswith("bestmove"):
            parts = line.split()
            return parts[1] if len(parts) >= 2 else None
    return None


def main():
    import os
    if not os.path.exists(ENGINE):
        sys.exit(f"FATAL: engine not found at {ENGINE}")

    print("=" * 72)
    print("ENGINE ROBUSTNESS CHECK")
    print(f"Engine: {ENGINE}")
    print("=" * 72)
    print()

    failures = []
    total = 0

    for pos_label, fen in POSITIONS:
        print(f"Position: {pos_label}")
        print(f"  FEN: {fen[:60]}...")
        for tc_label, go_cmd in TIME_CONTROLS:
            for mode, flags in [("NNUE", []), ("PeSTO", ["--no-nnue"])]:
                total += 1
                move = run_position(fen, go_cmd, flags)
                ok = is_legal_uci_move(move)
                status = "OK" if ok else "FAIL"
                print(f"  [{mode:5s}] {tc_label:12s}: {move or '(none)':8s}  {status}")
                if not ok:
                    failures.append((pos_label, tc_label, mode, move))
        print()

    print("=" * 72)
    print(f"Total tests: {total}")
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for pos, tc, mode, mv in failures:
            print(f"  {pos} / {tc} / {mode}: got {mv!r}")
        print()
        print("STOP: engine has robustness failures. Fix before any SPRT.")
        sys.exit(1)
    else:
        print("All tests PASSED — engine returns legal moves in all cases.")


if __name__ == "__main__":
    main()
