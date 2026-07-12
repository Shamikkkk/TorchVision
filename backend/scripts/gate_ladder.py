"""
Parameterized gate suite for the capacity-ladder candidates (July 2026).
Runs the three advisory gates off a Bullet raw.bin (float32 weights):

  Gate A  — l1w continuity (not pinned at the clip boundary)
  Gate M  — DIAG-3-style material pricing: real SF18 queen-down positions,
            NNUE float cp vs SF18 cp
  Gate S  — spearman_check: move-ranking correlation vs SF18 depth 10 on
            quiet children of ~15 mid-game positions (THE key gate;
            expE scored +0.155, "tracks SF18" bar is 0.3)

Width- and activation-generic so 512-wide and SCReLU nets gate without
touching the engine. Read-only; advisory — the SPRT is ground truth.

Usage (from repo root):
    python backend/scripts/gate_ladder.py --raw bullet/checkpoints/pyro-gpu/pyro-gpu-30/raw.bin \
        --hidden 256 --activation crelu --label candidate-0
"""
import argparse
import subprocess
import sys
from pathlib import Path

import chess
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCALE = 400
CLIP = 1.98

SF18_DATA = Path("C:/torch_data/selfplay_sf18_d12.plain")
STOCKFISH = Path(r"C:\Users\shami\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe")

SF_DEPTH = 10
N_POSITIONS = 15
MAX_QUIET_PER_POS = 25

PIECE_MAP = {'P': 0, 'N': 1, 'B': 2, 'R': 3, 'Q': 4, 'K': 5,
             'p': 0, 'n': 1, 'b': 2, 'r': 3, 'q': 4, 'k': 5}


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
            rank -= 1
            file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            pieces.append((rank * 8 + file, PIECE_MAP[ch], ch.isupper()))
            file += 1
    return pieces, stm_w


class Net:
    def __init__(self, raw_path, hidden, activation):
        self.hidden = hidden
        self.activation = activation
        data = np.fromfile(raw_path, dtype=np.float32)
        n_l0w = 768 * hidden
        expected = n_l0w + hidden + 2 * hidden + 1
        if len(data) < expected:
            raise ValueError(
                f"raw.bin has {len(data)} floats, need {expected} for hidden={hidden}")
        if len(data) > expected:
            # bullet may append a footer; tolerate a small trailer only
            trailer = len(data) - expected
            if trailer * 4 > 256:
                raise ValueError(
                    f"raw.bin has {len(data)} floats, expected {expected} "
                    f"(+{trailer} extra) — wrong --hidden?")
            print(f"  (ignoring {trailer * 4}-byte trailer)")
        self.l0w = data[:n_l0w].reshape(768, hidden)
        self.l0b = data[n_l0w:n_l0w + hidden]
        self.l1w = data[n_l0w + hidden:n_l0w + hidden + 2 * hidden]
        self.l1b = float(data[n_l0w + hidden + 2 * hidden])

    def _act(self, x):
        c = np.clip(x, 0.0, 1.0)
        if self.activation == "screlu":
            return c * c
        return c

    def eval_cp(self, fen):
        pieces, stm_w = fen_to_pieces(fen)

        def acc(persp):
            a = self.l0b.copy()
            for sq, pt, iw in pieces:
                a += self.l0w[feature_index(persp, sq, pt, iw)]
            return a

        stm = self._act(acc(stm_w))
        nstm = self._act(acc(not stm_w))
        return (float(np.dot(np.concatenate([stm, nstm]), self.l1w)) + self.l1b) * SCALE


# ---------------------------------------------------------------------------
# Gate A — l1w continuity
# ---------------------------------------------------------------------------
def gate_a(net, label):
    l1w = net.l1w
    print(f"\n=== Gate A: {label} ===")
    print(f"l1w n={len(l1w)}  min={l1w.min():.4f}  max={l1w.max():.4f}  "
          f"mean_abs={np.abs(l1w).mean():.4f}  std={l1w.std():.4f}")
    sat = float(np.mean(np.abs(l1w) >= 0.95 * CLIP))
    print(f"  |w| >= 0.95xclip ({0.95 * CLIP:.3f}): {100 * sat:.1f}%")
    ok = sat <= 0.90
    print(f"GATE A: {'PASS' if ok else 'FAIL'} — "
          f"{'continuous spread' if ok else 'l1w pinned at clip'} ({100 * sat:.0f}% near-saturated)")
    return ok, sat


