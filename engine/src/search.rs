use crate::board::Board;
use crate::movegen::{self, Move, generate_moves, is_in_check, make_move};
use crate::nnue;

use std::cell::Cell;

const INF: i32 = 100_000;
const CHECKMATE: i32 = 50_000;

// ---------------------------------------------------------------------------
// Transposition table
// ---------------------------------------------------------------------------

const TT_SIZE: usize = 1 << 20; // ~1M entries (16 MB)

const TT_EXACT: u8 = 0;
const TT_LOWER: u8 = 1; // score is a lower bound (failed high)
const TT_UPPER: u8 = 2; // score is an upper bound (failed low)

#[derive(Clone, Copy)]
struct TTEntry {
    hash: u64,
    score: i32,
    depth: u8,
    flag: u8,
    gen: u8, // iterative deepening generation
    best_from: u8, // 64 = no move
    best_to: u8,
}

impl TTEntry {
    const EMPTY: Self = TTEntry {
        hash: 0, score: 0, depth: 0, flag: 0, gen: 0,
        best_from: 64, best_to: 64,
    };

    fn best_move(&self) -> Option<(u8, u8)> {
        if self.best_from < 64 {
            Some((self.best_from, self.best_to))
        } else {
            None
        }
    }
}

pub struct TTable {
    entries: Vec<TTEntry>,
    gen: u8, // current generation
}

impl TTable {
    pub fn new() -> Self {
        TTable {
            entries: vec![TTEntry::EMPTY; TT_SIZE],
            gen: 0,
        }
    }

    /// Advance to the next iterative deepening generation.
    fn next_gen(&mut self) {
        self.gen = self.gen.wrapping_add(1);
    }

    /// Probe the TT. Returns the entry only if the hash matches.
    /// The caller decides whether to trust the score (check entry.gen).
    fn probe(&self, hash: u64) -> Option<&TTEntry> {
        let entry = &self.entries[hash as usize & (TT_SIZE - 1)];
        if entry.hash == hash { Some(entry) } else { None }
    }

    fn store(&mut self, hash: u64, depth: u8, score: i32, flag: u8, best: Option<(u8, u8)>) {
        let idx = hash as usize & (TT_SIZE - 1);
        let old = &self.entries[idx];
        // Replace if: empty, current gen with deeper/equal depth, or stale gen
        if old.hash == 0 || old.gen != self.gen || depth >= old.depth {
            self.entries[idx] = TTEntry {
                hash,
                score,
                depth,
                flag,
                gen: self.gen,
                best_from: best.map_or(64, |m| m.0),
                best_to: best.map_or(64, |m| m.1),
            };
        }
    }
}

/// Adjust mate scores for TT storage (make ply-independent).
fn tt_score_store(score: i32, ply: usize) -> i32 {
    if score > CHECKMATE - MAX_DEPTH as i32 {
        score + ply as i32
    } else if score < -(CHECKMATE - MAX_DEPTH as i32) {
        score - ply as i32
    } else {
        score
    }
}

/// Adjust mate scores from TT retrieval (make ply-relative).
fn tt_score_probe(score: i32, ply: usize) -> i32 {
    if score > CHECKMATE - MAX_DEPTH as i32 {
        score - ply as i32
    } else if score < -(CHECKMATE - MAX_DEPTH as i32) {
        score + ply as i32
    } else {
        score
    }
}

// ---------------------------------------------------------------------------
// PeSTO piece-square tables (tapered evaluation)
//
// Tables are in internal square order: index 0 = a1, index 63 = h8.
// White reads table[sq], black reads table[sq ^ 56] (vertical mirror).
// Material base values are added separately during evaluation.
// ---------------------------------------------------------------------------

// Midgame material base values (PeSTO)
const MG_PAWN_VAL: i32 = 82;
const MG_KNIGHT_VAL: i32 = 337;
const MG_BISHOP_VAL: i32 = 365;
const MG_ROOK_VAL: i32 = 477;
const MG_QUEEN_VAL: i32 = 1025;

// Endgame material base values (PeSTO)
const EG_PAWN_VAL: i32 = 94;
const EG_KNIGHT_VAL: i32 = 281;
const EG_BISHOP_VAL: i32 = 297;
const EG_ROOK_VAL: i32 = 512;
const EG_QUEEN_VAL: i32 = 936;

// Phase weights per piece type
const KNIGHT_PHASE: i32 = 1;
const BISHOP_PHASE: i32 = 1;
const ROOK_PHASE: i32 = 2;
const QUEEN_PHASE: i32 = 4;
const MAX_PHASE: i32 = 24; // 4*1 + 4*1 + 4*2 + 2*4

#[rustfmt::skip]
const MG_PAWN_TABLE: [i32; 64] = [
      0,   0,   0,   0,   0,   0,   0,   0,
    -35,  -1, -20, -23, -15,  24,  38, -22,
    -26,  -4,  -4, -10,   3,   3,  33, -12,
    -27,  -2,  -5,  12,  17,   6,  10, -25,
    -14,  13,   6,  21,  23,  12,  17, -23,
     -6,   7,  26,  31,  65,  56,  25, -20,
     98, 134,  61,  95,  68, 126,  34, -11,
      0,   0,   0,   0,   0,   0,   0,   0,
];

#[rustfmt::skip]
const MG_KNIGHT_TABLE: [i32; 64] = [
   -105, -21, -58, -33, -17, -28, -19, -23,
    -29, -53, -12,  -3,  -1,  18, -14, -19,
    -23,  -9,  12,  10,  19,  17,  25, -16,
    -13,   4,  16,  13,  28,  19,  21,  -8,
     -9,  17,  19,  53,  37,  69,  18,  22,
    -47,  60,  37,  65,  84, 129,  73,  44,
    -73, -41,  72,  36,  23,  62,   7, -17,
   -167, -89, -34, -49,  61, -97, -15,-107,
];

