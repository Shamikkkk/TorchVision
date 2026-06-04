"""
Mechanism check for Experiment D (pyro-expD).

Runs AFTER training completes and BEFORE SPRT. Checks whether the l0w clip ±0.06
actually moved the mechanism (not just changed the loss number):

  1. Active-neuron count  — expect >150/256 (vs d1v3-clean baseline: ~50)
  2. Queen-missing eval   — expect < -500cp (vs d1v3-clean baseline: ~-84cp)
  3. Sibling ranking      — expect >=3/10 vs PeSTO (vs d1v3-clean baseline: 0/10)
  4. Engine binary check  — Python quant sim vs engine depth-1 for 2 positions:
                            signs must match; magnitudes should be in the same ballpark
                            (depth-1 != static eval, but the difference shouldn't flip signs)

If queen eval is still ~-84cp AND neurons still ~50/256: FALSIFIED — do not run SPRT.
If mechanism moved (neurons up, queen recovered, ranking improved): proceed to SPRT.

Run:
    cd backend
    python -m scripts.diag_mech
"""

import struct
import subprocess
from pathlib import Path
import chess

ROOT        = Path(__file__).resolve().parent.parent.parent
NEW_NNUE    = ROOT / "engine" / "pyro.nnue"
ENGINE_PATH = ROOT / "engine" / "target" / "release" / "pyro.exe"

# Baseline numbers from d1v3-clean (DIAGNOSTIC E)
BASELINE = {
    "active_neurons": 53,
    "dead_neurons":   145,
    "maxed_neurons":  58,
    "queen_missing":  -84,
    "sibling_agree":  0,
}

HIDDEN_SIZE = 256
INPUT_SIZE  = 768
QA  = 255
QB  = 64
MAGIC = b"\x4E\x4E\x55\x45"

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 0, 1, 2, 3, 4, 5
PIECE_MAP = {
    'P': (PAWN,   True),  'N': (KNIGHT, True),  'B': (BISHOP, True),
    'R': (ROOK,   True),  'Q': (QUEEN,  True),  'K': (KING,   True),
    'p': (PAWN,   False), 'n': (KNIGHT, False), 'b': (BISHOP, False),
    'r': (ROOK,   False), 'q': (QUEEN,  False), 'k': (KING,   False),
}

# ── loaders ─────────────────────────────────────────────────────────────────

def load_nnue(path: Path):
    data = path.read_bytes()
    assert data[:4] == MAGIC, f"Bad magic: {data[:4]!r}"
    off = 8
    n_ft_w = INPUT_SIZE * HIDDEN_SIZE
    ft_w_raw = struct.unpack_from(f"<{n_ft_w}h", data, off)
    ft_weights = [list(ft_w_raw[f*HIDDEN_SIZE:(f+1)*HIDDEN_SIZE]) for f in range(INPUT_SIZE)]
    off += n_ft_w * 2
    ft_bias    = list(struct.unpack_from(f"<{HIDDEN_SIZE}h", data, off)); off += HIDDEN_SIZE*2
    out_weights = list(struct.unpack_from(f"<{HIDDEN_SIZE*2}h", data, off)); off += HIDDEN_SIZE*2*2
    out_bias   = struct.unpack_from("<h", data, off)[0]
    return ft_weights, ft_bias, out_weights, out_bias


# ── inference ────────────────────────────────────────────────────────────────

def feature_index(perspective: bool, sq: int, piece_type: int, piece_color: bool) -> int:
    mirrored_sq = sq if perspective else (sq ^ 56)
    color_idx = 0 if (piece_color == perspective) else 1
    return color_idx * 6 * 64 + piece_type * 64 + mirrored_sq


def parse_fen_pieces(fen: str):
    parts = fen.split()
    placement, stm_str = parts[0], parts[1]
    pieces = []
    rank, file = 7, 0
    for ch in placement:
        if ch == '/':
            rank -= 1; file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = rank * 8 + file
            pt, is_white = PIECE_MAP[ch]
            pieces.append((sq, pt, is_white))
            file += 1
    return pieces, (stm_str == 'w')