# ---------------------------------------------------------------------------
# Gate M — material pricing on real SF18 queen-down positions (DIAG-3 style)
# ---------------------------------------------------------------------------
def find_queen_down_positions(n=5):
    candidates = []
    seen = 0
    with open(SF18_DATA, "r") as f:
        for line in f:
            seen += 1
            if seen > 2_000_000 or len(candidates) >= n:
                break
            parts = line.strip().split("|")
            if len(parts) != 3:
                continue
            fen, score_s, _ = parts
            fen = fen.strip()
            try:
                score = int(score_s.strip())
            except ValueError:
                continue
            board, stm = fen.split()[0], fen.split()[1]
            wQ, bQ = board.count('Q'), board.count('q')
            full_move = int(fen.split()[-1]) if fen.split()[-1].isdigit() else 1
            ply = full_move * 2 + (0 if stm == 'w' else 1)
            if stm == 'w' and wQ == 0 and bQ == 1 and ply >= 16 and score <= -700:
                candidates.append((fen, score))
            elif stm == 'b' and bQ == 0 and wQ == 1 and ply >= 16 and score <= -700:
                candidates.append((fen, score))
    return candidates


def gate_m(net, label):
    print(f"\n=== Gate M (material pricing, DIAG-3): {label} ===")
    candidates = find_queen_down_positions()
    if not candidates:
        print("  No queen-down positions found — SKIP")
        return None
    ratios = []
    print(f"{'SF18 cp':>10} {'NNUE cp':>10} {'ratio':>7}")
    for fen, sf_cp in candidates:
        nn_cp = net.eval_cp(fen)
        ratio = nn_cp / sf_cp if sf_cp else float('nan')
        ratios.append(ratio)
        print(f"{sf_cp:>+10d} {nn_cp:>+10.1f} {ratio:>7.2f}  {fen}")
    mean_ratio = float(np.mean(ratios))
    # In-distribution pricing "OK" if NNUE sees the queen deficit at >=half
    # its SF18 magnitude with the right sign on average.
    ok = mean_ratio >= 0.5
    print(f"GATE M: {'PASS' if ok else 'FAIL'} — mean NNUE/SF18 ratio {mean_ratio:.2f} "
          f"(>=0.50 = queen deficit priced)")
    return ok, mean_ratio


# ---------------------------------------------------------------------------
# Gate S — Spearman move-ranking correlation vs SF18
# ---------------------------------------------------------------------------
def find_spearman_positions(n):
    out, seen = [], 0
    with open(SF18_DATA, "r") as f:
        for line in f:
            seen += 1
            if seen > 5_000_000 or len(out) >= n:
                break
            parts = line.strip().split("|")
            if len(parts) != 3:
                continue
            fen, s, _ = parts
            fen = fen.strip()
            try:
                sc = int(s.strip())
            except ValueError:
                continue
            bp, stm = fen.split()[0], fen.split()[1]
            if bp.count('Q') != 1 or bp.count('q') != 1:
                continue
            fm = int(fen.split()[-1]) if fen.split()[-1].isdigit() else 1
            ply = fm * 2 + (0 if stm == 'w' else 1)
            if ply < 20 or abs(sc) > 200:
                continue
            try:
                b = chess.Board(fen)
                if b.is_check():
                    continue
                quiet = [mv for mv in b.legal_moves
                         if not b.is_capture(mv) and not b.gives_check(mv)
                         and not mv.promotion]
                if len(quiet) < 6:
                    continue
            except Exception:
                continue
            out.append(fen)
    return out


