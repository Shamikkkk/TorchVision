use crate::board::Board;
use crate::movegen::{self, Move, generate_moves, is_in_check, make_move};
use crate::nnue;

use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, AtomicU8, Ordering};

// =========================================================================
// Tunable parameters — settable via UCI "setoption name X value Y"
// =========================================================================
static TUNE_TAL_AGGRESSION:      AtomicI32 = AtomicI32::new(25);  // ×10 scale (25 = 2.5)
static TUNE_FUTILITY_MARGIN_D1:  AtomicI32 = AtomicI32::new(100);
static TUNE_FUTILITY_MARGIN_D2:  AtomicI32 = AtomicI32::new(300);
static TUNE_ASPIRATION_DELTA:    AtomicI32 = AtomicI32::new(50);
static TUNE_NMP_REDUCTION:       AtomicI32 = AtomicI32::new(2);
static TUNE_LMR_MOVE_INDEX:      AtomicI32 = AtomicI32::new(3);
static TUNE_SE_BETA_MARGIN:      AtomicI32 = AtomicI32::new(50);
static TUNE_QUEEN_ATTACK_WT:     AtomicI32 = AtomicI32::new(40);
static TUNE_CASTLING_BONUS:      AtomicI32 = AtomicI32::new(80);
static TUNE_EARLY_QUEEN_PENALTY: AtomicI32 = AtomicI32::new(60);
static TUNE_DYNAMIC_BONUS:       AtomicI32 = AtomicI32::new(0);   // 0 = off (exact no-op)
static TUNE_COMP_BONUS:          AtomicI32 = AtomicI32::new(0);   // 0 = off (exact no-op)

static IID_ENABLE: AtomicBool = AtomicBool::new(false);

pub fn set_iid_enable(v: bool) {
    IID_ENABLE.store(v, Ordering::Relaxed);
}

/// Set a tunable search/eval parameter by name (called from UCI setoption handler).
pub fn set_tune_param(name: &str, value: i32) {
    match name {
        "tal_aggression"      => TUNE_TAL_AGGRESSION.store(value, Ordering::Relaxed),
        "futility_margin_d1"  => TUNE_FUTILITY_MARGIN_D1.store(value, Ordering::Relaxed),
        "futility_margin_d2"  => TUNE_FUTILITY_MARGIN_D2.store(value, Ordering::Relaxed),
        "aspiration_delta"    => TUNE_ASPIRATION_DELTA.store(value, Ordering::Relaxed),
        "nmp_reduction"       => TUNE_NMP_REDUCTION.store(value, Ordering::Relaxed),
        "lmr_move_index"      => TUNE_LMR_MOVE_INDEX.store(value, Ordering::Relaxed),
        "se_beta_margin"      => TUNE_SE_BETA_MARGIN.store(value, Ordering::Relaxed),
        "queen_attack_wt"     => TUNE_QUEEN_ATTACK_WT.store(value, Ordering::Relaxed),
        "castling_bonus"      => TUNE_CASTLING_BONUS.store(value, Ordering::Relaxed),
        "early_queen_penalty" => TUNE_EARLY_QUEEN_PENALTY.store(value, Ordering::Relaxed),
        "dynamic_bonus"       => TUNE_DYNAMIC_BONUS.store(value, Ordering::Relaxed),
        "comp_bonus"          => TUNE_COMP_BONUS.store(value, Ordering::Relaxed),
        _ => {}
    }
}

const INF: i32 = 100_000;
const CHECKMATE: i32 = 50_000;

/// Completed root-search result plus observational search-call accounting.
///
/// `nodes` counts entries into `ab_search` and `quiescence` across the main
/// thread and all Lazy-SMP helpers.  It includes TT cutoffs and work from an
/// incomplete final root iteration, and excludes the root position itself.
/// The counter's existing increment points and node-budget semantics are left
/// unchanged; this type only makes the already-recorded work observable.
#[derive(Debug)]
pub struct SearchOutcome {
    pub best_move: Move,
    pub score: i32,
    pub depth: u32,
    pub nodes: u64,
}

// ---------------------------------------------------------------------------
// Transposition table
// ---------------------------------------------------------------------------

const TT_SIZE: usize = 1 << 20; // ~1M entries (16 MB)

const TT_EXACT: u8 = 0;
const TT_LOWER: u8 = 1; // score is a lower bound (failed high)
const TT_UPPER: u8 = 2; // score is an upper bound (failed low)

/// Atomic storage slot for one TT entry (two independent AtomicU64s).
///
/// The pair is NOT updated atomically as a unit. We detect torn reads via an
/// XOR checksum: hash_xor_data stores (real_hash XOR data). On probe:
///   reconstructed = hash_xor_data XOR data
/// If reconstructed == query_hash the entry is intact; otherwise we treat it
/// as "not present" (covers both hash collisions and torn entries).
/// This is the standard Lazy SMP TT pattern (Stockfish, Ethereal, Weiss, …).
#[derive(Default)]
pub struct TTSlot {
    hash_xor_data: AtomicU64,
    data: AtomicU64,
}

/// Plain TT entry used inside the search. Packed into TTSlot for storage.
///
/// Pack layout (64 bits total):
///   bits  0-31: score    (i32 bit-pattern as u32; full range, no clamping)
///   bits 32-39: depth    (u8)
///   bits 40-41: flag     (2 bits: TT_EXACT/LOWER/UPPER)
///   bits 42-49: gen      (u8, wrapping)
///   bits 50-56: best_from (7 bits; 64 = no move)
///   bits 57-63: best_to   (7 bits; 64 = no move)
#[derive(Clone, Copy, Debug)]
struct TTEntry {
    hash: u64,
    score: i32,
    depth: u8,
    flag: u8,
    gen: u8,
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

    fn pack_data(&self) -> u64 {
        let score_bits = (self.score as u32) as u64;
        let depth     = self.depth as u64;
        let flag      = (self.flag & 0x03) as u64;
        let gen       = self.gen as u64;
        let best_from = (self.best_from & 0x7F) as u64;
        let best_to   = (self.best_to   & 0x7F) as u64;
        score_bits
            | (depth     << 32)
            | (flag      << 40)
            | (gen       << 42)
            | (best_from << 50)
            | (best_to   << 57)
    }

    fn unpack_data(hash: u64, data: u64) -> TTEntry {
        let score     = (data & 0xFFFF_FFFF) as u32 as i32;
        let depth     = ((data >> 32) & 0xFF) as u8;
        let flag      = ((data >> 40) & 0x03) as u8;
        let gen       = ((data >> 42) & 0xFF) as u8;
        let best_from = ((data >> 50) & 0x7F) as u8;
        let best_to   = ((data >> 57) & 0x7F) as u8;
        TTEntry { hash, score, depth, flag, gen, best_from, best_to }
    }
}

pub struct TTable {
    slots: Vec<TTSlot>,
    gen: AtomicU8,
}

impl TTable {
    pub fn new() -> Self {
        let mut slots = Vec::with_capacity(TT_SIZE);
        for _ in 0..TT_SIZE {
            slots.push(TTSlot::default());
        }
        TTable { slots, gen: AtomicU8::new(0) }
    }

    pub fn gen(&self) -> u8 {
        self.gen.load(Ordering::Relaxed)
    }

    /// Advance to the next iterative-deepening generation.
    /// Takes &self so it can be called on a shared reference.
    pub fn next_gen(&self) {
        self.gen.fetch_add(1, Ordering::Relaxed);
    }

