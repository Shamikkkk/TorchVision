"""
Four read-only diagnostics for expE Gate C failure.
Run from repo root: python backend/scripts/diag_expE.py
No retrain. No SPRT. Static eval only.
"""
import numpy as np
import subprocess, struct
from pathlib import Path
import sys, io

# Force UTF-8 stdout on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HIDDEN = 256
QA = 255
QB = 64
SCALE = 400

RAW_BIN   = Path("bullet/checkpoints/pyro-expE/pyro-expE-30/raw.bin")
NNUE_BIN  = Path("engine/pyro.nnue")
ENGINE    = Path("engine/target/release/pyro.exe")
SF18_DATA = Path("C:/torch_data/selfplay_sf18_d12.plain")

PIECE_MAP = {'P':0,'N':1,'B':2,'R':3,'Q':4,'K':5,
             'p':0,'n':1,'b':2,'r':3,'q':4,'k':5}

def feature_index(perspective_white, sq, piece_type_idx, piece_is_white):
    mirrored_sq = sq if perspective_white else (sq ^ 56)
    color_idx   = 0 if (piece_is_white == perspective_white) else 1
    return color_idx * 384 + piece_type_idx * 64 + mirrored_sq

def fen_to_pieces(fen):
    board_part = fen.split()[0]
    stm_white  = fen.split()[1] == 'w'
    pieces = []
    rank, file = 7, 0
    for ch in board_part:
        if ch == '/':
            rank -= 1; file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = rank * 8 + file
            pt = PIECE_MAP[ch]
            is_white = ch.isupper()
            pieces.append((sq, pt, is_white))
            file += 1
    return pieces, stm_white

def load_raw():
    data = np.fromfile(RAW_BIN, dtype=np.float32)
    n_l0w = 768 * HIDDEN
    n_l0b = HIDDEN
    n_l1w = 2 * HIDDEN
    l0w = data[:n_l0w].reshape(768, HIDDEN)
    l0b = data[n_l0w:n_l0w+n_l0b]
    l1w = data[n_l0w+n_l0b:n_l0w+n_l0b+n_l1w]
    l1b = float(data[n_l0w+n_l0b+n_l1w])
    return l0w, l0b, l1w, l1b

def load_quantised():
    with open(NNUE_BIN, "rb") as f:
        magic = f.read(4)
        ver = struct.unpack("<I", f.read(4))[0]
        assert magic == b"NNUE" and ver == 1
        def ri16():
            return struct.unpack("<h", f.read(2))[0]
        ft_w = np.array([[ri16() for _ in range(HIDDEN)] for _ in range(768)], dtype=np.int32)
        ft_b = np.array([ri16() for _ in range(HIDDEN)], dtype=np.int32)
        out_w = np.array([ri16() for _ in range(2*HIDDEN)], dtype=np.int32)
        out_b = ri16()
    return ft_w, ft_b, out_w, out_b

def float_eval_full(fen, l0w, l0b, l1w, l1b):
    """Return (stm_raw_acc, nstm_raw_acc, raw_output, cp)."""
    pieces, stm_white = fen_to_pieces(fen)
    def acc(persp):
        a = l0b.copy()
        for (sq, pt, is_white) in pieces:
            a += l0w[feature_index(persp, sq, pt, is_white)]
        return a
    stm_raw = acc(stm_white)
    nstm_raw = acc(not stm_white)
    stm_c = np.clip(stm_raw, 0.0, 1.0)
    nstm_c = np.clip(nstm_raw, 0.0, 1.0)
    combined = np.concatenate([stm_c, nstm_c])
    out_f = float(np.dot(combined, l1w)) + l1b
    return stm_raw, nstm_raw, out_f, out_f * SCALE

def quant_eval_full(fen, ft_w, ft_b, out_w, out_b):
    """Return (stm_raw_acc, nstm_raw_acc, integer_out)."""
    pieces, stm_white = fen_to_pieces(fen)
    def acc(persp):
        a = ft_b.copy().astype(np.int64)
        for (sq, pt, is_white) in pieces:
            a += ft_w[feature_index(persp, sq, pt, is_white)].astype(np.int64)
        return a
    stm_raw = acc(stm_white)
    nstm_raw = acc(not stm_white)
    stm_c = np.clip(stm_raw, 0, QA)
    nstm_c = np.clip(nstm_raw, 0, QA)
    combined = np.concatenate([stm_c, nstm_c])
    integer_out = int(np.dot(combined, out_w.astype(np.int64))) + int(out_b)
    return stm_raw, nstm_raw, integer_out

def cp_python_floor(integer_out):
    """Python floor division — diverges from Rust for negatives."""
    return integer_out * SCALE // (QA * QB)