#[rustfmt::skip]
const MG_BISHOP_TABLE: [i32; 64] = [
    -33,  -3, -14, -21, -13, -12, -39, -21,
      4,  15,  16,   0,   7,  21,  33,   1,
      0,  15,  15,  15,  14,  27,   6,   7,
     -6,  13,  13,  26,  34,  12,  10,   4,
     -4,   5,  19,  50,  37,  37,   7,  -2,
    -16,  37,  43,  40,  35,  50,  37,  -2,
    -26,  16, -18, -13,  30,  59,  18, -47,
    -29,   4, -82, -37, -25, -42,   7,  -8,
];

#[rustfmt::skip]
const MG_ROOK_TABLE: [i32; 64] = [
    -19, -13,   1,  17,  16,   7, -37, -26,
    -44, -16, -20,  -9,  -1,  11,  -6, -71,
    -45, -25, -16, -17,   3,   0,  -5, -33,
    -36, -26, -12,  -1,   9,  -7,   6, -23,
    -24, -11,   7,  26,  24,  35,  -8, -20,
     -5,  19,  26,  36,  17,  45,  61,  16,
     27,  32,  58,  62,  80,  67,  26,  44,
     32,  42,  32,  51,  63,   9,  31,  43,
];

#[rustfmt::skip]
const MG_QUEEN_TABLE: [i32; 64] = [
     -1, -18,  -9,  10, -15, -25, -31, -50,
    -35,  -8,  11,   2,   8,  15,  -3,   1,
    -14,   2, -11,  -2,  -5,   2,  14,   5,
     -9, -26,  -9, -10,  -2,  -4,   3,  -3,
    -27, -27, -16, -16,  -1,  17,  -2,   1,
    -13, -17,   7,   8,  29,  56,  47,  57,
    -24, -39,  -5,   1, -16,  57,  28,  54,
    -28,   0,  29,  12,  59,  44,  43,  45,
];

#[rustfmt::skip]
const MG_KING_TABLE: [i32; 64] = [
    -15,  36,  12, -54,   8, -28,  24,  14,
      1,   7,  -8, -64, -43, -16,   9,   8,
    -14, -14, -22, -46, -44, -30, -15, -27,
    -49,  -1, -27, -39, -46, -44, -33, -51,
    -17, -20, -12, -27, -30, -25, -14, -36,
     -9,  24,   2, -16, -20,   6,  22, -22,
     29,  -1, -20,  -7,  -8,  -4, -38, -29,
    -65,  23,  16, -15, -56, -34,   2,  13,
];

#[rustfmt::skip]
const EG_PAWN_TABLE: [i32; 64] = [
      0,   0,   0,   0,   0,   0,   0,   0,
     13,   8,   8,  10,  13,   0,   2,  -7,
      4,   7,  -6,   1,   0,  -5,  -1,  -8,
     13,   9,  -3,  -7,  -7,  -8,   3,  -1,
     32,  24,  13,   5,  -2,   4,  17,  17,
     94, 100,  85,  67,  56,  53,  82,  84,
    178, 173, 158, 134, 147, 132, 165, 187,
      0,   0,   0,   0,   0,   0,   0,   0,
];

#[rustfmt::skip]
const EG_KNIGHT_TABLE: [i32; 64] = [
    -29, -51, -23, -15, -22, -18, -50, -64,
    -42, -20, -10,  -5,  -2, -20, -23, -44,
    -23,  -3,  -1,  15,  10,  -3, -20, -22,
    -18,  -6,  16,  25,  16,  17,   4, -18,
    -17,   3,  22,  22,  22,  11,   8, -18,
    -24, -20,  10,   9,  -1,  -9, -19, -41,
    -25,  -8, -25,  -2,  -9, -25, -24, -52,
    -58, -38, -13, -28, -31, -27, -63, -99,
];

#[rustfmt::skip]
const EG_BISHOP_TABLE: [i32; 64] = [
    -23,  -9, -23,  -5,  -9, -16,  -5, -17,
    -14, -18,  -7,  -1,   4,  -9, -15, -27,
    -12,  -3,   8,  10,  13,   3,  -7, -15,
     -6,   3,  13,  19,   7,  10,  -3,  -9,
     -3,   9,  12,   9,  14,  10,   3,   2,
      2,  -8,   0,  -1,  -2,   6,   0,   4,
     -8,  -4,   7, -12,  -3, -13,  -4, -14,
    -14, -21, -11,  -8,  -7,  -9, -17, -24,
];

#[rustfmt::skip]
const EG_ROOK_TABLE: [i32; 64] = [
     -9,   2,   3,  -1,  -5, -13,   4, -20,
     -6,  -6,   0,   2,  -9,  -9, -11,  -3,
     -4,   0,  -5,  -1,  -7, -12,  -8, -16,
      3,   5,   8,   4,  -5,  -6,  -8, -11,
      4,   3,  13,   1,   2,   1,  -1,   2,
      7,   7,   7,   5,   4,  -3,  -5,  -3,
     11,  13,  13,  11,  -3,   3,   8,   3,
     13,  10,  18,  15,  12,  12,   8,   5,
];

#[rustfmt::skip]
const EG_QUEEN_TABLE: [i32; 64] = [
    -33, -28, -22, -43,  -5, -32, -20, -41,
    -22, -23, -30, -16, -16, -23, -36, -32,
    -16, -27,  15,   6,   9,  17,  10,   5,
    -18,  28,  19,  47,  31,  34,  39,  23,
      3,  22,  24,  45,  57,  40,  57,  36,
    -20,   6,   9,  49,  47,  35,  19,   9,
    -17,  20,  32,  41,  58,  25,  30,   0,
     -9,  22,  22,  27,  27,  19,  10,  20,
];