def make_accumulators(ft_weights, ft_bias, pieces):
    white = list(ft_bias)
    black = list(ft_bias)
    for sq, pt, is_white in pieces:
        w_idx = feature_index(True,  sq, pt, is_white)
        b_idx = feature_index(False, sq, pt, is_white)
        for i in range(HIDDEN_SIZE):
            white[i] += ft_weights[w_idx][i]
            black[i] += ft_weights[b_idx][i]
    return white, black


def quant_eval_from_acc(white_acc, black_acc, out_weights, out_bias, stm: bool) -> int:
    stm_acc  = white_acc if stm else black_acc
    nstm_acc = black_acc if stm else white_acc
    out = out_bias
    for i in range(HIDDEN_SIZE):
        out += max(0, min(QA, stm_acc[i]))  * out_weights[i]
        out += max(0, min(QA, nstm_acc[i])) * out_weights[HIDDEN_SIZE + i]
    return out // (QA * QB)


def quant_eval(ft_weights, ft_bias, out_weights, out_bias, fen: str) -> int:
    pieces, stm = parse_fen_pieces(fen)
    white_acc, black_acc = make_accumulators(ft_weights, ft_bias, pieces)
    return quant_eval_from_acc(white_acc, black_acc, out_weights, out_bias, stm)


def engine_eval_d1(fen: str) -> int | None:
    inp = f"uci\nisready\nposition fen {fen}\ngo depth 1\nquit\n"
    r = subprocess.run([str(ENGINE_PATH)], input=inp, capture_output=True, text=True, timeout=30)
    score = None
    for line in r.stdout.splitlines():
        if line.startswith("info") and "score cp" in line:
            parts = line.split()
            idx = parts.index("cp")
            score = int(parts[idx+1])
    return score


def pesto_top_move(fen: str) -> str | None:
    inp = f"uci\nisready\nposition fen {fen}\ngo depth 1\nquit\n"
    r = subprocess.run([str(ENGINE_PATH), "--no-nnue"], input=inp, capture_output=True,
                       text=True, timeout=30)
    for line in r.stdout.splitlines():
        if line.startswith("bestmove"):
            parts = line.split()
            if len(parts) >= 2 and parts[1] != "(none)":
                return parts[1]
    return None


# ── STARTPOS helper ──────────────────────────────────────────────────────────

def startpos_pieces():
    pieces = []
    back_rank = [ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK]
    for f, pt in enumerate(back_rank):
        pieces.append((f, pt, True))
        pieces.append((f+8, PAWN, True))
    for f, pt in enumerate(back_rank):
        pieces.append((56+f, pt, False))
        pieces.append((48+f, PAWN, False))
    return pieces


# ── CHECK 1 — active neurons ─────────────────────────────────────────────────

def check_neurons(ft_weights, ft_bias, out_weights, out_bias):
    pieces = startpos_pieces()
    white_acc, black_acc = make_accumulators(ft_weights, ft_bias, pieces)

    active_w = sum(1 for v in white_acc if 0 < v < QA)
    dead_w   = sum(1 for v in white_acc if v <= 0)
    maxed_w  = sum(1 for v in white_acc if v >= QA)

    active_b = sum(1 for v in black_acc if 0 < v < QA)
    dead_b   = sum(1 for v in black_acc if v <= 0)
    maxed_b  = sum(1 for v in black_acc if v >= QA)

    print(f"\n  Startpos accumulators:")
    print(f"    White: active={active_w}, dead(<=0)={dead_w}, maxed(>=255)={maxed_w}")
    print(f"    Black: active={active_b}, dead(<=0)={dead_b}, maxed(>=255)={maxed_b}")

    baseline = BASELINE["active_neurons"]
    moved    = active_w > baseline * 2
    print(f"\n  Baseline (d1v3-clean): active={baseline}/256")
    print(f"  Now:                   active={active_w}/256  {'(MOVED ++)' if moved else '(unchanged)'}")

    return active_w, dead_w, maxed_w


# ── CHECK 2 — queen-missing eval ─────────────────────────────────────────────