def cp_rust_truncate(integer_out):
    """Rust-style integer division (truncate toward zero)."""
    p = integer_out * SCALE
    d = QA * QB
    if (p >= 0) == (d >= 0):
        return p // d
    else:
        return -((-p) // d) if p < 0 else -((p) // (-d))

def engine_eval_d1(fen):
    cmd = f"uci\nisready\nposition fen {fen}\ngo depth 1\nquit\n"
    r = subprocess.run([str(ENGINE)], input=cmd, capture_output=True, text=True, timeout=10)
    for line in r.stdout.splitlines():
        if line.startswith("info depth 1") and "score cp" in line:
            parts = line.split()
            return int(parts[parts.index("cp")+1])
    return None

# ============================================================================
# DIAG 1: symmetry of W queen missing vs B queen missing
# ============================================================================
def diag1(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b):
    print("\n" + "="*72)
    print("DIAG 1 — W-queen-missing vs B-queen-missing symmetry")
    print("="*72)
    fens = [
        ("Startpos (W2M)", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
        ("W queen miss",   "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"),
        ("B queen miss",   "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"),
    ]
    results = []
    for label, fen in fens:
        stm_f, nstm_f, out_f, cp_f = float_eval_full(fen, l0w, l0b, l1w, l1b)
        stm_q, nstm_q, int_q = quant_eval_full(fen, ft_w, ft_b, out_w, out_b)
        results.append((label, fen, out_f, cp_f, int_q, stm_f, nstm_f))
        print(f"\n{label}")
        print(f"  float raw output = {out_f:.6f}")
        print(f"  float cp         = {cp_f:+.3f}")
        print(f"  quant int_output = {int_q}")
        print(f"  cp (Py floor)    = {cp_python_floor(int_q):+d}")
        print(f"  cp (Rust trunc)  = {cp_rust_truncate(int_q):+d}")
        print(f"  stm  acc raw: min={stm_f.min():+.4f}  max={stm_f.max():+.4f}  mean={stm_f.mean():+.4f}")
        print(f"  nstm acc raw: min={nstm_f.min():+.4f}  max={nstm_f.max():+.4f}  mean={nstm_f.mean():+.4f}")

    # Are W and B queen missing TRULY identical?
    wq = results[1]
    bq = results[2]
    print("\n--- W vs B queen missing comparison ---")
    print(f"  W float raw = {wq[2]:.6f}")
    print(f"  B float raw = {bq[2]:.6f}")
    print(f"  diff        = {wq[2] - bq[2]:.6e}")
    print(f"  W int       = {wq[4]}")
    print(f"  B int       = {bq[4]}")
    print(f"  int diff    = {wq[4] - bq[4]}")
    # By design, feature_index gives identical idx 259 for both:
    # W queen at d1 (sq=3) from W persp: 0*384 + 4*64 + 3 = 259
    # B queen at d8 (sq=59) from B persp: 0*384 + 4*64 + (59^56=3) = 259
    # So the STM half accumulator is IDENTICAL (same features active).
    # The NSTM half differs only if board pieces from opposite color differ — but
    # in startpos the pieces are mirror-symmetric, so NSTM is also IDENTICAL.
    # If True, this is BY DESIGN of the symmetric encoding, not a learned property.
    stm_diff = np.abs(wq[5] - bq[5]).max()
    nstm_diff = np.abs(wq[6] - bq[6]).max()
    print(f"  max |stm_W - stm_B|  = {stm_diff:.6e}")
    print(f"  max |nstm_W - nstm_B|= {nstm_diff:.6e}")
    print("\n  EXPECTED by symmetric encoding: if startpos is mirror-symmetric and one")
    print("  queen-at-d-file is removed from the STM side, the W-stm and B-stm")
    print("  accumulators are LITERALLY THE SAME 256-d vector (and so is nstm).")
    print("  Identical output ≠ 'eval insensitive to queen' — it's a design property.")

# ============================================================================
# DIAG 2: material sweep
# ============================================================================
def diag2(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b):
    print("\n" + "="*72)
    print("DIAG 2 — Material sweep (remove each W piece type from startpos)")
    print("="*72)
    # All from startpos with one white piece removed; STM = white
    fens = [
        ("Startpos (base)",  "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
        ("- W Pawn (e2)",    "rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1"),
        ("- W Knight (b1)",  "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/R1BQKBNR w KQkq - 0 1"),
        ("- W Bishop (c1)",  "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RN1QKBNR w KQkq - 0 1"),
        ("- W Rook (a1)",    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w KQkq - 0 1"),
        ("- W Queen (d1)",   "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"),
    ]
    base_f = None
    base_q = None
    print(f"{'pos':<22} {'float cp':>10} {'Δfloat':>10} {'quant cp':>10} {'Δquant':>10}")
    print("-" * 72)
    for label, fen in fens:
        _, _, _, cp_f = float_eval_full(fen, l0w, l0b, l1w, l1b)
        _, _, int_q = quant_eval_full(fen, ft_w, ft_b, out_w, out_b)
        cp_q = cp_rust_truncate(int_q)
        if base_f is None:
            base_f = cp_f; base_q = cp_q
            print(f"{label:<22} {cp_f:+10.2f} {'(base)':>10} {cp_q:+10d} {'(base)':>10}")
        else:
            df = cp_f - base_f
            dq = cp_q - base_q
            print(f"{label:<22} {cp_f:+10.2f} {df:+10.2f} {cp_q:+10d} {dq:+10d}")
    print()
    print("Expected if material learned:  Q≈-900, R≈-500, B/N≈-300, P≈-100, monotonic")
    print("If all deltas are O(10-50cp) regardless of piece -> globally material-blind")

# ============================================================================
# DIAG 3: in-distribution queen-down position from SF18 training data
# ============================================================================
def count_piece(fen, piece):
    return fen.split()[0].count(piece)

def find_queen_down_positions():
    """Scan SF18 plain for positions where one side has 0 queens but is mid-game.
    Pick examples with large negative score (from STM perspective)."""
    if not SF18_DATA.exists():
        return []
    print(f"  Scanning {SF18_DATA} for mid-game queen-down positions...")
    candidates = []
    seen = 0
    with open(SF18_DATA, "r") as f:
        for line in f:
            seen += 1
            if seen > 2_000_000:  # cap search
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
            # Parse fen
            board, stm = fen.split()[0], fen.split()[1]
            wQ = board.count('Q')
            bQ = board.count('q')
            full_move = int(fen.split()[-1]) if fen.split()[-1].isdigit() else 1
            ply = full_move * 2 + (0 if stm == 'w' else 1)
            # STM has no queen, opponent has 1 queen, mid-game, large negative score
            if stm == 'w' and wQ == 0 and bQ == 1 and ply >= 16 and score <= -700:
                candidates.append((fen, score, "white"))
            elif stm == 'b' and bQ == 0 and wQ == 1 and ply >= 16 and score <= -700:
                candidates.append((fen, score, "black"))
            if len(candidates) >= 5:
                break
    print(f"  Scanned {seen} lines, found {len(candidates)} candidates.")
    return candidates

def diag3(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b):
    print("\n" + "="*72)
    print("DIAG 3 — In-distribution check: real SF18 queen-down positions")
    print("="*72)
    candidates = find_queen_down_positions()
    if not candidates:
        print("  No candidates found (SF18 file missing or no matching positions).")
        return []
    print(f"\n{'STM no Q':>10} {'SF18 cp':>10} {'NNUE float cp':>16} {'NNUE quant cp':>16}")
    print("-" * 72)
    rows = []
    for i, (fen, sf18_score, side) in enumerate(candidates):
        _, _, _, cp_f = float_eval_full(fen, l0w, l0b, l1w, l1b)
        _, _, int_q = quant_eval_full(fen, ft_w, ft_b, out_w, out_b)
        cp_q = cp_rust_truncate(int_q)
        rows.append((fen, side, sf18_score, cp_f, cp_q))
        print(f"{side:>10} {sf18_score:>+10d} {cp_f:>+16.2f} {cp_q:>+16d}")
        print(f"  FEN: {fen}")
    print()
    print("If NNUE float cp ≈ SF18 cp on these REAL queen-down positions -> in-distribution OK.")
    print("If NNUE float cp ≈ 0 even here -> network IS globally material-blind, not OOD.")
    return rows

# ============================================================================
# DIAG 4: quant-path rounding (Python floor vs Rust truncate vs engine)
# ============================================================================
def diag4(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b):
    print("\n" + "="*72)
    print("DIAG 4 — Quant path rounding check: Python // vs Rust integer / vs engine")
    print("="*72)
    fens = [
        ("Startpos",          "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
        ("W queen missing",   "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"),
        ("W rook missing",    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w KQkq - 0 1"),
        ("Endgame K+R vs K",  "8/8/4k3/8/8/4K3/8/7R w - - 0 1"),
        ("W up Q+R vs bare K","3k4/8/8/8/8/8/8/3KQR2 w - - 0 1"),
    ]
    print(f"{'pos':<22} {'int_out':>10} {'Py //':>8} {'Rust /':>8} {'float cp':>10} {'diff':>8}")
    print("-" * 72)
    for label, fen in fens:
        _, _, _, cp_f = float_eval_full(fen, l0w, l0b, l1w, l1b)
        _, _, int_q = quant_eval_full(fen, ft_w, ft_b, out_w, out_b)
        py = cp_python_floor(int_q)
        rs = cp_rust_truncate(int_q)
        diff = py - rs
        print(f"{label:<22} {int_q:>10} {py:>+8d} {rs:>+8d} {cp_f:>+10.2f} {diff:>+8d}")
    print()
    print("Py // != Rust / for any row -> gate_cd.py used WRONG rounding (artifact).")
    print("Use Rust-truncate column to compare with engine.")

# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("Loading weights...")
    l0w, l0b, l1w, l1b = load_raw()
    ft_w, ft_b, out_w, out_b = load_quantised()

    diag1(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b)
    diag2(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b)
    rows = diag3(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b)
    diag4(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b)
    print("\nDone.")
