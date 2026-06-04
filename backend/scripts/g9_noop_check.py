"""
G9 STEP 0 — no-op proof.
SPEC_BONUS=0 (default) MUST play byte-identical to no-G9 build on a fixed
suite of positions. Same bestmove and same nps/depth/nodes summary line.

Since we can't easily compare two binaries (the previous binary is gone),
we instead verify:
  (a) baseline run with SPEC_BONUS unset = SPEC_BONUS=0 (default) on the same
      position gives the same bestmove twice
  (b) varying SPEC_BONUS away from 0 should at minimum sometimes change
      something — sanity check the gate isn't dead code.
"""
import subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ENGINE = Path("engine/target/release/pyro.exe")

# 10 startpos-derived positions: opening tactics, mid-game, sac-friendly.
SUITE = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("after_1e4", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"),
    ("italian",  "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("french",   "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3"),
    ("sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    ("kgambit",  "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq - 0 2"),
    ("kid",      "rnbqk2r/ppp1ppbp/3p1np1/8/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5"),
    ("dragon",   "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"),
    ("greek_gift_attack", "r1bq1rk1/ppp2ppp/2n5/3pn3/1bB1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7"),
    ("king_attack_pos",   "r1b1k2r/ppp2ppp/2n5/3qp3/1bB5/2N2N2/PPPP1PPP/R1BQ1RK1 w kq - 0 7"),
]

def go(fen, depth=8, spec_bonus=None):
    cmd_lines = ["uci", "isready"]
    if spec_bonus is not None:
        cmd_lines.append(f"setoption name spec_bonus value {spec_bonus}")
    cmd_lines += [f"position fen {fen}", f"go depth {depth}", "quit"]
    cmd = "\n".join(cmd_lines) + "\n"
    r = subprocess.run([str(ENGINE)], input=cmd, capture_output=True,
                       text=True, timeout=30)
    bm = None
    last_info = ""
    for line in r.stdout.splitlines():
        if line.startswith("info"):
            last_info = line
        elif line.startswith("bestmove"):
            bm = line.split()[1]
            break
    return bm, last_info

if __name__ == "__main__":
    print(f"{'position':<22} {'BM(default)':>14} {'BM(SPEC=0)':>14} {'BM(SPEC=2000)':>16} {'identical=0':>12}")
    print("-" * 86)
    fails_default_eq_zero = 0
    differs_when_on = 0
    for label, fen in SUITE:
        bm_def, _ = go(fen, depth=8)
        bm_zero, _ = go(fen, depth=8, spec_bonus=0)
        bm_on, _ = go(fen, depth=8, spec_bonus=2000)
        match_default = (bm_def == bm_zero)
        if not match_default:
            fails_default_eq_zero += 1
        if bm_on != bm_def:
            differs_when_on += 1
        print(f"{label:<22} {bm_def:>14} {bm_zero:>14} {bm_on:>16} {'OK' if match_default else 'FAIL':>12}")
    print()
    print(f"default == SPEC=0: {len(SUITE)-fails_default_eq_zero}/{len(SUITE)} positions identical (must be {len(SUITE)}/{len(SUITE)})")
    print(f"SPEC=2000 differs from default on: {differs_when_on}/{len(SUITE)} positions (sanity — gate is alive when >0)")
    sys.exit(0 if fails_default_eq_zero == 0 else 1)
