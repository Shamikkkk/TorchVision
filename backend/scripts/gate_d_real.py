"""
Corrected Gate D — sibling ranking on REAL mid-game positions from SF18.
Both sides have queens, ply>=20, roughly balanced (|score|<=200cp).
For each position: NNUE-top-quiet (via float static eval) vs PeSTO-top-quiet
(via engine --no-nnue depth 1).
"""
import numpy as np
import subprocess, struct, sys
from pathlib import Path
import chess

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HIDDEN = 256
QA = 255
QB = 64
SCALE = 400

RAW_BIN   = Path("bullet/checkpoints/pyro-expE/pyro-expE-30/raw.bin")
ENGINE    = Path("engine/target/release/pyro.exe")
SF18_DATA = Path("C:/torch_data/selfplay_sf18_d12.plain")

PIECE_MAP = {'P':0,'N':1,'B':2,'R':3,'Q':4,'K':5,
             'p':0,'n':1,'b':2,'r':3,'q':4,'k':5}

def feature_index(persp_white, sq, pt, is_white):
    msq = sq if persp_white else (sq ^ 56)
    cidx = 0 if (is_white == persp_white) else 1
    return cidx * 384 + pt * 64 + msq

def fen_to_pieces(fen):
    bp = fen.split()[0]
    stm_w = fen.split()[1] == 'w'
    pieces = []
    rank, file = 7, 0
    for ch in bp:
        if ch == '/':
            rank -= 1; file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = rank*8 + file
            pieces.append((sq, PIECE_MAP[ch], ch.isupper()))
            file += 1
    return pieces, stm_w

def load_raw():
    data = np.fromfile(RAW_BIN, dtype=np.float32)
    n_l0w = 768 * HIDDEN
    l0w = data[:n_l0w].reshape(768, HIDDEN)
    l0b = data[n_l0w:n_l0w+HIDDEN]
    l1w = data[n_l0w+HIDDEN:n_l0w+HIDDEN+2*HIDDEN]
    l1b = float(data[n_l0w+HIDDEN+2*HIDDEN])
    return l0w, l0b, l1w, l1b

def float_eval(fen, l0w, l0b, l1w, l1b):
    pieces, stm_w = fen_to_pieces(fen)
    def acc(p):
        a = l0b.copy()
        for sq, pt, iw in pieces:
            a += l0w[feature_index(p, sq, pt, iw)]
        return a
    stm = np.clip(acc(stm_w), 0.0, 1.0)
    nstm = np.clip(acc(not stm_w), 0.0, 1.0)
    return (float(np.dot(np.concatenate([stm, nstm]), l1w)) + l1b) * SCALE

def find_real_midgame_positions(n=10):
    """Mid-game (ply>=20), both sides have queens, roughly balanced (|score|<=200)."""
    out = []
    seen = 0
    with open(SF18_DATA, "r") as f:
        for line in f:
            seen += 1
            if seen > 5_000_000 or len(out) >= n:
                break
            parts = line.strip().split("|")
            if len(parts) != 3: continue
            fen, s, _ = parts
            fen = fen.strip()
            try: sc = int(s.strip())
            except: continue
            bp, stm = fen.split()[0], fen.split()[1]
            if bp.count('Q') != 1 or bp.count('q') != 1: continue
            fm = int(fen.split()[-1]) if fen.split()[-1].isdigit() else 1
            ply = fm*2 + (0 if stm == 'w' else 1)
            if ply < 20 or abs(sc) > 200: continue
            # Need at least 5 quiet moves
            try:
                b = chess.Board(fen)
                if b.is_check(): continue
                quiet = [mv for mv in b.legal_moves
                         if not b.is_capture(mv) and not b.gives_check(mv)
                         and not mv.promotion]
                if len(quiet) < 5: continue
            except: continue
            out.append((fen, sc))
    return out

def top_quiet_nnue(fen, l0w, l0b, l1w, l1b):
    b = chess.Board(fen)
    quiet = [mv for mv in b.legal_moves
             if not b.is_capture(mv) and not b.gives_check(mv) and not mv.promotion]
    if len(quiet) < 3: return None, 0
    best_uci, best = None, None
    for mv in quiet:
        b.push(mv)
        # child position is opponent's turn — eval is from THEIR STM perspective.
        # negate for our STM.
        ev = -float_eval(b.fen(), l0w, l0b, l1w, l1b)
        b.pop()
        if best is None or ev > best:
            best = ev; best_uci = mv.uci()
    return best_uci, len(quiet)

def top_quiet_pesto(fen):
    b = chess.Board(fen)
    quiet = [mv for mv in b.legal_moves
             if not b.is_capture(mv) and not b.gives_check(mv) and not mv.promotion]
    if len(quiet) < 3: return None
    best_uci, best = None, None
    for mv in quiet:
        b.push(mv)
        child_fen = b.fen()
        b.pop()
        cmd = f"uci\nisready\nposition fen {child_fen}\ngo depth 1\nquit\n"
        try:
            r = subprocess.run([str(ENGINE), "--no-nnue"], input=cmd,
                               capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            continue
        sc_cp = None
        for line in r.stdout.splitlines():
            if line.startswith("info depth 1") and "score cp" in line:
                parts = line.split()
                sc_cp = int(parts[parts.index("cp")+1])
                break
        if sc_cp is None: continue
        # child is opponent's STM, negate to our perspective
        our_sc = -sc_cp
        if best is None or our_sc > best:
            best = our_sc; best_uci = mv.uci()
    return best_uci

if __name__ == "__main__":
    print("Loading weights...")
    l0w, l0b, l1w, l1b = load_raw()
    print("Sampling real mid-game positions (balanced, both sides have queens)...")
    positions = find_real_midgame_positions(n=10)
    print(f"Found {len(positions)} positions.\n")
    print(f"{'#':<3} {'SF18cp':>7} {'NNUE top':>10} {'PeSTO top':>10} {'match':>7}  fen")
    print("-"*100)
    agree = 0
    for i, (fen, sc) in enumerate(positions, 1):
        n_top, n_quiet = top_quiet_nnue(fen, l0w, l0b, l1w, l1b)
        p_top = top_quiet_pesto(fen)
        if n_top is None or p_top is None:
            print(f"{i:<3} {sc:>+7d} {'-':>10} {'-':>10} {'skip':>7}")
            continue
        match = (n_top == p_top)
        agree += int(match)
        marker = "AGREE" if match else "differ"
        print(f"{i:<3} {sc:>+7d} {n_top:>10} {p_top:>10} {marker:>7}  {fen}")
    print()
    print(f"Sibling ranking on REAL mid-game positions: {agree}/10")
    print(f"Baseline (old startpos-like Gate D on d2-evalonly): 0/10")
    print(f"Baseline (expD): 2/10")