#[rustfmt::skip]
const EG_KING_TABLE: [i32; 64] = [
    -53, -34, -21, -11, -28, -14, -24, -43,
    -27, -11,   4,  13,  14,   4,  -5, -17,
    -19,  -3,  11,  21,  23,  16,   7,  -9,
    -18,  -4,  21,  24,  27,  23,   9, -11,
     -8,  22,  24,  27,  26,  33,  26,   3,
     10,  17,  23,  15,  20,  45,  44,  13,
    -12,  17,  14,  17,  17,  38,  23,  11,
    -74, -35, -18, -18, -11,  15,   4, -17,
];

// ---------------------------------------------------------------------------
// Tal-style bonuses
// ---------------------------------------------------------------------------

const TAL_AGGRESSION: f32 = 1.5;

/// File mask: all 8 squares on a given file (0=a .. 7=h).
const fn file_mask(file: u8) -> u64 {
    0x0101_0101_0101_0101u64 << file
}

/// 3x3 zone around a king square (clamped to board edges).
fn king_zone(king_sq: u8) -> u64 {
    let kf = (king_sq % 8) as i8;
    let kr = (king_sq / 8) as i8;
    let mut zone = 0u64;
    for dr in -1..=1i8 {
        for df in -1..=1i8 {
            let f = kf + df;
            let r = kr + dr;
            if f >= 0 && f < 8 && r >= 0 && r < 8 {
                zone |= 1u64 << (r * 8 + f);
            }
        }
    }
    zone
}

/// Count how many set bits in bb are adjacent (within 1 file) to a king on king_sq.
fn count_near_king(bb: u64, king_sq: u8) -> i32 {
    (bb & king_zone(king_sq)).count_ones() as i32
}

/// Tal-style bonus from white's perspective (before side-to-move flip).
fn tal_bonuses(board: &Board) -> i32 {
    let mut bonus = 0i32;

    let wk_sq = board.white_kings.trailing_zeros() as u8;
    let bk_sq = board.black_kings.trailing_zeros() as u8;
    let bk_zone = king_zone(bk_sq);
    let wk_zone = king_zone(wk_sq);

    // --- King attack: white pieces near black king ---
    let mut w_attackers = 0i32;
    let mut w_attack_sum = 0i32;
    for &(bb, val) in &[
        (board.white_knights, 20), (board.white_bishops, 20),
        (board.white_rooks, 25), (board.white_queens, 40),
    ] {
        let near = (bb & bk_zone).count_ones() as i32;
        if near > 0 {
            w_attackers += near;
            w_attack_sum += near * val;
        }
    }
    if w_attackers > 0 {
        bonus += w_attack_sum * w_attackers;  // scale by attacker count
    }

    // --- King attack: black pieces near white king ---
    let mut b_attackers = 0i32;
    let mut b_attack_sum = 0i32;
    for &(bb, val) in &[
        (board.black_knights, 20), (board.black_bishops, 20),
        (board.black_rooks, 25), (board.black_queens, 40),
    ] {
        let near = (bb & wk_zone).count_ones() as i32;
        if near > 0 {
            b_attackers += near;
            b_attack_sum += near * val;
        }
    }
    if b_attackers > 0 {
        bonus -= b_attack_sum * b_attackers;
    }

    // --- Pawn storm: pawns on rank 5/6 near enemy king file ---
    let bk_file = bk_sq % 8;
    let mut wp = board.white_pawns;
    while wp != 0 {
        let sq = wp.trailing_zeros() as u8;
        wp &= wp - 1;
        let f = sq % 8;
        let r = sq / 8;
        if (f as i8 - bk_file as i8).unsigned_abs() <= 2 {
            if r == 4 { bonus += 15; }       // rank 5
            else if r == 5 { bonus += 15; }  // rank 6
        }
    }
    let wk_file = wk_sq % 8;
    let mut bp = board.black_pawns;
    while bp != 0 {
        let sq = bp.trailing_zeros() as u8;
        bp &= bp - 1;
        let f = sq % 8;
        let r = sq / 8;
        if (f as i8 - wk_file as i8).unsigned_abs() <= 2 {
            if r == 3 { bonus -= 15; }       // rank 4 (from black's perspective = rank 5)
            else if r == 2 { bonus -= 15; }  // rank 3 (from black's perspective = rank 6)
        }
    }

    // --- Castling bonus: +80cp if castling rights intact ---
    if board.castling_rights & (crate::board::CASTLING_WK | crate::board::CASTLING_WQ) != 0 {
        bonus += 80;
    }
    if board.castling_rights & (crate::board::CASTLING_BK | crate::board::CASTLING_BQ) != 0 {
        bonus -= 80;
    }

    // --- Early queen penalty: -60cp if queen not on starting square before move 10 ---
    if board.fullmove_number < 10 {
        // White queen starting square is d1 = index 3
        if board.white_queens != 0 && board.white_queens & (1u64 << 3) == 0 {
            bonus -= 60;
        }
        // Black queen starting square is d8 = index 59
        if board.black_queens != 0 && board.black_queens & (1u64 << 59) == 0 {
            bonus += 60;
        }
    }

    // --- Open file rook: +25cp per rook on file with no pawns ---
    let all_pawns = board.white_pawns | board.black_pawns;
    let mut wr = board.white_rooks;
    while wr != 0 {
        let sq = wr.trailing_zeros() as u8;
        wr &= wr - 1;
        let fmask = file_mask(sq % 8);
        if all_pawns & fmask == 0 {
            bonus += 25;
        }
    }
    let mut br = board.black_rooks;
    while br != 0 {
        let sq = br.trailing_zeros() as u8;
        br &= br - 1;
        let fmask = file_mask(sq % 8);
        if all_pawns & fmask == 0 {
            bonus -= 25;
        }
    }

    // --- Bishop pair: +50cp if both bishops present ---
    if board.white_bishops.count_ones() >= 2 {
        bonus += 50;
    }
    if board.black_bishops.count_ones() >= 2 {
        bonus -= 50;
    }

    // --- Passed pawn bonus (endgame: < 10 pieces): +30cp per passed pawn ---
    let piece_count = board.occupied().count_ones();
    if piece_count < 10 {
        // White passed pawns
        let mut wp2 = board.white_pawns;
        while wp2 != 0 {
            let sq = wp2.trailing_zeros() as u8;
            wp2 &= wp2 - 1;
            let f = sq % 8;
            let r = sq / 8;
            // Check no black pawns on same or adjacent files ahead
            let mut passed = true;
            let mut bp2 = board.black_pawns;
            while bp2 != 0 {
                let bsq = bp2.trailing_zeros() as u8;
                bp2 &= bp2 - 1;
                let bf = bsq % 8;
                let br2 = bsq / 8;
                if (bf as i8 - f as i8).unsigned_abs() <= 1 && br2 > r {
                    passed = false;
                    break;
                }
            }
            if passed { bonus += 30; }
        }
        // Black passed pawns
        let mut bp3 = board.black_pawns;
        while bp3 != 0 {
            let sq = bp3.trailing_zeros() as u8;
            bp3 &= bp3 - 1;
            let f = sq % 8;
            let r = sq / 8;
            let mut passed = true;
            let mut wp3 = board.white_pawns;
            while wp3 != 0 {
                let wsq = wp3.trailing_zeros() as u8;
                wp3 &= wp3 - 1;
                let wf = wsq % 8;
                let wr2 = wsq / 8;
                if (wf as i8 - f as i8).unsigned_abs() <= 1 && wr2 < r {
                    passed = false;
                    break;
                }
            }
            if passed { bonus -= 30; }
        }
    }

    bonus
}

