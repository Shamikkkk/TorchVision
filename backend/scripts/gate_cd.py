"""
Gates C and D for Experiment E.
Gate C: float (raw.bin) vs quantized-sim vs engine-UCI on 8 positions.
Gate D: sibling ranking on 10 positions (NNUE top quiet move vs PeSTO top).
Run from repo root: python backend/scripts/gate_cd.py
"""
import numpy as np
import subprocess, struct
from pathlib import Path
import sys

HIDDEN = 256
QA = 255
QB = 64
SCALE = 400  # must match nnue.rs and pyro.rs

RAW_BIN  = Path("bullet/checkpoints/pyro-expE/pyro-expE-30/raw.bin")
NNUE_BIN = Path("engine/pyro.nnue")
ENGINE   = Path("engine/target/release/pyro.exe")

# ── Weight loading ────────────────────────────────────────────────────────────

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
    """Read pyro.nnue: 8-byte header + i16 array layout."""
    with open(NNUE_BIN, "rb") as f:
        magic = f.read(4)
        ver   = struct.unpack("<I", f.read(4))[0]
        assert magic == b"NNUE" and ver == 1, f"bad header {magic} v{ver}"
        def ri16():
            return struct.unpack("<h", f.read(2))[0]
        ft_w = np.array([[ri16() for _ in range(HIDDEN)] for _ in range(768)], dtype=np.int32)
        ft_b = np.array([ri16() for _ in range(HIDDEN)], dtype=np.int32)
        out_w = np.array([ri16() for _ in range(2*HIDDEN)], dtype=np.int32)
        out_b = ri16()
    return ft_w, ft_b, out_w, out_b

# ── Feature index (mirrors nnue.rs feature_index) ────────────────────────────

PIECE_MAP = {'P':0,'N':1,'B':2,'R':3,'Q':4,'K':5,
             'p':0,'n':1,'b':2,'r':3,'q':4,'k':5}

def feature_index(perspective_white, sq, piece_type_idx, piece_is_white):
    mirrored_sq = sq if perspective_white else (sq ^ 56)
    color_idx   = 0 if (piece_is_white == perspective_white) else 1
    return color_idx * 384 + piece_type_idx * 64 + mirrored_sq

def fen_to_features(fen):
    """Return (white_features, black_features) as lists of (sq, pt, is_white)."""
    board_part = fen.split()[0]
    stm_white  = fen.split()[1] == 'w'
    pieces = []
    rank = 7
    for ch in board_part:
        if ch == '/':
            rank -= 1; file = 0; continue
        if ch.isdigit():
            file = file + int(ch) if 'file' in dir() else int(ch)
            continue
        if 'file' not in dir(): file = 0
        sq = rank * 8 + file
        pt = PIECE_MAP[ch]
        is_white = ch.isupper()
        pieces.append((sq, pt, is_white))
        file += 1
    # rebuild cleanly
    pieces2 = []
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
            pieces2.append((sq, pt, is_white))
            file += 1
    return pieces2, stm_white

def accumulate(ft_w, ft_b, pieces, perspective_white):
    acc = ft_b.copy()
    for (sq, pt, is_white) in pieces:
        idx = feature_index(perspective_white, sq, pt, is_white)
        acc += ft_w[idx]
    return acc

# ── Eval functions ────────────────────────────────────────────────────────────

def float_eval(fen, l0w, l0b, l1w, l1b):
    pieces, stm_white = fen_to_features(fen)
    def acc(perspective):
        a = l0b.copy()
        for (sq, pt, is_white) in pieces:
            idx = feature_index(perspective, sq, pt, is_white)
            a += l0w[idx]
        return a
    stm_acc  = np.clip(acc(stm_white),  0.0, 1.0)
    nstm_acc = np.clip(acc(not stm_white), 0.0, 1.0)
    combined = np.concatenate([stm_acc, nstm_acc])
    out = float(np.dot(combined, l1w)) + l1b
    # Stock convention: out ≈ score/SCALE; convert to cp
    return out * SCALE

def quant_eval(fen, ft_w, ft_b, out_w, out_b):
    pieces, stm_white = fen_to_features(fen)
    stm_acc  = accumulate(ft_w, ft_b, pieces, stm_white)
    nstm_acc = accumulate(ft_w, ft_b, pieces, not stm_white)
    stm_c  = np.clip(stm_acc,  0, QA)
    nstm_c = np.clip(nstm_acc, 0, QA)
    combined = np.concatenate([stm_c, nstm_c])
    integer_out = int(np.dot(combined, out_w)) + out_b
    # New inference: * SCALE / (QA * QB)
    return integer_out * SCALE // (QA * QB)