def check_queen_eval(ft_weights, ft_bias, out_weights, out_bias):
    FEN_WQ_MISSING = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"
    FEN_BQ_MISSING = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    wq = quant_eval(ft_weights, ft_bias, out_weights, out_bias, FEN_WQ_MISSING)
    bq = quant_eval(ft_weights, ft_bias, out_weights, out_bias, FEN_BQ_MISSING)

    print(f"\n  Queen-missing eval:")
    print(f"    W queen missing: {wq:+d} cp  (should be ~-900, baseline: {BASELINE['queen_missing']:+d})")
    print(f"    B queen missing: {bq:+d} cp  (should be ~+900)")

    # Also report material-independent positions
    FEN_WROOK_MISSING = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w Kkq - 0 1"
    wr = quant_eval(ft_weights, ft_bias, out_weights, out_bias, FEN_WROOK_MISSING)
    print(f"    W rook missing : {wr:+d} cp  (should be ~-500)")

    moved = abs(wq) > abs(BASELINE["queen_missing"]) * 3
    print(f"\n  Baseline |queen-missing|: {abs(BASELINE['queen_missing'])} cp")
    print(f"  Now:                     {abs(wq)} cp  {'(RECOVERED ++)' if moved else '(still compressed)'}")

    return wq, bq


# ── CHECK 3 — sibling ranking ────────────────────────────────────────────────

FIXED_10_FENS = [
    # 10 positions extracted during DIAGNOSTIC E sibling ranking
    # We re-use the same sampling approach so comparison is fair
    "r2q1rk1/ppp2ppp/2n1bn2/3pp3/2B1P3/2NP1N2/PPP2PPP/R1BQR1K1 w - - 0 9",
    "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQ1RK1 w - - 4 5",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "rnbqkb1r/ppp2ppp/3p1n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4",
    "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5",
    "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 4 4",
    "rnbqkb1r/pp3ppp/2pp1n2/4p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 0 5",
    "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7",
    "r2qkb1r/ppp2ppp/2np1n2/1B2p3/4P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 2 6",
]

def is_quiet(board: chess.Board, move: chess.Move) -> bool:
    return not board.is_capture(move) and not board.gives_check(move)


def check_sibling_ranking(ft_weights, ft_bias, out_weights, out_bias):
    print(f"\n  Sibling ranking (same 10 positions as DIAGNOSTIC E):")
    print(f"    {'#':>3}  {'NNUE top':>8}  {'PeSTO top':>9}  {'agree?':>7}  {'#quiet':>6}")
    print("    " + "-" * 44)

    agreements = 0
    total = 0

    for idx, fen in enumerate(FIXED_10_FENS):
        board = chess.Board(fen)
        if board.is_game_over():
            continue
        quiet_moves = [m for m in board.legal_moves if is_quiet(board, m)]
        if len(quiet_moves) < 3:
            continue

        child_scores: dict[str, int] = {}
        for move in quiet_moves:
            board.push(move)
            pieces, stm = parse_fen_pieces(board.fen())
            ev = quant_eval(ft_weights, ft_bias, out_weights, out_bias, board.fen())
            child_scores[move.uci()] = -ev
            board.pop()

        nnue_top = max(child_scores, key=child_scores.get)
        pesto = pesto_top_move(fen)

        if pesto is None:
            print(f"    {idx+1:>3}  {nnue_top:>8}  {'N/A':>9}  {'skip':>7}")
            continue

        agree = (nnue_top == pesto)
        agreements += agree
        total += 1
        print(f"    {idx+1:>3}  {nnue_top:>8}  {pesto:>9}  {'YES' if agree else 'NO':>7}  {len(quiet_moves):>6}")

    rate = agreements / total if total > 0 else 0.0
    moved = agreements >= 3
    print(f"\n  Baseline (d1v3-clean): 0/10 = 0%")
    print(f"  Now: {agreements}/{total} = {rate:.0%}  {'(MOVED ++)' if moved else '(still scrambled)'}")
    return agreements, total


# ── CHECK 4 — engine binary vs Python quant ──────────────────────────────────

