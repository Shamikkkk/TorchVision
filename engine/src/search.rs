use crate::board::Board;
use crate::movegen::{self, Move, generate_moves, is_in_check, make_move};
use crate::nnue;

const INF: i32 = 100_000;
const CHECKMATE: i32 = 50_000;

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
    let score = (mg * mg_phase + eg * eg_phase) / MAX_PHASE;

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
fn score_move(board: &Board, mv: &Move, killers: &Killers, ply: usize) -> i32 {
    if mv.flags & movegen::FLAG_CAPTURE != 0 {
        let victim = if mv.flags & movegen::FLAG_EN_PASSANT != 0 {
            MVV_LVA_VAL[0] // en passant always captures a pawn
        } else {
            piece_val_on(board, mv.to_sq, !board.side_to_move)
        };
        let attacker = piece_val_on(board, mv.from_sq, board.side_to_move);
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
    0
}

/// Sort moves in-place: captures (MVV-LVA) → killers → quiet.
fn order_moves(board: &Board, moves: &mut [Move], killers: &Killers, ply: usize) {
    moves.sort_unstable_by(|a, b| {
        score_move(board, b, killers, ply)
            .cmp(&score_move(board, a, killers, ply))
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
fn quiescence(board: &Board, mut alpha: i32, beta: i32, network: Option<&nnue::Network>) -> i32 {
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

    let all_moves = generate_moves(board);
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
        let new_board = make_move(board, mv);
        let score = -quiescence(&new_board, -beta, -alpha, network);
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
    ab_search(board, depth, alpha, beta, 0, &mut killers, None, true)
}

/// Recursive alpha-beta with move ordering, killer heuristic, NMP, and LMR.
fn ab_search(
    board: &Board, depth: u32, mut alpha: i32, beta: i32,
    ply: usize, killers: &mut Killers, network: Option<&nnue::Network>,
    allow_null: bool,
) -> i32 {
    if depth == 0 {
        return quiescence(board, alpha, beta, network);
    }

    let in_check = is_in_check(board);

    // --- Null Move Pruning ---
    // Skip when: in check, not enough pieces, or after a previous null move
    if allow_null && !in_check && depth >= 3 && board.occupied().count_ones() >= 10 {
        let null_board = board.make_null_move();
        let r = 2; // reduction
        let score = -ab_search(&null_board, depth - 1 - r, -beta, -beta + 1, ply + 1, killers, network, false);
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

    order_moves(board, &mut moves, killers, ply);

    for (move_index, mv) in moves.iter().enumerate() {
        let new_board = make_move(board, mv);
        let is_capture = mv.flags & movegen::FLAG_CAPTURE != 0;
        let is_killer = ply < MAX_DEPTH && killers[ply].iter().any(|k| {
            k.map_or(false, |(f, t)| f == mv.from_sq && t == mv.to_sq)
        });

        let score;

        // --- Late Move Reductions ---
        // Reduce quiet non-killer moves beyond move 3 at depth >= 3
        if depth >= 3 && move_index > 3 && !is_capture && !is_killer && !in_check {
            // Reduced search (depth - 2 instead of depth - 1)
            let reduced = -ab_search(&new_board, depth - 2, -beta, -alpha, ply + 1, killers, network, true);
            if reduced > alpha {
                // Re-search at full depth if reduced search looks interesting
                score = -ab_search(&new_board, depth - 1, -beta, -alpha, ply + 1, killers, network, true);
            } else {
                score = reduced;
            }
        } else {
            score = -ab_search(&new_board, depth - 1, -beta, -alpha, ply + 1, killers, network, true);
        }

        if score >= beta {
            if !is_capture {
                store_killer(killers, ply, mv);
            }
            return beta;
        }
        if score > alpha {
            alpha = score;
        }
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
    // Order root moves (ply 0)
    order_moves(board, &mut moves, &killers, 0);

    let mut best: Option<(Move, i32)> = None;
    let mut alpha = -INF;
    let beta = INF;

    for mv in moves {
        let new_board = make_move(board, &mv);
        let score = -ab_search(&new_board, depth - 1, -beta, -alpha, 1, &mut killers, network, true);
        if score > alpha {
            alpha = score;
            best = Some((mv, score));
        }
    }

    best
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