// ---------------------------------------------------------------------------
// Tapered PeSTO evaluation
// ---------------------------------------------------------------------------

fn pop_lsb(bb: &mut u64) -> u8 {
    let sq = bb.trailing_zeros() as u8;
    *bb &= *bb - 1;
    sq
}

/// Evaluate using tapered PeSTO piece-square tables.
/// Positive = white advantage. Returns from side-to-move perspective.
pub fn evaluate(board: &Board) -> i32 {
    let mut mg = 0i32;
    let mut eg = 0i32;
    let mut phase = 0i32;

    // --- White pieces ---
    eval_pieces(&mut mg, &mut eg, &mut phase, board.white_pawns,
                MG_PAWN_VAL, EG_PAWN_VAL, &MG_PAWN_TABLE, &EG_PAWN_TABLE, 0, true);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.white_knights,
                MG_KNIGHT_VAL, EG_KNIGHT_VAL, &MG_KNIGHT_TABLE, &EG_KNIGHT_TABLE, KNIGHT_PHASE, true);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.white_bishops,
                MG_BISHOP_VAL, EG_BISHOP_VAL, &MG_BISHOP_TABLE, &EG_BISHOP_TABLE, BISHOP_PHASE, true);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.white_rooks,
                MG_ROOK_VAL, EG_ROOK_VAL, &MG_ROOK_TABLE, &EG_ROOK_TABLE, ROOK_PHASE, true);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.white_queens,
                MG_QUEEN_VAL, EG_QUEEN_VAL, &MG_QUEEN_TABLE, &EG_QUEEN_TABLE, QUEEN_PHASE, true);
    eval_king(&mut mg, &mut eg, board.white_kings, &MG_KING_TABLE, &EG_KING_TABLE, true);

    // --- Black pieces ---
    eval_pieces(&mut mg, &mut eg, &mut phase, board.black_pawns,
                MG_PAWN_VAL, EG_PAWN_VAL, &MG_PAWN_TABLE, &EG_PAWN_TABLE, 0, false);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.black_knights,
                MG_KNIGHT_VAL, EG_KNIGHT_VAL, &MG_KNIGHT_TABLE, &EG_KNIGHT_TABLE, KNIGHT_PHASE, false);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.black_bishops,
                MG_BISHOP_VAL, EG_BISHOP_VAL, &MG_BISHOP_TABLE, &EG_BISHOP_TABLE, BISHOP_PHASE, false);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.black_rooks,
                MG_ROOK_VAL, EG_ROOK_VAL, &MG_ROOK_TABLE, &EG_ROOK_TABLE, ROOK_PHASE, false);
    eval_pieces(&mut mg, &mut eg, &mut phase, board.black_queens,
                MG_QUEEN_VAL, EG_QUEEN_VAL, &MG_QUEEN_TABLE, &EG_QUEEN_TABLE, QUEEN_PHASE, false);
    eval_king(&mut mg, &mut eg, board.black_kings, &MG_KING_TABLE, &EG_KING_TABLE, false);

    // Taper between midgame and endgame
    let mg_phase = phase.min(MAX_PHASE);
    let eg_phase = MAX_PHASE - mg_phase;
    let pst_score = (mg * mg_phase + eg * eg_phase) / MAX_PHASE;

    // Add Tal-style bonuses (white-relative, then flip for STM)
    let tal = (tal_bonuses(board) as f32 * TAL_AGGRESSION) as i32;
    let score = pst_score + tal;

    if board.side_to_move { score } else { -score }
}

