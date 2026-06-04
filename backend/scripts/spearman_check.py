"""
SF18-referenced sibling check — Spearman correlation between NNUE and SF18
on the same set of quiet child positions across ~15 mid-game positions.
Read-only. Informational, not a gate.
"""
import numpy as np
import subprocess, struct, sys, os
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
STOCKFISH = Path(r"C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe")

SF_DEPTH = 10            # depth used for SF eval of child positions
N_POSITIONS = 15
MAX_QUIET_PER_POS = 25   # cap to keep runtime reasonable

PIECE_MAP = {'P':0,'N':1,'B':2,'R':3,'Q':4,'K':5,
             'p':0,'n':1,'b':2,'r':3,'q':4,'k':5}

def feature_index(persp_white, sq, pt, is_white):
    msq = sq if persp_white else (sq ^ 56)
    cidx = 0 if (is_white == persp_white) else 1
    return cidx * 384 + pt * 64 + msq

def fen_to_pieces(fen):
    bp = fen.split()[0]; stm_w = fen.split()[1] == 'w'
    pieces = []; rank, file = 7, 0
    for ch in bp:
        if ch == '/': rank -= 1; file = 0
        elif ch.isdigit(): file += int(ch)
        else: pieces.append((rank*8+file, PIECE_MAP[ch], ch.isupper())); file += 1
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

def find_positions(n):
    out, seen = [], 0
    with open(SF18_DATA, "r") as f:
        for line in f:
            seen += 1
            if seen > 5_000_000 or len(out) >= n: break
            parts = line.strip().split("|")
            if len(parts) != 3: continue
            fen, s, _ = parts; fen = fen.strip()
            try: sc = int(s.strip())
            except: continue
            bp, stm = fen.split()[0], fen.split()[1]
            if bp.count('Q') != 1 or bp.count('q') != 1: continue
            fm = int(fen.split()[-1]) if fen.split()[-1].isdigit() else 1
            ply = fm*2 + (0 if stm == 'w' else 1)
            if ply < 20 or abs(sc) > 200: continue
            try:
                b = chess.Board(fen)
                if b.is_check(): continue
                quiet = [mv for mv in b.legal_moves
                         if not b.is_capture(mv) and not b.gives_check(mv)
                         and not mv.promotion]
                if len(quiet) < 6: continue
            except: continue
            out.append((fen, sc, len(quiet)))
    return out

class StockfishWorker:
    def __init__(self):
        self.p = subprocess.Popen(
            [str(STOCKFISH)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1
        )
        self._cmd("uci")
        self._wait_until("uciok")
        self._cmd("setoption name Hash value 64")
        self._cmd("setoption name Threads value 1")
        self._cmd("isready")
        self._wait_until("readyok")

    def _cmd(self, s):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()

    def _wait_until(self, token):
        while True:
            line = self.p.stdout.readline()
            if not line: return None
            if token in line: return line

    def eval_position(self, fen, depth=SF_DEPTH):
        self._cmd("ucinewgame")
        self._cmd(f"position fen {fen}")
        self._cmd(f"go depth {depth}")
        last_cp = None
        last_mate = None
        while True:
            line = self.p.stdout.readline()
            if not line: break
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    last_cp = int(parts[parts.index("cp")+1])
                    last_mate = None
                elif "mate" in parts:
                    last_mate = int(parts[parts.index("mate")+1])
                    last_cp = None
            if line.startswith("bestmove"):
                break
        if last_mate is not None:
            # represent mates as huge scores in the correct direction
            return 30000 if last_mate > 0 else -30000
        return last_cp if last_cp is not None else 0

    def close(self):
        try: self._cmd("quit")
        except: pass
        try: self.p.wait(timeout=2)
        except: self.p.kill()

def spearman(a, b):
    """Spearman rank correlation. Returns NaN if undefined."""
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    if len(a) < 3: return float('nan')
    # rank with average for ties
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    # subtract mean
    ra -= ra.mean(); rb -= rb.mean()
    denom = np.sqrt((ra**2).sum() * (rb**2).sum())
    if denom == 0: return float('nan')
    return float((ra * rb).sum() / denom)

if __name__ == "__main__":
    print("Loading weights...")
    l0w, l0b, l1w, l1b = load_raw()
    print(f"Sampling {N_POSITIONS} real mid-game positions...")
    positions = find_positions(N_POSITIONS)
    print(f"Found {len(positions)}. Starting Stockfish at depth {SF_DEPTH}...\n")
    sf = StockfishWorker()
    rhos = []
    print(f"{'#':<3} {'ply_score':>9} {'nQuiet':>7} {'rho':>7}  fen")
    print("-"*100)
    try:
        for i, (fen, sc, nq) in enumerate(positions, 1):
            b = chess.Board(fen)
            quiet = [mv for mv in b.legal_moves
                     if not b.is_capture(mv) and not b.gives_check(mv)
                     and not mv.promotion]
            quiet = quiet[:MAX_QUIET_PER_POS]
            nnue_evals, sf_evals = [], []
            for mv in quiet:
                b.push(mv)
                child_fen = b.fen()
                # eval is from STM perspective (=opponent here); negate for our STM
                n_ev = -float_eval(child_fen, l0w, l0b, l1w, l1b)
                s_ev = -sf.eval_position(child_fen)
                b.pop()
                nnue_evals.append(n_ev); sf_evals.append(s_ev)
            rho = spearman(nnue_evals, sf_evals)
            rhos.append(rho)
            print(f"{i:<3} {sc:>+9d} {len(quiet):>7d} {rho:>+7.3f}  {fen}")
    finally:
        sf.close()
    rho_arr = np.array([r for r in rhos if not np.isnan(r)])
    print()
    print(f"Mean Spearman rho across {len(rho_arr)} positions: {rho_arr.mean():+.3f}")
    print(f"Median: {np.median(rho_arr):+.3f}")
    print(f"Min: {rho_arr.min():+.3f}  Max: {rho_arr.max():+.3f}")
    print(f"Fraction rho > 0.3: {(rho_arr > 0.3).mean():.2f}")
    print(f"Fraction rho > 0.0: {(rho_arr > 0.0).mean():.2f}")
    print()
    print("Interpretation:")
    print("  mean rho > 0.3  -> ranking tracks SF18; expect SPRT materially above 0.7%")
    print("  mean rho ~ 0.0  -> genuinely scrambled; expect low SPRT")
    print("  mean rho < 0    -> anti-correlated (would be very weird)")