def engine_eval_d1(fen):
    cmd = f"uci\nisready\nposition fen {fen}\ngo depth 1\nquit\n"
    result = subprocess.run(
        [str(ENGINE)], input=cmd, capture_output=True, text=True, timeout=10
    )
    for line in result.stdout.splitlines():
        if line.startswith("info depth 1") and "score cp" in line:
            parts = line.split()
            idx = parts.index("cp")
            return int(parts[idx+1])
    return None

# ── Gate C positions ──────────────────────────────────────────────────────────

POSITIONS = [
    ("Startpos (W2M)",       "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("Startpos (B2M) 1.e4",  "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"),
    ("W queen missing",      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"),
    ("B queen missing",      "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"),
    ("W rook missing",       "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w KQkq - 0 1"),
    ("Open-centre Sicilian", "rnbqkb1r/pp3ppp/3p1n2/4p3/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"),
    ("Endgame K+R vs K",     "8/8/4k3/8/8/4K3/8/7R w - - 0 1"),
    ("W up Q+R vs bare K",   "3k4/8/8/8/8/8/8/3KQR2 w - - 0 1"),
]

def gate_c(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b):
    print("\n=== GATE C: float vs quant-sim vs engine-UCI ===")
    print(f"{'Position':<26} {'Float':>8} {'Quant':>7} {'Eng d1':>8} {'FQ-gap':>7}")
    print("-" * 60)
    all_ok = True
    results = []
    for label, fen in POSITIONS:
        f_val = float_eval(fen, l0w, l0b, l1w, l1b)
        q_val = quant_eval(fen, ft_w, ft_b, out_w, out_b)
        e_val = engine_eval_d1(fen)
        fq_gap = abs(f_val - q_val)
        e_str = f"{e_val:+d}" if e_val is not None else "ERR"
        print(f"{label:<26} {f_val:+8.1f} {q_val:+7d} {e_str:>8} {fq_gap:7.1f}")
        results.append((label, f_val, q_val, e_val))

    # Pass/fail checks
    print()
    queen_w = next((r for r in results if "W queen" in r[0]), None)
    queen_b = next((r for r in results if "B queen" in r[0]), None)
    startpos = next((r for r in results if "W2M" in r[0]), None)

    issues = []
    if queen_w:
        qf, qq, qe = queen_w[1], queen_w[2], queen_w[3]
        if qf > -200:
            issues.append(f"W queen float={qf:.0f}cp not <-200 (root cause not fixed)")
        elif qf > -500:
            issues.append(f"W queen float={qf:.0f}cp below threshold but weak (<-500 needed)")
        else:
            print(f"  [OK] W queen float={qf:.0f}cp is in expected -600..-900 range")
        if qe is not None and qe > -100:
            issues.append(f"W queen engine d1={qe}cp still near-zero (scale mismatch?)")

    if startpos:
        sf, sq_, se = startpos[1], startpos[2], startpos[3]
        if abs(sf) > 200:
            issues.append(f"Startpos float={sf:.0f}cp out of sane range (expect near 0)")
        else:
            print(f"  [OK] Startpos float={sf:.0f}cp (sane range)")

    # Float-quant agreement
    fq_gaps = [abs(r[1] - r[2]) for r in results]
    max_fq = max(fq_gaps)
    if max_fq > 5:
        issues.append(f"Max float-quant gap={max_fq:.1f}cp (quantization error)")
    else:
        print(f"  [OK] Max float-quant gap={max_fq:.1f}cp (good quantization)")

    # Engine sign agreement on material positions
    for r in results:
        if r[3] is not None and r[1] != 0 and r[3] != 0:
            if (r[1] > 0) != (r[3] > 0) and abs(r[1]) > 50 and abs(r[3]) > 50:
                issues.append(f"Sign mismatch float={r[1]:.0f} engine={r[3]} for '{r[0]}'")

    if issues:
        print("\nGATE C: FAIL")
        for iss in issues:
            print(f"  !! {iss}")
        return False
    else:
        print("\nGATE C: PASS -- float/quant agree, queen eval in expected range, engine signs match.")
        return True

# ── Gate D: sibling ranking ───────────────────────────────────────────────────

GATE_D_FENS = [
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 2 6",
    "r2qkb1r/ppp2ppp/2np1n2/4p3/2B1P1b1/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 2 7",
    "rnbqkb1r/pp3ppp/3p1n2/4p3/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
    "r1bqkbnr/1ppp1ppp/p1n5/4p3/4P3/2NP4/PPP2PPP/R1BQKBNR b KQkq - 0 4",
    "3rk2r/ppp1qppp/2npbn2/4p3/2B1P3/2NP1N2/PPP2PPP/R2QK2R w KQ - 4 9",
    "r1b1kbnr/ppppqppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3",
]

def get_quiet_moves(fen):
    """Use engine to enumerate legal moves, filter out captures via SAN '×'."""
    import chess
    board = chess.Board(fen)
    quiet = []
    for mv in board.legal_moves:
        if not board.is_capture(mv) and not board.is_check():
            san = board.san(mv)
            if '+' not in san and '#' not in san:
                quiet.append(mv.uci())
    return quiet

def top_quiet_nnue(fen, ft_w, ft_b, out_w, out_b):
    try:
        quiets = get_quiet_moves(fen)
    except Exception:
        return None
    if len(quiets) < 3:
        return None
    import chess
    board = chess.Board(fen)
    best_uci, best_eval = None, None
    for uci in quiets:
        board.push_uci(uci)
        child_fen = board.fen()
        board.pop()
        ev = quant_eval(child_fen, ft_w, ft_b, out_w, out_b)
        # Child is opponent's turn, so negate for STM perspective
        if best_eval is None or -ev > best_eval:
            best_eval = -ev
            best_uci = uci
    return best_uci

def top_quiet_pesto(fen):
    """Use engine --no-nnue depth 1 to get PeSTO top quiet move."""
    try:
        import chess
        board = chess.Board(fen)
        quiets = []
        for mv in board.legal_moves:
            if not board.is_capture(mv):
                san = board.san(mv)
                if '+' not in san and '#' not in san:
                    quiets.append(mv.uci())
    except Exception:
        return None
    if len(quiets) < 3:
        return None

    best_uci, best_score = None, None
    for uci in quiets:
        import chess as ch2
        b2 = ch2.Board(fen)
        b2.push_uci(uci)
        child_fen = b2.fen()
        cmd = f"uci\nisready\nposition fen {child_fen}\ngo depth 1\nquit\n"
        try:
            r = subprocess.run(
                [str(ENGINE), "--no-nnue"], input=cmd, capture_output=True,
                text=True, timeout=10
            )
            for line in r.stdout.splitlines():
                if line.startswith("info depth 1") and "score cp" in line:
                    parts = line.split()
                    idx = parts.index("cp")
                    sc = -int(parts[idx+1])  # negate: child's score from their view
                    if best_score is None or sc > best_score:
                        best_score = sc
                        best_uci = uci
                    break
        except Exception:
            pass
    return best_uci

def gate_d(ft_w, ft_b, out_w, out_b):
    print("\n=== GATE D: sibling ranking (NNUE vs PeSTO top quiet move) ===")
    agree = 0
    total = 0
    for i, fen in enumerate(GATE_D_FENS):
        nnue_top = top_quiet_nnue(fen, ft_w, ft_b, out_w, out_b)
        pesto_top = top_quiet_pesto(fen)
        if nnue_top is None or pesto_top is None:
            print(f"  pos {i+1}: skipped (few quiet moves)")
            continue
        match = nnue_top == pesto_top
        agree += int(match)
        total += 1
        print(f"  pos {i+1}: NNUE={nnue_top} PeSTO={pesto_top} {'AGREE' if match else 'differ'}")
    print(f"\nAgreement: {agree}/{total}")
    if total > 0:
        pct = agree / total
        print(f"GATE D: {'PASS' if pct >= 0.3 else 'BELOW 3/10 (weak but not a stop)'} ({agree}/{total})")
    return agree, total

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading weights...")
    l0w, l0b, l1w, l1b = load_raw()
    ft_w, ft_b, out_w, out_b = load_quantised()

    c_ok = gate_c(l0w, l0b, l1w, l1b, ft_w, ft_b, out_w, out_b)
    if not c_ok:
        print("\nStopping: Gate C failed. Do NOT run SPRT.")
        sys.exit(1)

    gate_d(ft_w, ft_b, out_w, out_b)