#[inline]
fn eval_pieces(
    mg: &mut i32, eg: &mut i32, phase: &mut i32,
    mut bb: u64, mg_mat: i32, eg_mat: i32,
    mg_table: &[i32; 64], eg_table: &[i32; 64],
    phase_weight: i32, is_white: bool,
) {
    while bb != 0 {
        let sq = pop_lsb(&mut bb) as usize;
        let idx = if is_white { sq } else { sq ^ 56 };
        let mg_val = mg_mat + mg_table[idx];
        let eg_val = eg_mat + eg_table[idx];
        if is_white {
            *mg += mg_val;
            *eg += eg_val;
        } else {
            *mg -= mg_val;
            *eg -= eg_val;
        }
        *phase += phase_weight;
    }
}

#[inline]
fn eval_king(
    mg: &mut i32, eg: &mut i32,
    mut bb: u64, mg_table: &[i32; 64], eg_table: &[i32; 64],
    is_white: bool,
) {
    while bb != 0 {
        let sq = pop_lsb(&mut bb) as usize;
        let idx = if is_white { sq } else { sq ^ 56 };
        if is_white {
            *mg += mg_table[idx];
            *eg += eg_table[idx];
        } else {
            *mg -= mg_table[idx];
            *eg -= eg_table[idx];
        }
    }
}

// ---------------------------------------------------------------------------
// Search constants and killer table
// ---------------------------------------------------------------------------

const MAX_DEPTH: usize = 64;

// Simple piece values for MVV-LVA ordering (not PeSTO — just for sorting)
const MVV_LVA_VAL: [i32; 6] = [100, 320, 330, 500, 900, 20_000];

type Killers = [[Option<(u8, u8)>; 2]; MAX_DEPTH];

// History heuristic: [side_to_move (0=black, 1=white)][from_sq][to_sq]
// Tracks which quiet moves cause beta cutoffs across the search tree.
type History = [[[i32; 64]; 64]; 2];

const HISTORY_MAX: i32 = 4_000; // cap to keep scores below killer priority

/// Update history score with gravity: bonus decays existing values toward zero,
/// preventing unbounded growth. Formula from Stockfish-style gravity.
fn update_history(history: &mut History, side: bool, from: u8, to: u8, bonus: i32) {
    let entry = &mut history[side as usize][from as usize][to as usize];
    // Gravity formula: entry += bonus - entry * |bonus| / MAX
    // This naturally caps values near HISTORY_MAX without hard clamping.
    *entry += bonus - *entry * bonus.abs() / HISTORY_MAX;
}

// ---------------------------------------------------------------------------
// Move ordering
// ---------------------------------------------------------------------------

/// Return the simple piece value of whatever is on `sq` for `is_white`.
fn piece_val_on(board: &Board, sq: u8, is_white: bool) -> i32 {
    let bit = 1u64 << sq;
    let (p, n, b, r, q) = if is_white {
        (board.white_pawns, board.white_knights, board.white_bishops,
         board.white_rooks, board.white_queens)
    } else {
        (board.black_pawns, board.black_knights, board.black_bishops,
         board.black_rooks, board.black_queens)
    };
    if p & bit != 0 { MVV_LVA_VAL[0] }
    else if n & bit != 0 { MVV_LVA_VAL[1] }
    else if b & bit != 0 { MVV_LVA_VAL[2] }
    else if r & bit != 0 { MVV_LVA_VAL[3] }
    else if q & bit != 0 { MVV_LVA_VAL[4] }
    else { MVV_LVA_VAL[5] }
}

/// Score a move for ordering. Higher = searched first.
fn score_move(board: &Board, mv: &Move, killers: &Killers, ply: usize, tt_move: Option<(u8, u8)>, history: &History) -> i32 {
    // TT best move: highest priority
    if let Some((from, to)) = tt_move {
        if mv.from_sq == from && mv.to_sq == to {
            return 100_000;
        }
    }
    if mv.flags & movegen::FLAG_CAPTURE != 0 {
        let victim = if mv.flags & movegen::FLAG_EN_PASSANT != 0 {
            MVV_LVA_VAL[0] // en passant always captures a pawn
        } else {
            piece_val_on(board, mv.to_sq, !board.side_to_move)
        };
        let attacker = piece_val_on(board, mv.from_sq, board.side_to_move);
        // Losing captures (attacker worth much more than victim): below killers
        if victim < attacker - 200 {
            return 3_000 + victim - attacker / 10;
        }
        return 10_000 + victim - attacker / 10;
    }
    // Killer moves: searched after captures, before quiet
    if ply < MAX_DEPTH {
        for slot in &killers[ply] {
            if let Some((from, to)) = slot {
                if *from == mv.from_sq && *to == mv.to_sq {
                    return 5_000;
                }
            }
        }
    }
    // History heuristic: differentiate quiet moves
    history[board.side_to_move as usize][mv.from_sq as usize][mv.to_sq as usize]
}

/// Sort moves in-place: TT move → captures (MVV-LVA) → killers → history → quiet.
fn order_moves(board: &Board, moves: &mut [Move], killers: &Killers, ply: usize, tt_move: Option<(u8, u8)>, history: &History) {
    moves.sort_unstable_by(|a, b| {
        score_move(board, b, killers, ply, tt_move, history)
            .cmp(&score_move(board, a, killers, ply, tt_move, history))
    });
}

/// Store a killer move (non-capture that caused beta cutoff).
fn store_killer(killers: &mut Killers, ply: usize, mv: &Move) {
    if ply >= MAX_DEPTH {
        return;
    }
    let entry = (mv.from_sq, mv.to_sq);
    // Don't store duplicates; shift slot 0 → slot 1
    if killers[ply][0] == Some(entry) {
        return;
    }
    killers[ply][1] = killers[ply][0];
    killers[ply][0] = Some(entry);
}