def check_engine_binary(ft_weights, ft_bias, out_weights, out_bias):
    print(f"\n  Engine binary vs Python quant (depth-1 vs static):")
    print(f"  NOTE: depth-1 searches one ply; signs should agree, magnitudes will differ.")

    positions = [
        ("Startpos (W2M)",     "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
        ("W queen missing",    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"),
    ]

    all_ok = True
    print(f"\n    {'Position':<25} {'Python':>8} {'Engine d1':>10}  sign-match?")
    print("    " + "-" * 55)
    for label, fen in positions:
        py_ev = quant_eval(ft_weights, ft_bias, out_weights, out_bias, fen)
        e1    = engine_eval_d1(fen)
        sign_match = (e1 is not None) and (
            (py_ev >= 0 and e1 >= 0) or
            (py_ev <= 0 and e1 <= 0) or
            abs(py_ev) < 50  # near-zero: don't require sign match
        )
        ok_str = "OK" if sign_match else "SIGN FLIP"
        if not sign_match:
            all_ok = False
        e1_str = f"{e1:+d}" if e1 is not None else "N/A"
        print(f"    {label:<25} {py_ev:>+8d} {e1_str:>10}  {ok_str}")

    print()
    verdict = "OK" if all_ok else "SIGN FLIP — possible engine binary bug"
    print(f"  Engine binary verdict: {verdict}")
    return all_ok


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("MECHANISM CHECK — Experiment D (pyro-expD)")
    print("=" * 72)

    if not NEW_NNUE.exists():
        print(f"\nERROR: {NEW_NNUE} not found. Run bullet_to_pyro_nnue.py first.")
        return

    print(f"\nLoading {NEW_NNUE}")
    ft_weights, ft_bias, out_weights, out_bias = load_nnue(NEW_NNUE)
    print(f"  out_bias: {out_bias}")
    print(f"  out_weights[0:4]: {out_weights[:4]}")

    print("\n" + "=" * 72)
    print("CHECK 1 — Active neurons in startpos accumulator")
    print("=" * 72)
    active, dead, maxed = check_neurons(ft_weights, ft_bias, out_weights, out_bias)

    print("\n" + "=" * 72)
    print("CHECK 2 — Queen-missing eval magnitude")
    print("=" * 72)
    wq_eval, bq_eval = check_queen_eval(ft_weights, ft_bias, out_weights, out_bias)

    print("\n" + "=" * 72)
    print("CHECK 3 — Sibling ranking (10 fixed positions)")
    print("=" * 72)
    agree_count, total = check_sibling_ranking(ft_weights, ft_bias, out_weights, out_bias)

    print("\n" + "=" * 72)
    print("CHECK 4 — Engine binary vs Python quant")
    print("=" * 72)
    engine_ok = check_engine_binary(ft_weights, ft_bias, out_weights, out_bias)

    # ── Final verdict ─────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("MECHANISM CHECK SUMMARY")
    print("=" * 72)

    print(f"\n  Metric                 d1v3-clean    Experiment D   Delta")
    print(f"  {'─'*58}")
    print(f"  Active neurons:        {BASELINE['active_neurons']:>5}/256       {active:>5}/256       {active - BASELINE['active_neurons']:>+5}")
    print(f"  Queen-missing eval:    {BASELINE['queen_missing']:>+8} cp     {wq_eval:>+8} cp     {wq_eval - BASELINE['queen_missing']:>+5}")
    print(f"  Sibling agreement:     {BASELINE['sibling_agree']:>5}/10        {agree_count:>5}/10        {agree_count - BASELINE['sibling_agree']:>+5}")
    print(f"  Engine binary:         OK            {'OK' if engine_ok else 'FAIL'}         {'  -' if engine_ok else '  !'}")

    neurons_moved = active > BASELINE["active_neurons"] * 2
    queen_moved   = abs(wq_eval) > abs(BASELINE["queen_missing"]) * 3
    ranking_moved = agree_count >= 3

    proceed = neurons_moved and queen_moved and ranking_moved and engine_ok

    print()
    if proceed:
        print("  VERDICT: MECHANISM MOVED on all metrics. Proceed to SPRT.")
    elif not engine_ok:
        print("  VERDICT: STOP — engine binary sign mismatch. Investigate before SPRT.")
    else:
        moved_flags = []
        if neurons_moved:  moved_flags.append("neurons")
        if queen_moved:    moved_flags.append("queen-eval")
        if ranking_moved:  moved_flags.append("sibling-ranking")
        not_moved = [m for m in ["neurons", "queen-eval", "sibling-ranking"]
                     if m not in moved_flags]
        print(f"  VERDICT: HYPOTHESIS {'PARTIALLY ' if moved_flags else ''}FALSIFIED.")
        print(f"    Moved: {moved_flags or 'none'}")
        print(f"    Not moved: {not_moved}")
        print(f"    Do NOT run SPRT. Re-examine root cause.")


if __name__ == "__main__":
    main()