class StockfishWorker:
    def __init__(self):
        self.p = subprocess.Popen(
            [str(STOCKFISH)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1)
        self._cmd("uci")
        self._wait("uciok")
        self._cmd("setoption name Hash value 64")
        self._cmd("setoption name Threads value 1")
        self._cmd("isready")
        self._wait("readyok")

    def _cmd(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def _wait(self, token):
        while True:
            line = self.p.stdout.readline()
            if not line or token in line:
                return line

    def eval_position(self, fen, depth=SF_DEPTH):
        self._cmd("ucinewgame")
        self._cmd(f"position fen {fen}")
        self._cmd(f"go depth {depth}")
        last_cp, last_mate = None, None
        while True:
            line = self.p.stdout.readline()
            if not line:
                break
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    last_cp = int(parts[parts.index("cp") + 1])
                    last_mate = None
                elif "mate" in parts:
                    last_mate = int(parts[parts.index("mate") + 1])
                    last_cp = None
            if line.startswith("bestmove"):
                break
        if last_mate is not None:
            return 30000 if last_mate > 0 else -30000
        return last_cp if last_cp is not None else 0

    def close(self):
        try:
            self._cmd("quit")
        except Exception:
            pass
        try:
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


def spearman(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 3:
        return float('nan')
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    if denom == 0:
        return float('nan')
    return float((ra * rb).sum() / denom)


def gate_s(net, label, sf_evals_cache):
    print(f"\n=== Gate S (Spearman vs SF18 d{SF_DEPTH}): {label} ===")
    rhos = []
    for i, (fen, children) in enumerate(sf_evals_cache, 1):
        nnue_evals = [-net.eval_cp(child_fen) for child_fen, _ in children]
        sf_evals = [-s for _, s in children]
        rho = spearman(nnue_evals, sf_evals)
        rhos.append(rho)
        print(f"  pos {i:<3} n={len(children):<3} rho={rho:+.3f}")
    arr = np.array([r for r in rhos if not np.isnan(r)])
    print(f"Mean rho: {arr.mean():+.3f}  median {np.median(arr):+.3f}  "
          f"min {arr.min():+.3f}  max {arr.max():+.3f}")
    return float(arr.mean())


def build_sf_cache():
    """SF child evals are net-independent — compute once, reuse per candidate."""
    print(f"Sampling {N_POSITIONS} mid-game positions and running SF18 d{SF_DEPTH} "
          f"on quiet children (once, shared across candidates)...")
    positions = find_spearman_positions(N_POSITIONS)
    sf = StockfishWorker()
    cache = []
    try:
        for fen in positions:
            b = chess.Board(fen)
            quiet = [mv for mv in b.legal_moves
                     if not b.is_capture(mv) and not b.gives_check(mv)
                     and not mv.promotion][:MAX_QUIET_PER_POS]
            children = []
            for mv in quiet:
                b.push(mv)
                cf = b.fen()
                children.append((cf, sf.eval_position(cf)))
                b.pop()
            cache.append((fen, children))
    finally:
        sf.close()
    return cache


def main():
    ap = argparse.ArgumentParser(description="Capacity-ladder gate suite")
    ap.add_argument("--raw", action="append", required=True,
                    help="Path to raw.bin (repeatable)")
    ap.add_argument("--hidden", action="append", type=int, required=True,
                    help="Hidden size per --raw (repeatable, same order)")
    ap.add_argument("--activation", action="append", required=True,
                    choices=["crelu", "screlu"],
                    help="Activation per --raw (repeatable, same order)")
    ap.add_argument("--label", action="append", required=True,
                    help="Label per --raw (repeatable, same order)")
    args = ap.parse_args()
    if not (len(args.raw) == len(args.hidden) == len(args.activation) == len(args.label)):
        ap.error("--raw/--hidden/--activation/--label counts must match")

    nets = []
    for raw, hidden, act, label in zip(args.raw, args.hidden, args.activation, args.label):
        print(f"Loading {label}: {raw} (hidden={hidden}, {act})")
        nets.append((Net(raw, hidden, act), label))

    sf_cache = build_sf_cache()

    summary = []
    for net, label in nets:
        a_ok, a_sat = gate_a(net, label)
        m = gate_m(net, label)
        rho = gate_s(net, label, sf_cache)
        summary.append((label, a_ok, a_sat, m, rho))

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"{'candidate':<22} {'GateA':>6} {'sat%':>6} {'GateM':>6} {'M-ratio':>8} {'rho':>7}")
    for label, a_ok, a_sat, m, rho in summary:
        m_str = "SKIP" if m is None else ("PASS" if m[0] else "FAIL")
        m_ratio = "" if m is None else f"{m[1]:8.2f}"
        print(f"{label:<22} {'PASS' if a_ok else 'FAIL':>6} {100 * a_sat:>5.1f}% "
              f"{m_str:>6} {m_ratio:>8} {rho:>+7.3f}")
    print("\nDecision bar: rho >= 0.3 (and > expE's +0.155) earns the SPRT; "
          "< 0.25 across all candidates = stop.")


if __name__ == "__main__":
    main()