// ---------------------------------------------------------------------------
// Quiescence search
// ---------------------------------------------------------------------------

/// Search captures only until the position is quiet.
fn quiescence(board: &Board, mut alpha: i32, beta: i32, ply: usize, network: Option<&nnue::Network>, nodes: &Cell<u64>, node_limit: u64) -> i32 {
    nodes.set(nodes.get() + 1);

    let all_moves = generate_moves(board);

    // Detect checkmate / stalemate before stand-pat (must not be masked by beta cutoff)
    if all_moves.is_empty() {
        if is_in_check(board) {
            return -(CHECKMATE - ply as i32);
        }
        return 0;
    }

    let stand_pat = if let Some(net) = network {
        let acc = nnue::Accumulator::from_board(net, board);
        net.evaluate(&acc, board.side_to_move)
    } else {
        evaluate(board)
    };
    if stand_pat >= beta {
        return beta;
    }
    if stand_pat > alpha {
        alpha = stand_pat;
    }

    // Collect and order captures by MVV-LVA
    let mut captures: Vec<Move> = all_moves
        .into_iter()
        .filter(|m| m.flags & movegen::FLAG_CAPTURE != 0)
        .collect();
    captures.sort_unstable_by(|a, b| {
        let sa = {
            let victim = if a.flags & movegen::FLAG_EN_PASSANT != 0 {
                MVV_LVA_VAL[0]
            } else {
                piece_val_on(board, a.to_sq, !board.side_to_move)
            };
            victim - piece_val_on(board, a.from_sq, board.side_to_move) / 10
        };
        let sb = {
            let victim = if b.flags & movegen::FLAG_EN_PASSANT != 0 {
                MVV_LVA_VAL[0]
            } else {
                piece_val_on(board, b.to_sq, !board.side_to_move)
            };
            victim - piece_val_on(board, b.from_sq, board.side_to_move) / 10
        };
        sb.cmp(&sa)
    });

    for mv in &captures {
        if nodes.get() >= node_limit {
            break;
        }
        let new_board = make_move(board, mv);
        let score = -quiescence(&new_board, -beta, -alpha, ply + 1, network, nodes, node_limit);
        if score >= beta {
            return beta;
        }
        if score > alpha {
            alpha = score;
        }
    }

    alpha
}

// ---------------------------------------------------------------------------
// Alpha-beta search
// ---------------------------------------------------------------------------

/// Public entry point: alpha-beta with quiescence, move ordering, and killers.
pub fn alpha_beta(board: &Board, depth: u32, alpha: i32, beta: i32) -> i32 {
    let mut killers: Killers = [[None; 2]; MAX_DEPTH];
    let mut history: History = [[[0i32; 64]; 64]; 2];
    let nodes = Cell::new(0u64);
    let mut tt = TTable::new();
    ab_search(board, depth, alpha, beta, 0, &mut killers, &mut history, None, true, &nodes, u64::MAX, &mut tt)
}