    /// Probe the TT. Returns an owned TTEntry if the hash matches and the
    /// entry is not torn; None on hash miss, torn read, or empty slot.
    pub fn probe(&self, hash: u64) -> Option<TTEntry> {
        let slot = &self.slots[hash as usize & (TT_SIZE - 1)];
        let stored_xor = slot.hash_xor_data.load(Ordering::Relaxed);
        let data       = slot.data.load(Ordering::Relaxed);
        if data == 0 {
            return None; // empty slot
        }
        if (stored_xor ^ data) != hash {
            return None; // hash miss or torn entry
        }
        Some(TTEntry::unpack_data(hash, data))
    }

    /// Store an entry. Takes &self — atomic writes, no &mut needed.
    /// Safe to call concurrently (benign races: at worst two threads both
    /// write; one wins and the other's write is simply overwritten).
    pub fn store(&self, hash: u64, depth: u8, score: i32, flag: u8, best: Option<(u8, u8)>) {
        let idx  = hash as usize & (TT_SIZE - 1);
        let slot = &self.slots[idx];
        let current_gen = self.gen.load(Ordering::Relaxed);

        let existing_data = slot.data.load(Ordering::Relaxed);
        let replace = if existing_data == 0 {
            true // empty slot — always replace
        } else {
            let existing_gen   = ((existing_data >> 42) & 0xFF) as u8;
            let existing_depth = ((existing_data >> 32) & 0xFF) as u8;
            existing_gen != current_gen || existing_depth <= depth
        };

        if replace {
            let (bf, bt) = best.unwrap_or((64, 64));
            let entry = TTEntry {
                hash, score, depth, flag, gen: current_gen,
                best_from: bf, best_to: bt,
            };
            let new_data = entry.pack_data();
            let new_xor  = hash ^ new_data;
            // Write data first; then xor. A reader catching us mid-write sees
            // mismatched xor → correctly treated as a torn entry.
            slot.data.store(new_data, Ordering::Relaxed);
            slot.hash_xor_data.store(new_xor, Ordering::Relaxed);
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
    let queen_wt = TUNE_QUEEN_ATTACK_WT.load(Ordering::Relaxed);
    let mut w_attackers = 0i32;
    let mut w_attack_sum = 0i32;
    for &(bb, val) in &[
        (board.white_knights, 20), (board.white_bishops, 20),
        (board.white_rooks, 25), (board.white_queens, queen_wt),
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
        (board.black_rooks, 25), (board.black_queens, queen_wt),
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

    // --- King exposure bonus (G8 v2, capped additive) ---
    // Requires BOTH weak pawn shield AND 2+ attackers near king.
    // Capped at 50cp inside tal_bonuses → max 125cp after TAL_AGGRESSION=2.5.
    {
        // Black king exposure (white attacking)
        let bk_file_i = (bk_sq % 8) as i32;
        let mut bk_shield = 0i32;
        for f in (bk_file_i - 1).max(0)..=(bk_file_i + 1).min(7) {
            for &r in &[5u8, 6u8] {
                if board.black_pawns & (1u64 << (r * 8 + f as u8)) != 0 {
                    bk_shield += 1;
                }
            }
        }
        if bk_shield <= 1 && w_attackers >= 2 {
            let raw = w_attack_sum.min(100) / 2;
            bonus += raw.min(50);
        }

        // White king exposure (black attacking)
        let wk_file_i = (wk_sq % 8) as i32;
        let mut wk_shield = 0i32;
        for f in (wk_file_i - 1).max(0)..=(wk_file_i + 1).min(7) {
            for &r in &[1u8, 2u8] {
                if board.white_pawns & (1u64 << (r * 8 + f as u8)) != 0 {
                    wk_shield += 1;
                }
            }
        }
        if wk_shield <= 1 && b_attackers >= 2 {
            let raw = b_attack_sum.min(100) / 2;
            bonus -= raw.min(50);
        }
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

    // --- Castling bonus: +cp if castling rights intact ---
    let castling_bonus = TUNE_CASTLING_BONUS.load(Ordering::Relaxed);
    if board.castling_rights & (crate::board::CASTLING_WK | crate::board::CASTLING_WQ) != 0 {
        bonus += castling_bonus;
    }
    if board.castling_rights & (crate::board::CASTLING_BK | crate::board::CASTLING_BQ) != 0 {
        bonus -= castling_bonus;
    }

    // --- Early queen penalty: if queen not on starting square before move 10 ---
    if board.fullmove_number < 10 {
        let eq_penalty = TUNE_EARLY_QUEEN_PENALTY.load(Ordering::Relaxed);
        // White queen starting square is d1 = index 3
        if board.white_queens != 0 && board.white_queens & (1u64 << 3) == 0 {
            bonus -= eq_penalty;
        }
        // Black queen starting square is d8 = index 59
        if board.black_queens != 0 && board.black_queens & (1u64 << 59) == 0 {
            bonus += eq_penalty;
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
// Dynamic-initiative tiebreak (DYNAMIC_BONUS, default 0 = skipped entirely)
// ---------------------------------------------------------------------------

/// One side's built-up initiative against the enemy king, hard-capped at `cap`.
/// Rewards the ATTACKER's pressure — pieces bearing on the enemy king zone and
/// heavy pieces on own-half-open files toward the king. Distinct from the G8v2
/// exposure term above, which is gated on the DEFENDER's weak shield and counts
/// pieces physically inside the zone.
fn side_initiative(
    board: &Board, cap: i32, enemy_king_sq: u8,
    own_minors_majors: u64, own_pawns: u64, own_heavy: u64, occupied: u64,
) -> i32 {
    // a) Own non-pawn pieces attacking any square of the enemy king zone.
    let mut zone = king_zone(enemy_king_sq);
    let mut attackers = 0u64;
    while zone != 0 {
        let sq = pop_lsb(&mut zone);
        attackers |= movegen::attackers_to(board, sq, occupied) & own_minors_majors;
    }
    let att_count = (attackers.count_ones() as i32).min(3);

    // b) King file ±1: own-half-open (no own pawn) with an own rook/queen on it.
    let kf = (enemy_king_sq % 8) as i32;
    let mut open_files = 0i32;
    for f in (kf - 1).max(0)..=(kf + 1).min(7) {
        let fmask = file_mask(f as u8);
        if own_pawns & fmask == 0 && own_heavy & fmask != 0 {
            open_files += 1;
        }
    }
    let file_count = open_files.min(2);

    (att_count * (cap / 4) + file_count * (cap / 4)).min(cap)
}

/// White-relative dynamic-initiative term: white's capped initiative minus
/// black's, so the eval stays perspective-correct (same convention as
/// tal_bonuses). Each side can never exceed `cap` centipawns.
fn dynamic_initiative(board: &Board, cap: i32) -> i32 {
    let occupied = board.occupied();
    let wk_sq = board.white_kings.trailing_zeros() as u8;
    let bk_sq = board.black_kings.trailing_zeros() as u8;

    let w_pieces = board.white_knights | board.white_bishops
                 | board.white_rooks   | board.white_queens;
    let b_pieces = board.black_knights | board.black_bishops
                 | board.black_rooks   | board.black_queens;

    let w = side_initiative(board, cap, bk_sq, w_pieces, board.white_pawns,
                            board.white_rooks | board.white_queens, occupied);
    let b = side_initiative(board, cap, wk_sq, b_pieces, board.black_pawns,
                            board.black_rooks | board.black_queens, occupied);
    w - b
}

// ---------------------------------------------------------------------------
// Compensation-gated attack term (COMP_BONUS, default 0 = skipped entirely)
// ---------------------------------------------------------------------------

/// White-relative compensation term: a material-down side that kept its queen
/// and has a live attack on the enemy king retains partial eval credit for the
/// deficit. Pays ONLY when down 100..350cp, so the value survives a sacrifice
/// instead of vanishing with the sacrificed piece (the DYNAMIC_BONUS failure
/// mode: it rewarded attackers STANDING on the board). Hard-capped at `cap`;
/// a piece-down attack still evaluates as worse than material equality.
fn compensation_term(board: &Board, cap: i32) -> i32 {
    // g1 (cheapest): compensation is queen-led — no queens, nothing to do.
    if board.white_queens == 0 && board.black_queens == 0 {
        return 0;
    }

    // g2: simple material count matching SEE values, computed once and shared.
    // Only one side can be down; 100..350cp is the compensation window
    // (below = gambit noise, above = usually just lost).
    let mat = |p: u64, n: u64, b: u64, r: u64, q: u64| -> i32 {
        p.count_ones() as i32 * 100
            + n.count_ones() as i32 * 320
            + b.count_ones() as i32 * 330
            + r.count_ones() as i32 * 500
            + q.count_ones() as i32 * 900
    };
    let w_mat = mat(board.white_pawns, board.white_knights, board.white_bishops,
                    board.white_rooks, board.white_queens);
    let b_mat = mat(board.black_pawns, board.black_knights, board.black_bishops,
                    board.black_rooks, board.black_queens);
    let deficit = (w_mat - b_mat).abs();
    if deficit < 100 || deficit > 350 {
        return 0;
    }

    let white_down = w_mat < b_mat;
    let (own_queens, own_minors_majors, enemy_king_sq) = if white_down {
        (board.white_queens,
         board.white_knights | board.white_bishops | board.white_rooks | board.white_queens,
         board.black_kings.trailing_zeros() as u8)
    } else {
        (board.black_queens,
         board.black_knights | board.black_bishops | board.black_rooks | board.black_queens,
         board.white_kings.trailing_zeros() as u8)
    };
    // g1 per-side: the DOWN side must still have its queen.
    if own_queens == 0 {
        return 0;
    }

    // g3 (most expensive): ≥2 own non-pawn pieces attacking the enemy king
    // zone (same zone-attacker machinery as side_initiative).
    let occupied = board.occupied();
    let mut zone = king_zone(enemy_king_sq);
    let mut attackers = 0u64;
    while zone != 0 {
        let sq = pop_lsb(&mut zone);
        attackers |= movegen::attackers_to(board, sq, occupied) & own_minors_majors;
    }
    let att_count = attackers.count_ones() as i32;
    if att_count < 2 {
        return 0;
    }

    // Graduated, hard-capped: at cap=100, 2 attackers → 50, 3 → 75, 4+ → 100.
    let comp = (att_count.min(4) * (cap / 4)).min(cap);
    if white_down { comp } else { -comp }
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
    let tal_agg = TUNE_TAL_AGGRESSION.load(Ordering::Relaxed) as f32 / 10.0;
    let tal = (tal_bonuses(board) as f32 * tal_agg) as i32;
    let mut score = pst_score + tal;

    // DYNAMIC_BONUS tiebreak: added outside the TAL_AGGRESSION multiplier so
    // the per-side hard cap is exact centipawns. 0 (default) skips everything.
    let dyn_cap = TUNE_DYNAMIC_BONUS.load(Ordering::Relaxed);
    if dyn_cap > 0 {
        score += dynamic_initiative(board, dyn_cap);
    }

    // COMP_BONUS compensation-gated attack term: same white-relative
    // convention, exact centipawn cap. 0 (default) skips everything.
    let comp_cap = TUNE_COMP_BONUS.load(Ordering::Relaxed);
    if comp_cap > 0 {
        score += compensation_term(board, comp_cap);
    }

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
const ACCUMULATOR_STACK_CAPACITY: usize = MAX_DEPTH + 16;

/// Search-local evaluation state. The generic search body is monomorphised
/// for PeSTO and NNUE so the PeSTO path carries no accumulator storage.
trait SearchEvaluation: Send + Sized {
    fn evaluate(&self, board: &Board) -> i32;
    fn push_child(&mut self, parent: &Board, child: &Board);
    fn pop_child(&mut self);
    fn fork_root(&self) -> Self;
    fn stack_depth(&self) -> usize;
}

#[derive(Clone, Copy)]
struct PestoSearchState;

impl SearchEvaluation for PestoSearchState {
    #[inline]
    fn evaluate(&self, board: &Board) -> i32 {
        evaluate(board)
    }

    #[inline]
    fn push_child(&mut self, _parent: &Board, _child: &Board) {}

    #[inline]
    fn pop_child(&mut self) {}

    #[inline]
    fn fork_root(&self) -> Self {
        *self
    }

    #[inline]
    fn stack_depth(&self) -> usize {
        0
    }
}

struct NnueSearchState<'n> {
    network: &'n nnue::Network,
    accumulators: Vec<nnue::Accumulator>,
}

impl<'n> NnueSearchState<'n> {
    fn from_root(network: &'n nnue::Network, board: &Board) -> Self {
        let mut accumulators = Vec::with_capacity(ACCUMULATOR_STACK_CAPACITY);
        accumulators.push(nnue::Accumulator::from_board(network, board));
        Self { network, accumulators }
    }
}

impl SearchEvaluation for NnueSearchState<'_> {
    #[inline]
    fn evaluate(&self, board: &Board) -> i32 {
        self.network.evaluate(
            self.accumulators
                .last()
                .expect("NNUE accumulator stack must contain the current position"),
            board.side_to_move,
        )
    }

    #[inline]
    fn push_child(&mut self, parent: &Board, child: &Board) {
        let child_accumulator = self
            .accumulators
            .last()
            .expect("NNUE accumulator stack must contain the parent position")
            .updated_for_child(self.network, parent, child);
        self.accumulators.push(child_accumulator);
    }

    #[inline]
    fn pop_child(&mut self) {
        assert!(
            self.accumulators.len() > 1,
            "cannot pop the NNUE root accumulator"
        );
        self.accumulators.pop();
    }

    fn fork_root(&self) -> Self {
        debug_assert_eq!(self.accumulators.len(), 1);
        let mut accumulators = Vec::with_capacity(ACCUMULATOR_STACK_CAPACITY);
        accumulators.push(self.accumulators[0].clone());
        Self {
            network: self.network,
            accumulators,
        }
    }

    #[inline]
    fn stack_depth(&self) -> usize {
        self.accumulators.len()
    }
}

/// Push one authoritative real-child state for the duration of all searches
/// of that child, then restore the parent state before returning its result.
#[inline]
fn with_real_child<E, R>(
    eval_state: &mut E,
    parent: &Board,
    child: &Board,
    search: impl FnOnce(&mut E) -> R,
) -> R
where
    E: SearchEvaluation,
{
    let parent_depth = eval_state.stack_depth();
    eval_state.push_child(parent, child);
    let child_depth = parent_depth + usize::from(parent_depth != 0);
    debug_assert_eq!(eval_state.stack_depth(), child_depth);
    let result = search(eval_state);
    debug_assert_eq!(eval_state.stack_depth(), child_depth);
    eval_state.pop_child();
    debug_assert_eq!(eval_state.stack_depth(), parent_depth);
    result
}

// Simple piece values for MVV-LVA ordering (not PeSTO — just for sorting)
const MVV_LVA_VAL: [i32; 6] = [100, 320, 330, 500, 900, 20_000];

type Killers = [[Option<(u8, u8)>; 2]; MAX_DEPTH];

// History heuristic: [side_to_move (0=black, 1=white)][from_sq][to_sq]
// Tracks which quiet moves cause beta cutoffs across the search tree.
type History = [[[i32; 64]; 64]; 2];

// Countermove table: [side_to_move][previous_move_to_sq] = refuting move.
// When a quiet move causes a beta cutoff in response to the opponent's last
// move, that quiet move is stored here and tried early next time the same
// destination square is targeted.
type CounterMoves = [[Option<(u8, u8)>; 64]; 2];

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
// Static Exchange Evaluation
// ---------------------------------------------------------------------------

/// Find the square and piece type of the least valuable piece in `attackers`
/// for the given side. `attackers` must be non-zero.
fn least_valuable_attacker(board: &Board, attackers: u64, white: bool) -> (u8, u8) {
    let bbs: [u64; 6] = if white {
        [board.white_pawns, board.white_knights, board.white_bishops,
         board.white_rooks, board.white_queens, board.white_kings]
    } else {
        [board.black_pawns, board.black_knights, board.black_bishops,
         board.black_rooks, board.black_queens, board.black_kings]
    };
    for (piece_type, &bb) in bbs.iter().enumerate() {
        let overlap = attackers & bb;
        if overlap != 0 {
            return (overlap.trailing_zeros() as u8, piece_type as u8);
        }
    }
    (0, movegen::KING) // unreachable if attackers is non-zero
}

/// Static Exchange Evaluation. Returns the material balance of the capture
/// sequence starting with `mv` (positive = mover wins material).
/// En passant returns 0 (roughly even pawn trade).
fn see(board: &Board, mv: &Move) -> i32 {
    if mv.flags & movegen::FLAG_CAPTURE == 0 { return 0; }
    if mv.flags & movegen::FLAG_EN_PASSANT != 0 { return 0; }

    const SEE_VAL: [i32; 6] = [100, 320, 330, 500, 900, 20_000];

    let target_sq = mv.to_sq;
    let stm = board.side_to_move;

    let victim_type   = movegen::piece_type_at(board, target_sq, !stm);
    let attacker_type = movegen::piece_type_at(board, mv.from_sq, stm);

    let mut gains = [0i32; 32];
    gains[0] = SEE_VAL[victim_type as usize];

    let mut occupied = board.occupied();
    occupied ^= 1u64 << mv.from_sq;

    let mut side = !stm;
    let mut last_val = SEE_VAL[attacker_type as usize];
    let mut d = 1usize;

    loop {
        if d >= 32 { break; }

        let all_att = movegen::attackers_to(board, target_sq, occupied);
        let side_att = all_att
            & (if side { board.white_pieces() } else { board.black_pieces() })
            & occupied;
        if side_att == 0 { break; }

        let (lva_sq, lva_type) = least_valuable_attacker(board, side_att, side);
        if lva_sq >= 64 { break; }
        gains[d] = last_val - gains[d - 1];

        if std::cmp::max(-gains[d - 1], gains[d]) < 0 { break; }

        occupied ^= 1u64 << lva_sq;
        last_val = SEE_VAL[lva_type as usize];
        side = !side;
        d += 1;
    }

    let mut i = d - 1;
    while i > 0 {
        gains[i - 1] = -std::cmp::max(-gains[i - 1], gains[i]);
        i -= 1;
    }

    gains[0]
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
fn score_move(board: &Board, mv: &Move, killers: &Killers, ply: usize, tt_move: Option<(u8, u8)>, history: &History, counter_moves: &CounterMoves, prev_move: Option<(u8, u8)>) -> i32 {
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
        // SEE-negative captures go below killers; SEE-positive above
        if see(board, mv) < 0 {
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
    // Countermove heuristic: refutation of the opponent's last move (between killers and history)
    if let Some((_, pt)) = prev_move {
        if let Some((cf, ct)) = counter_moves[board.side_to_move as usize][pt as usize] {
            if mv.from_sq == cf && mv.to_sq == ct {
                return 4_500;
            }
        }
    }
    // History heuristic: differentiate quiet moves
    history[board.side_to_move as usize][mv.from_sq as usize][mv.to_sq as usize]
}

/// Sort moves in-place: TT move → captures (MVV-LVA) → killers → countermove → history → quiet.
fn order_moves(board: &Board, moves: &mut [Move], killers: &Killers, ply: usize, tt_move: Option<(u8, u8)>, history: &History, counter_moves: &CounterMoves, prev_move: Option<(u8, u8)>) {
    moves.sort_unstable_by(|a, b| {
        score_move(board, b, killers, ply, tt_move, history, counter_moves, prev_move)
            .cmp(&score_move(board, a, killers, ply, tt_move, history, counter_moves, prev_move))
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
// Time / node budget helpers
// ---------------------------------------------------------------------------

/// Returns true if the stop flag is set or the deadline has passed.
#[inline]
fn time_up(deadline: Option<std::time::Instant>, stop: &AtomicBool) -> bool {
    if stop.load(Ordering::Relaxed) {
        return true;
    }
    match deadline {
        Some(d) => std::time::Instant::now() >= d,
        None => false,
    }
}

// ---------------------------------------------------------------------------
// Quiescence search
// ---------------------------------------------------------------------------

/// Search captures only until the position is quiet.
fn quiescence<E: SearchEvaluation>(board: &Board, mut alpha: i32, beta: i32, ply: usize, eval_state: &mut E, nodes: &AtomicU64, node_limit: u64, deadline: Option<std::time::Instant>, stop: &AtomicBool) -> i32 {
    nodes.fetch_add(1, Ordering::Relaxed);

    let all_moves = generate_moves(board);

    // Detect checkmate / stalemate before stand-pat (must not be masked by beta cutoff)
    if all_moves.is_empty() {
        if is_in_check(board) {
            return -(CHECKMATE - ply as i32);
        }
        return 0;
    }

    let stand_pat = eval_state.evaluate(board);
    if stand_pat >= beta {
        return beta;
    }
    if stand_pat > alpha {
        alpha = stand_pat;
    }

    // Collect and order captures by MVV-LVA; prune SEE-negative captures
    let mut captures: Vec<Move> = all_moves
        .into_iter()
        .filter(|m| m.flags & movegen::FLAG_CAPTURE != 0 && see(board, m) >= 0)
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
        if nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, stop) {
            break;
        }
        let new_board = make_move(board, mv);
        let score = with_real_child(eval_state, board, &new_board, |child_state| {
            -quiescence(&new_board, -beta, -alpha, ply + 1, child_state, nodes, node_limit, deadline, stop)
        });
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
    let mut counter_moves: CounterMoves = [[None; 64]; 2];
    let nodes = AtomicU64::new(0);
    let tt = TTable::new();
    let stop = AtomicBool::new(false);
    let mut eval_state = PestoSearchState;
    ab_search(board, depth, alpha, beta, 0, &mut killers, &mut history, &mut counter_moves, None, &mut eval_state, true, &nodes, u64::MAX, None, &stop, &tt)
}

/// Recursive alpha-beta with move ordering, killer heuristic, history, NMP, LMR, and TT.
fn ab_search<E: SearchEvaluation>(
    board: &Board, depth: u32, mut alpha: i32, beta: i32,
    ply: usize, killers: &mut Killers, history: &mut History,
    counter_moves: &mut CounterMoves, prev_move: Option<(u8, u8)>,
    eval_state: &mut E,
    allow_null: bool, nodes: &AtomicU64, node_limit: u64,
    deadline: Option<std::time::Instant>,
    stop: &AtomicBool,
    tt: &TTable,
) -> i32 {
    nodes.fetch_add(1, Ordering::Relaxed);

    if nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, stop) {
        return eval_state.evaluate(board);
    }

    if depth == 0 {
        return quiescence(board, alpha, beta, ply, eval_state, nodes, node_limit, deadline, stop);
    }

    // Hard ply cap: prevents stack overflow from unlimited check extensions
    // in perpetual-check positions. Any position at this depth is quiesced.
    if ply >= 2 * MAX_DEPTH {
        return quiescence(board, alpha, beta, ply, eval_state, nodes, node_limit, deadline, stop);
    }

    // --- TT probe ---
    let hash = board.zobrist_hash();
    let mut tt_move: Option<(u8, u8)> = None;
    // Capture the pre-IID TT entry so SE only fires on genuine high-depth evidence,
    // not on the shallow entry that IID itself writes.
    let original_tt_entry = tt.probe(hash);

    if let Some(entry) = original_tt_entry {
        // Always use the best move for ordering (even from older generations)
        tt_move = entry.best_move();
        // Only trust scores from the current generation (same iterative deepening depth)
        if entry.gen == tt.gen() && entry.depth as u32 >= depth {
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

    // --- Check Extension ---
    // When the side to move is in check, extend search by 1 ply.
    // This catches forced tactical sequences that would otherwise fall
    // off the horizon. Extension bumps depth but not ply.
    // Capped at ply < MAX_DEPTH to prevent unbounded extension in check chains.
    let depth = if in_check && ply < MAX_DEPTH { depth + 1 } else { depth };

    // --- Null Move Pruning ---
    if allow_null && !in_check && depth >= 3 && board.occupied().count_ones() >= 10 {
        let null_board = board.make_null_move();
        let r = TUNE_NMP_REDUCTION.load(Ordering::Relaxed) as u32;
        let score = -ab_search(&null_board, depth - 1 - r, -beta, -beta + 1, ply + 1, killers, history, counter_moves, None, eval_state, false, nodes, node_limit, deadline, stop, tt);
        if score >= beta {
            return beta;
        }
    }

    // --- Internal Iterative Deepening ---
    // If no TT move, run a reduced-depth search to seed the TT before move ordering.
    // allow_null=false keeps the sub-search cheap. original_tt_entry (captured above)
    // ensures SE doesn't fire on the shallow entry IID writes.
    if IID_ENABLE.load(Ordering::Relaxed) && tt_move.is_none() && depth >= 4 && !in_check {
        ab_search(board, depth - 2, alpha, beta, ply, killers, history, counter_moves, prev_move, eval_state, false, nodes, node_limit, deadline, stop, tt);
        tt_move = tt.probe(hash).and_then(|e| e.best_move());
    }

    // --- Singular Extension ---
    // If the TT move is significantly better than all alternatives (tested
    // by a reduced-depth search excluding it), extend its search by 1 ply.
    // Gate on original_tt_entry (not a fresh probe) so IID's shallow write
    // cannot falsely satisfy the depth condition and trigger SE.
    let mut singular_extension: i32 = 0;
    if let Some(tt_mv) = tt_move {
        if let Some(entry) = original_tt_entry {
            let tt_score_raw = tt_score_probe(entry.score, ply);
            if entry.depth as u32 + 3 >= depth
                && depth >= 6
                && tt_score_raw.abs() < CHECKMATE - 1000
                && entry.flag != TT_UPPER
            {
                let se_beta = tt_score_raw - TUNE_SE_BETA_MARGIN.load(Ordering::Relaxed);
                let se_depth = depth / 2;
                let se_moves = generate_moves(board);
                let mut se_best = -INF;
                'se: for mv in &se_moves {
                    if mv.from_sq == tt_mv.0 && mv.to_sq == tt_mv.1 {
                        continue;
                    }
                    let new_board = make_move(board, mv);
                    let se_score = with_real_child(eval_state, board, &new_board, |child_state| {
                        -ab_search(
                            &new_board, se_depth.saturating_sub(1), -se_beta, -se_beta + 1,
                            ply + 1, killers, history, counter_moves, None, child_state, false,
                            nodes, node_limit, deadline, stop, tt,
                        )
                    });
                    if se_score >= se_beta {
                        se_best = se_score;
                        break 'se;
                    }
                    if se_score > se_best {
                        se_best = se_score;
                    }
                }
                if se_best < se_beta {
                    singular_extension = 1;
                }
            }
        }
    }

    let mut moves = generate_moves(board);

    if moves.is_empty() {
        if in_check {
            return -(CHECKMATE - ply as i32);
        }
        return 0;
    }

    order_moves(board, &mut moves, killers, ply, tt_move, history, counter_moves, prev_move);

    // --- Futility Pruning Setup ---
    // At shallow depths, if static eval + margin is still below alpha,
    // quiet moves are unlikely to raise the score enough to matter.
    // Skip them, searching only captures, promotions, and checks.
    //
    // Gates:
    //   - Not in check (quiet moves out of check can be survival-critical)
    //   - Depth <= 2 (only shallow — deeper searches need full coverage)
    //   - Alpha is not a mate score (don't skip moves while hunting mate)
    //   - Static eval is not a mate score (don't trust margins in mate zones)
    let futility_prune = !in_check
        && depth <= 2
        && alpha.abs() < CHECKMATE - 1000
        && {
            let static_eval = eval_state.evaluate(board);
            let margin: i32 = if depth == 1 {
                TUNE_FUTILITY_MARGIN_D1.load(Ordering::Relaxed)
            } else {
                TUNE_FUTILITY_MARGIN_D2.load(Ordering::Relaxed)
            };
            static_eval.abs() < CHECKMATE - 1000
                && static_eval + margin <= alpha
        };

    let original_alpha = alpha;
    let mut best_mv: Option<(u8, u8)> = None;

    let mut searched_all = true;
    // Track quiet moves searched before a cutoff (for history malus)
    let mut quiets_searched = [(0u8, 0u8); 128];
    let mut num_quiets = 0usize;

    for (move_index, mv) in moves.iter().enumerate() {
        if nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, stop) {
            searched_all = false;
            break;
        }

        let new_board = make_move(board, mv);
        let is_capture = mv.flags & movegen::FLAG_CAPTURE != 0;
        let is_promotion = mv.promotion.is_some();

        // Futility pruning: skip quiet, non-promoting, non-checking moves.
        if futility_prune && !is_capture && !is_promotion && !is_in_check(&new_board) {
            continue;
        }

        let is_killer = ply < MAX_DEPTH && killers[ply].iter().any(|k| {
            k.map_or(false, |(f, t)| f == mv.from_sq && t == mv.to_sq)
        });
        let hist_score = if !is_capture {
            history[board.side_to_move as usize][mv.from_sq as usize][mv.to_sq as usize]
        } else {
            0
        };

        let mv_prev = Some((mv.from_sq, mv.to_sq));
        let score = with_real_child(eval_state, board, &new_board, |child_state| {
            if move_index == 0 {
                // PV move: full window + full depth, plus singular extension if applicable.
                -ab_search(&new_board, depth - 1 + singular_extension as u32, -beta, -alpha, ply + 1, killers, history, counter_moves, mv_prev, child_state, true, nodes, node_limit, deadline, stop, tt)
            } else {
                // Non-PV moves: null window first (cheap probe), re-search on fail-high.
                let null_score;

                // --- Late Move Reductions (applied on top of null window) ---
                if depth >= 3 && move_index > TUNE_LMR_MOVE_INDEX.load(Ordering::Relaxed) as usize && !is_capture && !is_killer && !in_check {
                    null_score = -ab_search(&new_board, depth - 2, -alpha - 1, -alpha, ply + 1, killers, history, counter_moves, mv_prev, child_state, true, nodes, node_limit, deadline, stop, tt);
                } else {
                    null_score = -ab_search(&new_board, depth - 1, -alpha - 1, -alpha, ply + 1, killers, history, counter_moves, mv_prev, child_state, true, nodes, node_limit, deadline, stop, tt);
                }

                // Fail-high on null window: this move might be genuinely better.
                // Re-search at full depth + full window to get the real score.
                if null_score > alpha && null_score < beta {
                    -ab_search(&new_board, depth - 1, -beta, -alpha, ply + 1, killers, history, counter_moves, mv_prev, child_state, true, nodes, node_limit, deadline, stop, tt)
                } else {
                    null_score
                }
            }
        });

        if score >= beta {
            if !is_capture {
                store_killer(killers, ply, mv);
                // Countermove: record this quiet move as the refutation of the opponent's last move
                if let Some((_, pt)) = prev_move {
                    counter_moves[board.side_to_move as usize][pt as usize] = Some((mv.from_sq, mv.to_sq));
                }
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
        return eval_state.evaluate(board);
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
pub fn best_move(board: &Board, depth: u32, network: Option<&nnue::Network>) -> Option<SearchOutcome> {
    let moves = generate_moves(board);
    if moves.is_empty() {
        return None;
    }

    match network {
        Some(network) => best_move_with_state(
            board,
            depth,
            moves,
            NnueSearchState::from_root(network, board),
        ),
        None => best_move_with_state(board, depth, moves, PestoSearchState),
    }
}

fn best_move_with_state<E: SearchEvaluation>(
    board: &Board,
    depth: u32,
    mut moves: Vec<Move>,
    mut eval_state: E,
) -> Option<SearchOutcome> {
    let root_stack_depth = eval_state.stack_depth();

    let mut killers: Killers = [[None; 2]; MAX_DEPTH];
    let mut history: History = [[[0i32; 64]; 64]; 2];
    let mut counter_moves: CounterMoves = [[None; 64]; 2];
    let nodes = AtomicU64::new(0);
    let tt = TTable::new();
    let stop = AtomicBool::new(false);

    // Probe TT for root move ordering
    let root_hash = board.zobrist_hash();
    let tt_move = tt.probe(root_hash).and_then(|e| e.best_move());
    order_moves(board, &mut moves, &killers, 0, tt_move, &history, &counter_moves, None);

    let mut best: Option<(Move, i32)> = None;
    let mut alpha = -INF;
    let beta = INF;

    for mv in moves {
        let new_board = make_move(board, &mv);
        let score = with_real_child(&mut eval_state, board, &new_board, |child_state| {
            -ab_search(
                &new_board,
                depth - 1,
                -beta,
                -alpha,
                1,
                &mut killers,
                &mut history,
                &mut counter_moves,
                Some((mv.from_sq, mv.to_sq)),
                child_state,
                true,
                &nodes,
                u64::MAX,
                None,
                &stop,
                &tt,
            )
        });
        debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);
        if score > alpha {
            alpha = score;
            best = Some((mv, score));
        }
    }

    best.map(|(best_move, score)| SearchOutcome {
        best_move,
        score,
        depth,
        nodes: nodes.load(Ordering::Relaxed),
    })
}

/// Worker thread for Lazy SMP. Runs a simplified iterative-deepening
/// loop with no aspiration windows, warming the shared TTable.
/// Exits when `stop` is set to true by the main thread.
fn smp_worker<E: SearchEvaluation>(
    board: &Board,
    tt: &TTable,
    stop: &AtomicBool,
    deadline: Option<std::time::Instant>,
    node_limit: u64,
    mut eval_state: E,
    thread_id: usize,
) -> u64 {
    let mut killers: Killers = [[None; 2]; MAX_DEPTH];
    let mut history: History = [[[0i32; 64]; 64]; 2];
    let mut counter_moves: CounterMoves = [[None; 64]; 2];
    let nodes = AtomicU64::new(0);
    let moves = generate_moves(board);
    if moves.is_empty() {
        return 0;
    }
    let root_stack_depth = eval_state.stack_depth();

    // Each worker starts at a slightly different depth to ensure
    // diverse TT entries. Odd workers start at depth 2, even at 1.
    let start_depth: u32 = if thread_id % 2 == 0 { 1 } else { 2 };

    for depth in start_depth..=MAX_DEPTH as u32 {
        if stop.load(Ordering::Relaxed) || time_up(deadline, stop) {
            break;
        }

        let mut alpha = -INF;
        let beta = INF;
        killers = [[None; 2]; MAX_DEPTH];

        let root_hash = board.zobrist_hash();
        let tt_move = tt.probe(root_hash).and_then(|e| e.best_move());
        let mut ordered_moves = moves.clone();
        order_moves(board, &mut ordered_moves, &killers, 0, tt_move, &history, &counter_moves, None);

        for mv in &ordered_moves {
            if stop.load(Ordering::Relaxed) {
                return nodes.load(Ordering::Relaxed);
            }
            let new_board = make_move(board, mv);
            let score = with_real_child(&mut eval_state, board, &new_board, |child_state| {
                -ab_search(
                    &new_board,
                    depth - 1,
                    -beta,
                    -alpha,
                    1,
                    &mut killers,
                    &mut history,
                    &mut counter_moves,
                    Some((mv.from_sq, mv.to_sq)),
                    child_state,
                    true,
                    &nodes,
                    node_limit,
                    deadline,
                    stop,
                    tt,
                )
            });
            debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);
            if score > alpha {
                alpha = score;
            }
            if nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, stop) {
                break;
            }
        }
        debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);
    }

    nodes.load(Ordering::Relaxed)
}

/// Iterative deepening search with a node limit and aspiration windows.
/// Increases depth until the node budget is exhausted.
/// Returns the best move + score from the last completed depth.
/// TT persists across depths for move ordering benefit.
#[cfg(test)]
mod root_budget_test_hook {
    use std::sync::Mutex;
    use std::thread::{self, ThreadId};

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) enum Checkpoint {
        BeforeScore,
        AfterScore,
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) enum MoveTarget {
        Index(usize),
        Final,
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) enum ScoreScript {
        HoldAlpha,
        FailHighFirst,
        FailLowFirst,
        FailHighThenFailLow,
    }

    #[derive(Clone, Copy, Debug)]
    pub(super) struct Config {
        pub depth: u32,
        pub abort_attempt: usize,
        pub move_target: MoveTarget,
        pub checkpoint: Checkpoint,
        pub score_script: ScoreScript,
    }

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(super) struct Event {
        pub depth: u32,
        pub attempt: usize,
        pub move_index: usize,
        pub checkpoint: Checkpoint,
        pub window_alpha: i32,
        pub window_beta: i32,
    }

    #[derive(Debug)]
    pub(super) struct State {
        owner: ThreadId,
        config: Config,
        pub hit: Option<Event>,
        pub max_attempt: usize,
    }

    static CONTROL: Mutex<Option<State>> = Mutex::new(None);

    fn lock_control() -> std::sync::MutexGuard<'static, Option<State>> {
        CONTROL.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    pub(super) fn install(config: Config) {
        let mut control = lock_control();
        assert!(control.is_none(), "root budget test hook already installed");
        *control = Some(State {
            owner: thread::current().id(),
            config,
            hit: None,
            max_attempt: 0,
        });
    }

    pub(super) fn clear() {
        *lock_control() = None;
    }

    pub(super) fn take() -> State {
        lock_control()
            .take()
            .expect("root budget test hook was not installed")
    }

    pub(super) fn adjust_score(
        depth: u32,
        attempt: usize,
        score: i32,
        alpha: i32,
        beta: i32,
    ) -> i32 {
        let mut control = lock_control();
        let Some(state) = control.as_mut() else {
            return score;
        };
        if state.owner != thread::current().id() || state.config.depth != depth {
            return score;
        }

        state.max_attempt = state.max_attempt.max(attempt);
        match state.config.score_script {
            ScoreScript::HoldAlpha => alpha,
            ScoreScript::FailHighFirst if attempt == 1 => beta,
            ScoreScript::FailLowFirst if attempt == 1 => alpha,
            ScoreScript::FailHighThenFailLow if attempt == 1 => beta,
            ScoreScript::FailHighThenFailLow if attempt == 2 => alpha,
            _ => score,
        }
    }

    pub(super) fn should_abort(
        depth: u32,
        attempt: usize,
        move_index: usize,
        move_count: usize,
        checkpoint: Checkpoint,
        window_alpha: i32,
        window_beta: i32,
    ) -> bool {
        let mut control = lock_control();
        let Some(state) = control.as_mut() else {
            return false;
        };
        if state.owner != thread::current().id() || state.config.depth != depth {
            return false;
        }

        state.max_attempt = state.max_attempt.max(attempt);
        let target_index = match state.config.move_target {
            MoveTarget::Index(index) => index,
            MoveTarget::Final => move_count.saturating_sub(1),
        };
        if state.hit.is_none()
            && attempt == state.config.abort_attempt
            && move_index == target_index
            && checkpoint == state.config.checkpoint
        {
            state.hit = Some(Event {
                depth,
                attempt,
                move_index,
                checkpoint,
                window_alpha,
                window_beta,
            });
            return true;
        }
        false
    }
}

pub fn best_move_nodes(board: &Board, node_limit: u64, deadline: Option<std::time::Instant>, network: Option<&nnue::Network>, num_threads: usize) -> Option<SearchOutcome> {
    let moves = generate_moves(board);
    if moves.is_empty() {
        return None;
    }

    match network {
        Some(network) => best_move_nodes_with_state(
            board,
            node_limit,
            deadline,
            num_threads,
            moves,
            NnueSearchState::from_root(network, board),
        ),
        None => best_move_nodes_with_state(
            board,
            node_limit,
            deadline,
            num_threads,
            moves,
            PestoSearchState,
        ),
    }
}

fn best_move_nodes_with_state<E: SearchEvaluation>(
    board: &Board,
    node_limit: u64,
    deadline: Option<std::time::Instant>,
    num_threads: usize,
    moves: Vec<Move>,
    mut eval_state: E,
) -> Option<SearchOutcome> {
    let asp_delta = TUNE_ASPIRATION_DELTA.load(Ordering::Relaxed);
    const MATE_THRESHOLD: i32 = CHECKMATE - 1000;

    let tt = TTable::new();
    let stop = AtomicBool::new(false);
    let mut best_overall: Option<(Move, i32, u32)> = None;
    let mut total_nodes = 0u64;

    // thread::scope lets workers borrow board, tt, stop, network from
    // this stack frame without requiring 'static lifetimes.
    std::thread::scope(|s| {
        // Spawn N-1 worker threads that warm the TT with independent
        // searches at slightly offset depths. They don't return moves.
        // Take explicit shared refs so only &-ptrs (Copy) are moved into
        // each closure — avoids moving TTable/AtomicBool out of the frame.
        let tt_ref   = &tt;
        let stop_ref = &stop;
        let num_workers = num_threads.saturating_sub(1);
        let mut worker_handles = Vec::with_capacity(num_workers);
        for thread_id in 1..=num_workers {
            let worker_eval_state = eval_state.fork_root();
            worker_handles.push(s.spawn(move || {
                smp_worker(
                    board,
                    tt_ref,
                    stop_ref,
                    deadline,
                    node_limit,
                    worker_eval_state,
                    thread_id,
                )
            }));
        }

        // ---- Main thread: full aspiration-window ID loop ----
        let mut history: History = [[[0i32; 64]; 64]; 2];
        let mut counter_moves: CounterMoves = [[None; 64]; 2];
        let root_hash = board.zobrist_hash();
        let mut prev_score: Option<i32> = None;
        let mut main_nodes = 0u64;
        let root_stack_depth = eval_state.stack_depth();

        for depth in 1..=MAX_DEPTH as u32 {
            // Soft check: don't start a new iteration if the deadline has
            // already passed. The result from the previous depth stays in best_overall.
            // Depth 1 always runs so we always have something to return.
            if depth > 1 && time_up(deadline, &stop) {
                break;
            }

            tt.next_gen();

            // Decide aspiration window for this iteration.
            // Depth 1 or after a mate score: use full window.
            // Otherwise: center on previous score with +/- DELTA.
            let (mut alpha_init, mut beta_init) = match prev_score {
                Some(s) if depth > 1 && s.abs() < MATE_THRESHOLD => {
                    (s - asp_delta, s + asp_delta)
                }
                _ => (-INF, INF),
            };

            // Re-search loop: widen window on fail-low or fail-high.
            let nodes = AtomicU64::new(0);
            #[cfg(test)]
            let mut root_attempt = 0usize;
            let (iter_best, iter_completed) = loop {
                #[cfg(test)]
                {
                    root_attempt += 1;
                }
                let mut killers: Killers = [[None; 2]; MAX_DEPTH];
                let mut ordered_moves = moves.clone();

                let tt_move = tt.probe(root_hash).and_then(|e| e.best_move());
                order_moves(board, &mut ordered_moves, &killers, 0, tt_move, &history, &counter_moves, None);

                let mut best: Option<(Move, i32)> = None;
                let mut alpha = alpha_init;
                let beta = beta_init;
                let mut completed = true;
                let mut fail_high = false;

                #[cfg(test)]
                let mut test_move_index = 0usize;
                for mv in ordered_moves.iter() {
                    #[cfg(test)]
                    let move_index = {
                        let index = test_move_index;
                        test_move_index += 1;
                        index
                    };

                    let new_board = make_move(board, mv);
                    let score = with_real_child(
                        &mut eval_state,
                        board,
                        &new_board,
                        |child_state| {
                            -ab_search(
                                &new_board,
                                depth - 1,
                                -beta,
                                -alpha,
                                1,
                                &mut killers,
                                &mut history,
                                &mut counter_moves,
                                Some((mv.from_sq, mv.to_sq)),
                                child_state,
                                true,
                                &nodes,
                                node_limit,
                                deadline,
                                &stop,
                                &tt,
                            )
                        },
                    );
                    debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);

                    let budget_exhausted =
                        nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, &stop);
                    #[cfg(test)]
                    let budget_exhausted = budget_exhausted
                        || root_budget_test_hook::should_abort(
                            depth,
                            root_attempt,
                            move_index,
                            ordered_moves.len(),
                            root_budget_test_hook::Checkpoint::BeforeScore,
                            alpha_init,
                            beta_init,
                        );
                    if budget_exhausted {
                        completed = false;
                        break;
                    }

                    #[cfg(test)]
                    let score = root_budget_test_hook::adjust_score(
                        depth,
                        root_attempt,
                        score,
                        alpha,
                        beta,
                    );

                    // Fail-high at root: score == beta under fail-hard.
                    // Record the move, break, and re-search with wider beta.
                    if score >= beta {
                        best = Some((mv.clone(), score));
                        fail_high = true;
                        break;
                    }

                    if score > alpha {
                        alpha = score;
                        best = Some((mv.clone(), score));
                    }

                    let budget_exhausted =
                        nodes.load(Ordering::Relaxed) >= node_limit || time_up(deadline, &stop);
                    #[cfg(test)]
                    let budget_exhausted = budget_exhausted
                        || root_budget_test_hook::should_abort(
                            depth,
                            root_attempt,
                            move_index,
                            ordered_moves.len(),
                            root_budget_test_hook::Checkpoint::AfterScore,
                            alpha_init,
                            beta_init,
                        );
                    if budget_exhausted {
                        completed = false;
                        break;
                    }
                }
                debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);

                // Node budget exhausted mid-iteration — bail out of re-search loop.
                if !completed {
                    break (best, false);
                }

                // Fail-high: widen beta to INF and re-search.
                if fail_high && beta_init < INF {
                    beta_init = INF;
                    continue;
                }

                // Fail-low: no move exceeded alpha_init. Widen alpha to -INF and re-search.
                // Detected by: best is None OR best's score equals alpha_init (didn't improve).
                let failed_low = match &best {
                    None => alpha_init > -INF,
                    Some((_, s)) => *s <= alpha_init && alpha_init > -INF,
                };
                if failed_low {
                    alpha_init = -INF;
                    continue;
                }

                // Clean completion within the window.
                break (best, true);
            };
            debug_assert_eq!(eval_state.stack_depth(), root_stack_depth);

            // The main-thread counter is intentionally still per depth so
            // `go nodes` retains its historical budget behavior.  Aggregate
            // it only after the iteration/re-search work has finished.
            main_nodes = main_nodes.saturating_add(nodes.load(Ordering::Relaxed));

            if iter_completed {
                if let Some((mv, score)) = iter_best {
                    best_overall = Some((mv, score, depth));
                    prev_score = Some(score);
                }
            } else {
                // Budget exhausted mid-iteration. Only commit if we have no prior
                // result at all (otherwise keep the last fully-searched depth).
                if best_overall.is_none() {
                    if let Some((mv, score)) = iter_best {
                        best_overall = Some((mv, score, depth));
                    }
                }
                break;
            }
        }

        // Signal workers to stop. The scope join point below waits for them.
        stop.store(true, Ordering::Relaxed);

        let helper_nodes = worker_handles
            .into_iter()
            .map(|handle| handle.join().expect("Lazy-SMP worker panicked"))
            .fold(0u64, u64::saturating_add);
        total_nodes = main_nodes.saturating_add(helper_nodes);
    });

    best_overall.map(|(best_move, score, depth)| SearchOutcome {
        best_move,
        score,
        depth,
        nodes: total_nodes,
    })
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
        let outcome = result.unwrap();
        assert_eq!(outcome.best_move.to_uci(), "d1d5", "Should capture the queen");
        assert!(outcome.score > 800, "Score should reflect queen capture, got {}", outcome.score);
        assert!(outcome.nodes > 0, "Search should report visited nodes");
    }

    #[test]
    fn finds_checkmate_in_one() {
        // White to move, Qh5# is mate (back rank)
        let board = Board::from_fen("6k1/5ppp/8/8/8/8/8/4K2Q w - - 0 1").unwrap();
        let result = best_move(&board, 2, None);
        assert!(result.is_some());
        let outcome = result.unwrap();
        assert!(outcome.score > 40_000, "Should find checkmate, score={}", outcome.score);
    }

    #[test]
    fn finds_qh4_mate_in_one() {
        // Black to move after 1.f3 e5 2.g4 — Qh4# is checkmate
        let board = Board::from_fen("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2").unwrap();
        let result = best_move(&board, 1, None);
        assert!(result.is_some());
        let outcome = result.unwrap();
        assert_eq!(outcome.best_move.to_uci(), "d8h4", "Should find Qh4# checkmate");
        assert!(outcome.score > 40_000, "Should return mate score, got {}", outcome.score);
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
        let outcome = result.unwrap();
        // Queen should not stay on e3 where it gets captured
        assert!(
            outcome.best_move.from_sq == 20, // e3
            "Queen should move, got {}",
            outcome.best_move.to_uci()
        );
    }

    #[test]
    fn nnue_search_stacks_balance_on_fixed_iterative_and_helper_paths() {
        let board = Board::startpos();
        let network = nnue::Network::from_random();

        let fixed = best_move(&board, 2, Some(&network));
        assert!(fixed.is_some(), "fixed-depth NNUE search returned no move");

        let iterative = best_move_nodes(&board, 1_000, None, Some(&network), 2);
        assert!(iterative.is_some(), "iterative NNUE search returned no move");
    }

    struct RootHookReset;

    impl Drop for RootHookReset {
        fn drop(&mut self) {
            root_budget_test_hook::clear();
        }
    }

    #[test]
    fn interrupted_root_iterations_keep_last_completed_tuple() {
        use root_budget_test_hook::{
            Checkpoint, Config, MoveTarget, ScoreScript,
        };

        let board = Board::startpos();
        let depth_one = best_move(&board, 1, None)
            .expect("startpos must have a depth-1 move");
        let expected_uci = depth_one.best_move.to_uci();
        let depth_one_score = depth_one.score;
        let legal_moves = generate_moves(&board);

        let cases = [
            (
                "first_root_move_before_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(0),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "first_root_move_after_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(0),
                    checkpoint: Checkpoint::AfterScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "second_root_move_before_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(1),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "second_root_move_after_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(1),
                    checkpoint: Checkpoint::AfterScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "later_root_move_before_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(3),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "later_root_move_after_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Index(3),
                    checkpoint: Checkpoint::AfterScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "final_root_move_before_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Final,
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "final_root_move_after_score",
                Config {
                    depth: 2,
                    abort_attempt: 1,
                    move_target: MoveTarget::Final,
                    checkpoint: Checkpoint::AfterScore,
                    score_script: ScoreScript::HoldAlpha,
                },
            ),
            (
                "fail_high_research",
                Config {
                    depth: 2,
                    abort_attempt: 2,
                    move_target: MoveTarget::Index(0),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::FailHighFirst,
                },
            ),
            (
                "fail_low_research",
                Config {
                    depth: 2,
                    abort_attempt: 2,
                    move_target: MoveTarget::Index(0),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::FailLowFirst,
                },
            ),
            (
                "full_window_research",
                Config {
                    depth: 2,
                    abort_attempt: 3,
                    move_target: MoveTarget::Index(0),
                    checkpoint: Checkpoint::BeforeScore,
                    score_script: ScoreScript::FailHighThenFailLow,
                },
            ),
        ];

        for (label, config) in cases {
            root_budget_test_hook::install(config);
            let reset = RootHookReset;

            let actual = best_move_nodes(&board, u64::MAX, None, None, 1)
                .unwrap_or_else(|| panic!("{label}: expected preserved depth-1 result"));
            let state = root_budget_test_hook::take();
            drop(reset);

            let event = state
                .hit
                .unwrap_or_else(|| panic!("{label}: test hook never reached its abort point"));
            assert_eq!(
                state.max_attempt, config.abort_attempt,
                "{label}: unexpected re-search attempt count"
            );
            assert_eq!(event.depth, config.depth, "{label}: wrong abort depth");
            assert_eq!(
                event.attempt, config.abort_attempt,
                "{label}: wrong abort attempt"
            );
            assert_eq!(
                event.checkpoint, config.checkpoint,
                "{label}: wrong abort checkpoint"
            );
            match config.move_target {
                MoveTarget::Index(index) => assert_eq!(
                    event.move_index, index,
                    "{label}: wrong root move index"
                ),
                MoveTarget::Final => assert_eq!(
                    event.move_index + 1,
                    legal_moves.len(),
                    "{label}: abort was not on the final root move"
                ),
            }

            match label {
                "fail_high_research" => {
                    assert_ne!(event.window_alpha, -INF);
                    assert_eq!(event.window_beta, INF);
                }
                "fail_low_research" => {
                    assert_eq!(event.window_alpha, -INF);
                    assert_ne!(event.window_beta, INF);
                }
                "full_window_research" => {
                    assert_eq!(event.window_alpha, -INF);
                    assert_eq!(event.window_beta, INF);
                }
                _ => {}
            }

            assert_eq!(actual.depth, 1, "{label}: partial depth replaced depth 1");
            assert_eq!(
                actual.best_move.to_uci(),
                expected_uci,
                "{label}: move did not come from completed depth 1"
            );
            assert_eq!(
                actual.score, depth_one_score,
                "{label}: score did not come from completed depth 1"
            );
            assert!(
                legal_moves.iter().any(|mv| mv.to_uci() == actual.best_move.to_uci()),
                "{label}: preserved move is illegal"
            );
            assert!(actual.nodes > 0, "{label}: node total was not reported");
        }
    }
}