/// Recursive alpha-beta with move ordering, killer heuristic, history, NMP, LMR, and TT.
fn ab_search(
    board: &Board, depth: u32, mut alpha: i32, beta: i32,
    ply: usize, killers: &mut Killers, history: &mut History,
    network: Option<&nnue::Network>,
    allow_null: bool, nodes: &Cell<u64>, node_limit: u64,
    tt: &mut TTable,
) -> i32 {
    nodes.set(nodes.get() + 1);

    if nodes.get() >= node_limit {
        return if let Some(net) = network {
            let acc = nnue::Accumulator::from_board(net, board);
            net.evaluate(&acc, board.side_to_move)
        } else {
            evaluate(board)
        };
    }

    if depth == 0 {
        return quiescence(board, alpha, beta, ply, network, nodes, node_limit);
    }

    // --- TT probe ---
    let hash = board.zobrist_hash();
    let mut tt_move: Option<(u8, u8)> = None;

    if let Some(entry) = tt.probe(hash) {
        // Always use the best move for ordering (even from older generations)
        tt_move = entry.best_move();
        // Only trust scores from the current generation (same iterative deepening depth)
        if entry.gen == tt.gen && entry.depth as u32 >= depth {
            let tt_score = tt_score_probe(entry.score, ply);
            match entry.flag {
                TT_EXACT => {
                    if tt_score >= beta { return beta; }
                    if tt_score <= alpha { return alpha; }
                    return tt_score;
                }
                TT_LOWER => { if tt_score >= beta { return beta; } }
                TT_UPPER => { if tt_score <= alpha { return alpha; } }
                _ => {}
            }
        }
    }

    let in_check = is_in_check(board);

    // --- Null Move Pruning ---
    if allow_null && !in_check && depth >= 3 && board.occupied().count_ones() >= 10 {
        let null_board = board.make_null_move();
        let r = 2;
        let score = -ab_search(&null_board, depth - 1 - r, -beta, -beta + 1, ply + 1, killers, history, network, false, nodes, node_limit, tt);
        if score >= beta {
            return beta;
        }
    }

    let mut moves = generate_moves(board);

    if moves.is_empty() {
        if in_check {
            return -(CHECKMATE - ply as i32);
        }
        return 0;
    }

    order_moves(board, &mut moves, killers, ply, tt_move, history);

    let original_alpha = alpha;
    let mut best_mv: Option<(u8, u8)> = None;

    let mut searched_all = true;
    // Track quiet moves searched before a cutoff (for history malus)
    let mut quiets_searched = [(0u8, 0u8); 128];
    let mut num_quiets = 0usize;

    for (move_index, mv) in moves.iter().enumerate() {
        if nodes.get() >= node_limit {
            searched_all = false;
            break;
        }

        let new_board = make_move(board, mv);
        let is_capture = mv.flags & movegen::FLAG_CAPTURE != 0;
        let is_killer = ply < MAX_DEPTH && killers[ply].iter().any(|k| {
            k.map_or(false, |(f, t)| f == mv.from_sq && t == mv.to_sq)
        });
        let hist_score = if !is_capture {
            history[board.side_to_move as usize][mv.from_sq as usize][mv.to_sq as usize]
        } else {
            0
        };

        let score;

        // --- Late Move Reductions ---
        if depth >= 3 && move_index > 3 && !is_capture && !is_killer && !in_check {
            let reduced = -ab_search(&new_board, depth - 2, -beta, -alpha, ply + 1, killers, history, network, true, nodes, node_limit, tt);
            if reduced > alpha {
                score = -ab_search(&new_board, depth - 1, -beta, -alpha, ply + 1, killers, history, network, true, nodes, node_limit, tt);
            } else {
                score = reduced;
            }
        } else {
            score = -ab_search(&new_board, depth - 1, -beta, -alpha, ply + 1, killers, history, network, true, nodes, node_limit, tt);
        }

        if score >= beta {
            if !is_capture {
                store_killer(killers, ply, mv);
                // History bonus for the move that caused cutoff
                let bonus = (depth * depth) as i32;
                update_history(history, board.side_to_move, mv.from_sq, mv.to_sq, bonus);
                // History malus: penalize quiet moves that were searched but didn't cut off
                for i in 0..num_quiets {
                    let (f, t) = quiets_searched[i];
                    update_history(history, board.side_to_move, f, t, -bonus);
                }
            }
            // Beta cutoff is always reliable — one move proves it
            tt.store(hash, depth as u8, tt_score_store(beta, ply), TT_LOWER, Some((mv.from_sq, mv.to_sq)));
            return beta;
        }
        if score > alpha {
            alpha = score;
            best_mv = Some((mv.from_sq, mv.to_sq));
        }
        // Track quiet moves that didn't cause cutoff
        if !is_capture && num_quiets < 128 {
            quiets_searched[num_quiets] = (mv.from_sq, mv.to_sq);
            num_quiets += 1;
        }
    }

    // If truncated before any move improved alpha, we have no real search result.
    // Return static eval instead of the original alpha (which could be -INF).
    if !searched_all && alpha == original_alpha {
        return if let Some(net) = network {
            let acc = nnue::Accumulator::from_board(net, board);
            net.evaluate(&acc, board.side_to_move)
        } else {
            evaluate(board)
        };
    }

    // Only store TT entries from complete searches.
    // Truncated searches (node limit) haven't evaluated all moves,
    // so UPPER bound ("no move beats alpha") is unreliable.
    // If alpha improved in a truncated search, store as LOWER bound
    // (we know score >= alpha, but there may be better moves unsearched).
    if searched_all {
        let flag = if alpha > original_alpha { TT_EXACT } else { TT_UPPER };
        tt.store(hash, depth as u8, tt_score_store(alpha, ply), flag, best_mv.or(tt_move));
    } else if alpha > original_alpha {
        tt.store(hash, depth as u8, tt_score_store(alpha, ply), TT_LOWER, best_mv);
    }

    alpha
}

/// Search for the best move at the given depth.
/// Returns None if no legal moves exist (checkmate or stalemate).
pub fn best_move(board: &Board, depth: u32, network: Option<&nnue::Network>) -> Option<(Move, i32)> {
    let mut moves = generate_moves(board);
    if moves.is_empty() {
        return None;
    }

    let mut killers: Killers = [[None; 2]; MAX_DEPTH];
    let mut history: History = [[[0i32; 64]; 64]; 2];
    let nodes = Cell::new(0u64);
    let mut tt = TTable::new();

    // Probe TT for root move ordering
    let root_hash = board.zobrist_hash();
    let tt_move = tt.probe(root_hash).and_then(|e| e.best_move());
    order_moves(board, &mut moves, &killers, 0, tt_move, &history);

    let mut best: Option<(Move, i32)> = None;
    let mut alpha = -INF;
    let beta = INF;

    for mv in moves {
        let new_board = make_move(board, &mv);
        let score = -ab_search(&new_board, depth - 1, -beta, -alpha, 1, &mut killers, &mut history, network, true, &nodes, u64::MAX, &mut tt);
        if score > alpha {
            alpha = score;
            best = Some((mv, score));
        }
    }

    best
}

/// Iterative deepening search with a node limit.
/// Increases depth until the node budget is exhausted.
/// Returns the best move + score from the last completed depth.
/// TT persists across depths for move ordering benefit.
pub fn best_move_nodes(board: &Board, node_limit: u64, network: Option<&nnue::Network>) -> Option<(Move, i32, u32)> {
    let moves = generate_moves(board);
    if moves.is_empty() {
        return None;
    }

    let mut tt = TTable::new();
    let mut history: History = [[[0i32; 64]; 64]; 2];
    let root_hash = board.zobrist_hash();
    let mut best_overall: Option<(Move, i32, u32)> = None;

    for depth in 1..=MAX_DEPTH as u32 {
        tt.next_gen(); // new generation — old scores used only for move ordering
        let mut killers: Killers = [[None; 2]; MAX_DEPTH];
        let nodes = Cell::new(0u64);
        let mut ordered_moves = moves.clone();

        // Use TT best move from previous depth for ordering (any generation)
        let tt_move = tt.probe(root_hash).and_then(|e| e.best_move());
        order_moves(board, &mut ordered_moves, &killers, 0, tt_move, &history);

        let mut best: Option<(Move, i32)> = None;
        let mut alpha = -INF;
        let beta = INF;
        let mut completed = true;

        for mv in &ordered_moves {
            let new_board = make_move(board, mv);
            let score = -ab_search(&new_board, depth - 1, -beta, -alpha, 1, &mut killers, &mut history, network, true, &nodes, node_limit, &mut tt);
            if nodes.get() >= node_limit && best.is_none() {
                completed = false;
                break;
            }
            if score > alpha {
                alpha = score;
                best = Some((mv.clone(), score));
            }
            if nodes.get() >= node_limit {
                break;
            }
        }

        if let Some((mv, score)) = best {
            best_overall = Some((mv, score, depth));
        }

        if !completed || nodes.get() >= node_limit {
            break;
        }
    }

    best_overall
}

// ---------------------------------------------------------------------------
// UCI move parsing
// ---------------------------------------------------------------------------

/// Parse a UCI move string (e.g. "e2e4", "e7e8q") and find the matching legal move.
pub fn parse_uci_move(board: &Board, uci: &str) -> Option<Move> {
    let bytes = uci.as_bytes();
    if bytes.len() < 4 {
        return None;
    }
    let from_file = bytes[0].wrapping_sub(b'a');
    let from_rank = bytes[1].wrapping_sub(b'1');
    let to_file = bytes[2].wrapping_sub(b'a');
    let to_rank = bytes[3].wrapping_sub(b'1');
    if from_file > 7 || from_rank > 7 || to_file > 7 || to_rank > 7 {
        return None;
    }
    let from_sq = from_rank * 8 + from_file;
    let to_sq = to_rank * 8 + to_file;

    let promo = if bytes.len() > 4 {
        match bytes[4] {
            b'n' => Some(movegen::KNIGHT),
            b'b' => Some(movegen::BISHOP),
            b'r' => Some(movegen::ROOK),
            b'q' => Some(movegen::QUEEN),
            _ => None,
        }
    } else {
        None
    };

    let moves = generate_moves(board);
    moves.into_iter().find(|m| {
        m.from_sq == from_sq && m.to_sq == to_sq && m.promotion == promo
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startpos_eval_is_zero() {
        let board = Board::startpos();
        assert_eq!(evaluate(&board), 0, "Starting position should be 0 (equal material)");
    }

    #[test]
    fn white_up_a_queen() {
        // White has an extra queen (black queen removed)
        let board = Board::from_fen("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1").unwrap();
        let eval = evaluate(&board);
        assert!(eval > 900, "White up a queen should eval > 900, got {}", eval);
    }

    #[test]
    fn best_move_finds_capture() {
        // White queen can capture undefended black queen
        let board = Board::from_fen("4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1").unwrap();
        let result = best_move(&board, 2, None);
        assert!(result.is_some());
        let (mv, score) = result.unwrap();
        assert_eq!(mv.to_uci(), "d1d5", "Should capture the queen");
        assert!(score > 800, "Score should reflect queen capture, got {}", score);
    }

    #[test]
    fn finds_checkmate_in_one() {
        // White to move, Qh5# is mate (back rank)
        let board = Board::from_fen("6k1/5ppp/8/8/8/8/8/4K2Q w - - 0 1").unwrap();
        let result = best_move(&board, 2, None);
        assert!(result.is_some());
        let (_, score) = result.unwrap();
        assert!(score > 40_000, "Should find checkmate, score={}", score);
    }

    #[test]
    fn finds_qh4_mate_in_one() {
        // Black to move after 1.f3 e5 2.g4 — Qh4# is checkmate
        let board = Board::from_fen("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2").unwrap();
        let result = best_move(&board, 1, None);
        assert!(result.is_some());
        let (mv, score) = result.unwrap();
        assert_eq!(mv.to_uci(), "d8h4", "Should find Qh4# checkmate");
        assert!(score > 40_000, "Should return mate score, got {}", score);
    }

    #[test]
    fn no_moves_in_checkmate() {
        let board = Board::from_fen("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4").unwrap();
        assert!(best_move(&board, 1, None).is_none());
    }

    #[test]
    fn parse_uci_move_basic() {
        let board = Board::startpos();
        let mv = parse_uci_move(&board, "e2e4");
        assert!(mv.is_some());
        let mv = mv.unwrap();
        assert_eq!(mv.from_sq, 12); // e2
        assert_eq!(mv.to_sq, 28);   // e4
    }

    #[test]
    fn parse_uci_move_promotion() {
        let board = Board::from_fen("8/4P3/8/8/8/8/8/4K2k w - - 0 1").unwrap();
        let mv = parse_uci_move(&board, "e7e8q");
        assert!(mv.is_some());
        assert_eq!(mv.unwrap().promotion, Some(movegen::QUEEN));
    }

    #[test]
    fn depth_0_returns_quiescence() {
        let board = Board::startpos();
        // No captures available at startpos, so quiescence = evaluate = 0
        let score = alpha_beta(&board, 0, -INF, INF);
        assert_eq!(score, 0);
    }

    #[test]
    fn search_doesnt_blunder_queen() {
        // White queen under attack by black pawn — shouldn't leave it there
        let board = Board::from_fen("4k3/8/8/8/3p4/4Q3/8/4K3 w - - 0 1").unwrap();
        let result = best_move(&board, 3, None);
        assert!(result.is_some());
        let (mv, _) = result.unwrap();
        // Queen should not stay on e3 where it gets captured
        assert!(
            mv.from_sq == 20, // e3
            "Queen should move, got {}",
            mv.to_uci()
        );
    }
}
