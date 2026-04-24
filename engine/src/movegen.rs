use crate::board::{Board, CASTLING_WK, CASTLING_WQ, CASTLING_BK, CASTLING_BQ};

// Piece types (for promotion field)
pub const PAWN: u8 = 0;
pub const KNIGHT: u8 = 1;
pub const BISHOP: u8 = 2;
pub const ROOK: u8 = 3;
pub const QUEEN: u8 = 4;
pub const KING: u8 = 5;

// Move flags
pub const FLAG_CAPTURE: u8 = 0x01;
pub const FLAG_EN_PASSANT: u8 = 0x02;
pub const FLAG_CASTLING: u8 = 0x04;

// File and rank masks
const FILE_A: u64 = 0x0101_0101_0101_0101;
const FILE_H: u64 = 0x8080_8080_8080_8080;
const RANK_1: u64 = 0x0000_0000_0000_00FF;
const RANK_2: u64 = 0x0000_0000_0000_FF00;
const RANK_3: u64 = 0x0000_0000_00FF_0000;
const RANK_6: u64 = 0x0000_FF00_0000_0000;
const RANK_7: u64 = 0x00FF_0000_0000_0000;
const RANK_8: u64 = 0xFF00_0000_0000_0000;

// ---------------------------------------------------------------------------
// Precomputed attack tables (computed at compile time)
// ---------------------------------------------------------------------------

static KNIGHT_ATTACKS: [u64; 64] = init_knight_attacks();
static KING_ATTACKS: [u64; 64] = init_king_attacks();

const fn init_knight_attacks() -> [u64; 64] {
    let mut table = [0u64; 64];
    let offsets: [(i8, i8); 8] = [
        (2, 1), (2, -1), (-2, 1), (-2, -1),
        (1, 2), (1, -2), (-1, 2), (-1, -2),
    ];
    let mut sq: u8 = 0;
    while sq < 64 {
        let rank = (sq / 8) as i8;
        let file = (sq % 8) as i8;
        let mut i = 0;
        while i < 8 {
            let r = rank + offsets[i].0;
            let f = file + offsets[i].1;
            if r >= 0 && r < 8 && f >= 0 && f < 8 {
                table[sq as usize] |= 1u64 << (r * 8 + f);
            }
            i += 1;
        }
        sq += 1;
    }
    table
}

const fn init_king_attacks() -> [u64; 64] {
    let mut table = [0u64; 64];
    let offsets: [(i8, i8); 8] = [
        (1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1),
    ];
    let mut sq: u8 = 0;
    while sq < 64 {
        let rank = (sq / 8) as i8;
        let file = (sq % 8) as i8;
        let mut i = 0;
        while i < 8 {
            let r = rank + offsets[i].0;
            let f = file + offsets[i].1;
            if r >= 0 && r < 8 && f >= 0 && f < 8 {
                table[sq as usize] |= 1u64 << (r * 8 + f);
            }
            i += 1;
        }
        sq += 1;
    }
    table
}

// ---------------------------------------------------------------------------
// Move struct
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Move {
    pub from_sq: u8,
    pub to_sq: u8,
    pub promotion: Option<u8>,
    pub flags: u8,
}

impl Move {
    pub fn to_uci(&self) -> String {
        let from_file = (b'a' + self.from_sq % 8) as char;
        let from_rank = (b'1' + self.from_sq / 8) as char;
        let to_file = (b'a' + self.to_sq % 8) as char;
        let to_rank = (b'1' + self.to_sq / 8) as char;
        let promo = match self.promotion {
            Some(KNIGHT) => "n",
            Some(BISHOP) => "b",
            Some(ROOK) => "r",
            Some(QUEEN) => "q",
            _ => "",
        };
        format!("{}{}{}{}{}", from_file, from_rank, to_file, to_rank, promo)
    }
}

// ---------------------------------------------------------------------------
// Sliding piece attacks (ray-based, no magic bitboards)
// ---------------------------------------------------------------------------

const BISHOP_DIRS: [(i8, i8); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
const ROOK_DIRS: [(i8, i8); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];

fn sliding_attacks(sq: u8, occupied: u64, dirs: &[(i8, i8)]) -> u64 {
    let mut attacks = 0u64;
    let rank = (sq / 8) as i8;
    let file = (sq % 8) as i8;
    for &(dr, df) in dirs {
        let mut r = rank + dr;
        let mut f = file + df;
        while r >= 0 && r < 8 && f >= 0 && f < 8 {
            let target = (r * 8 + f) as u8;
            attacks |= 1u64 << target;
            if occupied & (1u64 << target) != 0 {
                break;
            }
            r += dr;
            f += df;
        }
    }
    attacks
}

pub(crate) fn bishop_attacks(sq: u8, occupied: u64) -> u64 {
    sliding_attacks(sq, occupied, &BISHOP_DIRS)
}

pub(crate) fn rook_attacks(sq: u8, occupied: u64) -> u64 {
    sliding_attacks(sq, occupied, &ROOK_DIRS)
}

// ---------------------------------------------------------------------------
// Square attack detection
// ---------------------------------------------------------------------------

/// Returns true if `sq` is attacked by a piece belonging to `by_white`.
pub fn is_square_attacked(board: &Board, sq: u8, by_white: bool) -> bool {
    let sq_bit = 1u64 << sq;
    let occupied = board.occupied();

    // Knight attacks
    let knights = if by_white { board.white_knights } else { board.black_knights };
    if KNIGHT_ATTACKS[sq as usize] & knights != 0 {
        return true;
    }

    // King attacks
    let king = if by_white { board.white_kings } else { board.black_kings };
    if KING_ATTACKS[sq as usize] & king != 0 {
        return true;
    }

    // Pawn attacks (look for pawns that attack *this* square)
    let pawns = if by_white { board.white_pawns } else { board.black_pawns };
    let pawn_attackers = if by_white {
        // White pawns attack upward: a pawn at sq-7 (NW source) or sq-9 (NE source)
        ((sq_bit >> 7) & !FILE_A) | ((sq_bit >> 9) & !FILE_H)
    } else {
        // Black pawns attack downward: a pawn at sq+7 (SE source) or sq+9 (SW source)
        ((sq_bit << 7) & !FILE_H) | ((sq_bit << 9) & !FILE_A)
    };
    if pawn_attackers & pawns != 0 {
        return true;
    }

    // Bishop / Queen (diagonal)
    let bq = if by_white {
        board.white_bishops | board.white_queens
    } else {
        board.black_bishops | board.black_queens
    };
    if bishop_attacks(sq, occupied) & bq != 0 {
        return true;
    }

    // Rook / Queen (orthogonal)
    let rq = if by_white {
        board.white_rooks | board.white_queens
    } else {
        board.black_rooks | board.black_queens
    };
    if rook_attacks(sq, occupied) & rq != 0 {
        return true;
    }

    false
}

/// Returns a bitboard of ALL pieces (both colors) attacking `sq` given the
/// provided `occupied` mask. As SEE removes pieces from `occupied` each ply,
/// sliding rays automatically discover X-ray attackers behind removed pieces.
pub(crate) fn attackers_to(board: &Board, sq: u8, occupied: u64) -> u64 {
    if sq >= 64 { return 0; }
    let sq_idx = sq as usize;
    let sq_bb = 1u64 << sq;
    let mut att = 0u64;

    // Knights
    att |= KNIGHT_ATTACKS[sq_idx] & (board.white_knights | board.black_knights) & occupied;

    // Kings
    att |= KING_ATTACKS[sq_idx] & (board.white_kings | board.black_kings) & occupied;

    // White pawns: a white pawn at sq-7 or sq-9 attacks sq (mirrors is_square_attacked logic)
    // Right shifts on u64 are always safe (truncate toward 0).
    att |= (((sq_bb >> 7) & !FILE_A) | ((sq_bb >> 9) & !FILE_H)) & board.white_pawns & occupied;

    // Black pawns: a black pawn at sq+7 or sq+9 attacks sq.
    // Use wrapping_shl to avoid debug-mode panic when sq >= 57/55 (no black pawn can be above
    // rank 8 anyway, so the shift would produce 0 after the FILE mask in those cases).
    att |= ((sq_bb.wrapping_shl(7) & !FILE_H) | (sq_bb.wrapping_shl(9) & !FILE_A))
        & board.black_pawns & occupied;

    // Bishops + Queens (diagonal), using updated occupied for X-ray
    let diag = (board.white_bishops | board.black_bishops
              | board.white_queens  | board.black_queens) & occupied;
    att |= bishop_attacks(sq, occupied) & diag;

    // Rooks + Queens (orthogonal)
    let orth = (board.white_rooks | board.black_rooks
              | board.white_queens | board.black_queens) & occupied;
    att |= rook_attacks(sq, occupied) & orth;

    att
}

/// Returns true if the side to move is in check.
pub fn is_in_check(board: &Board) -> bool {
    let is_white = board.side_to_move;
    let king_bb = if is_white { board.white_kings } else { board.black_kings };
    if king_bb == 0 {
        return false;
    }
    let king_sq = king_bb.trailing_zeros() as u8;
    is_square_attacked(board, king_sq, !is_white)
}

// ---------------------------------------------------------------------------
// Bitboard helpers
// ---------------------------------------------------------------------------

fn pop_lsb(bb: &mut u64) -> u8 {
    let sq = bb.trailing_zeros() as u8;
    *bb &= *bb - 1;
    sq
}

// ---------------------------------------------------------------------------
// Make move (apply a move to a board copy, for legality testing)
// ---------------------------------------------------------------------------

pub(crate) fn piece_type_at(board: &Board, sq: u8, is_white: bool) -> u8 {
    if sq >= 64 { return KING; }
    let bit = 1u64 << sq;
    if is_white {
        if board.white_pawns & bit != 0 { return PAWN; }
        if board.white_knights & bit != 0 { return KNIGHT; }
        if board.white_bishops & bit != 0 { return BISHOP; }
        if board.white_rooks & bit != 0 { return ROOK; }
        if board.white_queens & bit != 0 { return QUEEN; }
        KING
    } else {
        if board.black_pawns & bit != 0 { return PAWN; }
        if board.black_knights & bit != 0 { return KNIGHT; }
        if board.black_bishops & bit != 0 { return BISHOP; }
        if board.black_rooks & bit != 0 { return ROOK; }
        if board.black_queens & bit != 0 { return QUEEN; }
        KING
    }
}

fn set_piece(board: &mut Board, sq: u8, is_white: bool, piece: u8) {
    let bit = 1u64 << sq;
    match (is_white, piece) {
        (true, PAWN) => board.white_pawns |= bit,
        (true, KNIGHT) => board.white_knights |= bit,
        (true, BISHOP) => board.white_bishops |= bit,
        (true, ROOK) => board.white_rooks |= bit,
        (true, QUEEN) => board.white_queens |= bit,
        (true, KING) => board.white_kings |= bit,
        (false, PAWN) => board.black_pawns |= bit,
        (false, KNIGHT) => board.black_knights |= bit,
        (false, BISHOP) => board.black_bishops |= bit,
        (false, ROOK) => board.black_rooks |= bit,
        (false, QUEEN) => board.black_queens |= bit,
        (false, KING) => board.black_kings |= bit,
        _ => {}
    }
}

fn clear_piece(board: &mut Board, sq: u8, is_white: bool, piece: u8) {
    let mask = !(1u64 << sq);
    match (is_white, piece) {
        (true, PAWN) => board.white_pawns &= mask,
        (true, KNIGHT) => board.white_knights &= mask,
        (true, BISHOP) => board.white_bishops &= mask,
        (true, ROOK) => board.white_rooks &= mask,
        (true, QUEEN) => board.white_queens &= mask,
        (true, KING) => board.white_kings &= mask,
        (false, PAWN) => board.black_pawns &= mask,
        (false, KNIGHT) => board.black_knights &= mask,
        (false, BISHOP) => board.black_bishops &= mask,
        (false, ROOK) => board.black_rooks &= mask,
        (false, QUEEN) => board.black_queens &= mask,
        (false, KING) => board.black_kings &= mask,
        _ => {}
    }
}

/// Clear any piece of the given color from a square (used for captures).
fn clear_square(board: &mut Board, sq: u8, is_white: bool) {
    let mask = !(1u64 << sq);
    if is_white {
        board.white_pawns &= mask;
        board.white_knights &= mask;
        board.white_bishops &= mask;
        board.white_rooks &= mask;
        board.white_queens &= mask;
        board.white_kings &= mask;
    } else {
        board.black_pawns &= mask;
        board.black_knights &= mask;
        board.black_bishops &= mask;
        board.black_rooks &= mask;
        board.black_queens &= mask;
        board.black_kings &= mask;
    }
}

/// Apply a move to a board, returning the new board state.
pub fn make_move(board: &Board, mv: &Move) -> Board {
    let mut b = board.clone();
    let is_white = board.side_to_move;
    let piece = piece_type_at(board, mv.from_sq, is_white);

    // Remove piece from source square
    clear_piece(&mut b, mv.from_sq, is_white, piece);

    // Handle capture
    if mv.flags & FLAG_CAPTURE != 0 {
        if mv.flags & FLAG_EN_PASSANT != 0 {
            // En passant: captured pawn is behind the target square
            let cap_sq = if is_white { mv.to_sq - 8 } else { mv.to_sq + 8 };
            clear_square(&mut b, cap_sq, !is_white);
        } else {
            clear_square(&mut b, mv.to_sq, !is_white);
        }
    }

    // Place piece at destination (possibly promoted)
    let dest_piece = mv.promotion.unwrap_or(piece);
    set_piece(&mut b, mv.to_sq, is_white, dest_piece);

    // Handle castling — move the rook
    if mv.flags & FLAG_CASTLING != 0 {
        match mv.to_sq {
            6 => {
                // White kingside: rook h1(7) → f1(5)
                clear_piece(&mut b, 7, true, ROOK);
                set_piece(&mut b, 5, true, ROOK);
            }
            2 => {
                // White queenside: rook a1(0) → d1(3)
                clear_piece(&mut b, 0, true, ROOK);
                set_piece(&mut b, 3, true, ROOK);
            }
            62 => {
                // Black kingside: rook h8(63) → f8(61)
                clear_piece(&mut b, 63, false, ROOK);
                set_piece(&mut b, 61, false, ROOK);
            }
            58 => {
                // Black queenside: rook a8(56) → d8(59)
                clear_piece(&mut b, 56, false, ROOK);
                set_piece(&mut b, 59, false, ROOK);
            }
            _ => {}
        }
    }

    // Update en passant target
    b.en_passant = None;
    if piece == PAWN {
        let diff = (mv.to_sq as i16 - mv.from_sq as i16).unsigned_abs();
        if diff == 16 {
            b.en_passant = Some((mv.from_sq + mv.to_sq) / 2);
        }
    }

    // Update castling rights
    if piece == KING {
        if is_white {
            b.castling_rights &= !(CASTLING_WK | CASTLING_WQ);
        } else {
            b.castling_rights &= !(CASTLING_BK | CASTLING_BQ);
        }
    }
    // Rook moves from or is captured on home square
    match mv.from_sq {
        0 => b.castling_rights &= !CASTLING_WQ,
        7 => b.castling_rights &= !CASTLING_WK,
        56 => b.castling_rights &= !CASTLING_BQ,
        63 => b.castling_rights &= !CASTLING_BK,
        _ => {}
    }
    match mv.to_sq {
        0 => b.castling_rights &= !CASTLING_WQ,
        7 => b.castling_rights &= !CASTLING_WK,
        56 => b.castling_rights &= !CASTLING_BQ,
        63 => b.castling_rights &= !CASTLING_BK,
        _ => {}
    }

    // Clocks
    if piece == PAWN || mv.flags & FLAG_CAPTURE != 0 {
        b.halfmove_clock = 0;
    } else {
        b.halfmove_clock += 1;
    }
    if !is_white {
        b.fullmove_number += 1;
    }

    b.side_to_move = !is_white;
    b
}

// ---------------------------------------------------------------------------
// Move generation
// ---------------------------------------------------------------------------

/// Generate all legal moves for the side to move.
pub fn generate_moves(board: &Board) -> Vec<Move> {
    let mut moves = Vec::with_capacity(64);
    let is_white = board.side_to_move;
    let friendly = if is_white { board.white_pieces() } else { board.black_pieces() };
    let enemy = if is_white { board.black_pieces() } else { board.white_pieces() };
    let occupied = board.occupied();

    // --- Pawns ---
    if is_white {
        gen_white_pawn_moves(board, enemy, occupied, &mut moves);
    } else {
        gen_black_pawn_moves(board, enemy, occupied, &mut moves);
    }

    // --- Knights ---
    let mut bb = if is_white { board.white_knights } else { board.black_knights };
    while bb != 0 {
        let sq = pop_lsb(&mut bb);
        let targets = KNIGHT_ATTACKS[sq as usize] & !friendly;
        add_targets(sq, targets, enemy, &mut moves);
    }

    // --- Bishops ---
    let mut bb = if is_white { board.white_bishops } else { board.black_bishops };
    while bb != 0 {
        let sq = pop_lsb(&mut bb);
        let targets = bishop_attacks(sq, occupied) & !friendly;
        add_targets(sq, targets, enemy, &mut moves);
    }

    // --- Rooks ---
    let mut bb = if is_white { board.white_rooks } else { board.black_rooks };
    while bb != 0 {
        let sq = pop_lsb(&mut bb);
        let targets = rook_attacks(sq, occupied) & !friendly;
        add_targets(sq, targets, enemy, &mut moves);
    }

    // --- Queens ---
    let mut bb = if is_white { board.white_queens } else { board.black_queens };
    while bb != 0 {
        let sq = pop_lsb(&mut bb);
        let targets = (bishop_attacks(sq, occupied) | rook_attacks(sq, occupied)) & !friendly;
        add_targets(sq, targets, enemy, &mut moves);
    }

    // --- King (normal moves) ---
    let king_bb = if is_white { board.white_kings } else { board.black_kings };
    if king_bb != 0 {
        let king_sq = king_bb.trailing_zeros() as u8;
        let targets = KING_ATTACKS[king_sq as usize] & !friendly;
        add_targets(king_sq, targets, enemy, &mut moves);

        // --- Castling ---
        gen_castling(board, is_white, occupied, &mut moves);
    }

    // Filter: keep only moves where our king is not in check afterwards
    moves
        .into_iter()
        .filter(|mv| {
            let new_board = make_move(board, mv);
            let king = if is_white { new_board.white_kings } else { new_board.black_kings };
            if king == 0 {
                return false;
            }
            let king_sq = king.trailing_zeros() as u8;
            !is_square_attacked(&new_board, king_sq, !is_white)
        })
        .collect()
}

/// Add moves from `from_sq` to every bit in `targets`.
fn add_targets(from_sq: u8, mut targets: u64, enemy: u64, moves: &mut Vec<Move>) {
    while targets != 0 {
        let to = pop_lsb(&mut targets);
        let flags = if enemy & (1u64 << to) != 0 { FLAG_CAPTURE } else { 0 };
        moves.push(Move {
            from_sq,
            to_sq: to,
            promotion: None,
            flags,
        });
    }
}

// ---------------------------------------------------------------------------
// Pawn move generation (white)
// ---------------------------------------------------------------------------

fn gen_white_pawn_moves(board: &Board, enemy: u64, occupied: u64, moves: &mut Vec<Move>) {
    let pawns = board.white_pawns;

    // Single push
    let single = (pawns << 8) & !occupied;
    add_pawn_pushes(single & !RANK_8, -8i8, moves);
    add_pawn_promotions(single & RANK_8, -8i8, moves);

    // Double push (pawns that just reached rank 3 can push again to rank 4)
    let double = ((single & RANK_3) << 8) & !occupied;
    add_pawn_pushes(double, -16i8, moves);

    // Captures north-west (file decreases)
    let nw = ((pawns & !FILE_A) << 7) & enemy;
    add_pawn_captures(nw & !RANK_8, -7i8, moves);
    add_pawn_promo_captures(nw & RANK_8, -7i8, moves);

    // Captures north-east (file increases)
    let ne = ((pawns & !FILE_H) << 9) & enemy;
    add_pawn_captures(ne & !RANK_8, -9i8, moves);
    add_pawn_promo_captures(ne & RANK_8, -9i8, moves);

    // En passant
    if let Some(ep_sq) = board.en_passant {
        let ep_file = ep_sq % 8;
        let ep_rank = ep_sq / 8;
        // Capturing pawns are on rank ep_rank-1, file ep_file ± 1
        if ep_rank > 0 {
            let src_rank = ep_rank - 1;
            if ep_file > 0 {
                let from = src_rank * 8 + (ep_file - 1);
                if pawns & (1u64 << from) != 0 {
                    moves.push(Move {
                        from_sq: from,
                        to_sq: ep_sq,
                        promotion: None,
                        flags: FLAG_CAPTURE | FLAG_EN_PASSANT,
                    });
                }
            }
            if ep_file < 7 {
                let from = src_rank * 8 + (ep_file + 1);
                if pawns & (1u64 << from) != 0 {
                    moves.push(Move {
                        from_sq: from,
                        to_sq: ep_sq,
                        promotion: None,
                        flags: FLAG_CAPTURE | FLAG_EN_PASSANT,
                    });
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Pawn move generation (black)
// ---------------------------------------------------------------------------

fn gen_black_pawn_moves(board: &Board, enemy: u64, occupied: u64, moves: &mut Vec<Move>) {
    let pawns = board.black_pawns;

    // Single push
    let single = (pawns >> 8) & !occupied;
    add_pawn_pushes(single & !RANK_1, 8i8, moves);
    add_pawn_promotions(single & RANK_1, 8i8, moves);

    // Double push (pawns that just reached rank 6 can push again to rank 5)
    let double = ((single & RANK_6) >> 8) & !occupied;
    add_pawn_pushes(double, 16i8, moves);

    // Captures south-west (file decreases)
    let sw = ((pawns & !FILE_A) >> 9) & enemy;
    add_pawn_captures(sw & !RANK_1, 9i8, moves);
    add_pawn_promo_captures(sw & RANK_1, 9i8, moves);

    // Captures south-east (file increases)
    let se = ((pawns & !FILE_H) >> 7) & enemy;
    add_pawn_captures(se & !RANK_1, 7i8, moves);
    add_pawn_promo_captures(se & RANK_1, 7i8, moves);

    // En passant
    if let Some(ep_sq) = board.en_passant {
        let ep_file = ep_sq % 8;
        let ep_rank = ep_sq / 8;
        // Capturing pawns are on rank ep_rank+1, file ep_file ± 1
        if ep_rank < 7 {
            let src_rank = ep_rank + 1;
            if ep_file > 0 {
                let from = src_rank * 8 + (ep_file - 1);
                if pawns & (1u64 << from) != 0 {
                    moves.push(Move {
                        from_sq: from,
                        to_sq: ep_sq,
                        promotion: None,
                        flags: FLAG_CAPTURE | FLAG_EN_PASSANT,
                    });
                }
            }
            if ep_file < 7 {
                let from = src_rank * 8 + (ep_file + 1);
                if pawns & (1u64 << from) != 0 {
                    moves.push(Move {
                        from_sq: from,
                        to_sq: ep_sq,
                        promotion: None,
                        flags: FLAG_CAPTURE | FLAG_EN_PASSANT,
                    });
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Pawn move helpers
// ---------------------------------------------------------------------------

/// Add quiet pawn pushes. `from_offset` is subtracted from target to get source.
fn add_pawn_pushes(mut targets: u64, from_offset: i8, moves: &mut Vec<Move>) {
    while targets != 0 {
        let to = pop_lsb(&mut targets);
        moves.push(Move {
            from_sq: (to as i8 + from_offset) as u8,
            to_sq: to,
            promotion: None,
            flags: 0,
        });
    }
}

/// Add pawn promotion pushes (4 promotions per target square).
fn add_pawn_promotions(mut targets: u64, from_offset: i8, moves: &mut Vec<Move>) {
    while targets != 0 {
        let to = pop_lsb(&mut targets);
        let from = (to as i8 + from_offset) as u8;
        for &p in &[QUEEN, ROOK, BISHOP, KNIGHT] {
            moves.push(Move {
                from_sq: from,
                to_sq: to,
                promotion: Some(p),
                flags: 0,
            });
        }
    }
}

/// Add pawn captures (non-promotion).
fn add_pawn_captures(mut targets: u64, from_offset: i8, moves: &mut Vec<Move>) {
    while targets != 0 {
        let to = pop_lsb(&mut targets);
        moves.push(Move {
            from_sq: (to as i8 + from_offset) as u8,
            to_sq: to,
            promotion: None,
            flags: FLAG_CAPTURE,
        });
    }
}

/// Add pawn promotion captures (4 promotions per target square).
fn add_pawn_promo_captures(mut targets: u64, from_offset: i8, moves: &mut Vec<Move>) {
    while targets != 0 {
        let to = pop_lsb(&mut targets);
        let from = (to as i8 + from_offset) as u8;
        for &p in &[QUEEN, ROOK, BISHOP, KNIGHT] {
            moves.push(Move {
                from_sq: from,
                to_sq: to,
                promotion: Some(p),
                flags: FLAG_CAPTURE,
            });
        }
    }
}

// ---------------------------------------------------------------------------
// Castling generation
// ---------------------------------------------------------------------------

fn gen_castling(board: &Board, is_white: bool, occupied: u64, moves: &mut Vec<Move>) {
    let opponent = !is_white;

    if is_white {
        // Kingside: e1(4) → g1(6), rook h1(7) → f1(5)
        if board.castling_rights & CASTLING_WK != 0
            && board.white_rooks & (1u64 << 7) != 0
            && occupied & ((1u64 << 5) | (1u64 << 6)) == 0
            && !is_square_attacked(board, 4, opponent)
            && !is_square_attacked(board, 5, opponent)
            && !is_square_attacked(board, 6, opponent)
        {
            moves.push(Move {
                from_sq: 4,
                to_sq: 6,
                promotion: None,
                flags: FLAG_CASTLING,
            });
        }
        // Queenside: e1(4) → c1(2), rook a1(0) → d1(3)
        if board.castling_rights & CASTLING_WQ != 0
            && board.white_rooks & (1u64 << 0) != 0
            && occupied & ((1u64 << 1) | (1u64 << 2) | (1u64 << 3)) == 0
            && !is_square_attacked(board, 4, opponent)
            && !is_square_attacked(board, 2, opponent)
            && !is_square_attacked(board, 3, opponent)
        {
            moves.push(Move {
                from_sq: 4,
                to_sq: 2,
                promotion: None,
                flags: FLAG_CASTLING,
            });
        }
    } else {
        // Kingside: e8(60) → g8(62), rook h8(63) → f8(61)
        if board.castling_rights & CASTLING_BK != 0
            && board.black_rooks & (1u64 << 63) != 0
            && occupied & ((1u64 << 61) | (1u64 << 62)) == 0
            && !is_square_attacked(board, 60, opponent)
            && !is_square_attacked(board, 61, opponent)
            && !is_square_attacked(board, 62, opponent)
        {
            moves.push(Move {
                from_sq: 60,
                to_sq: 62,
                promotion: None,
                flags: FLAG_CASTLING,
            });
        }
        // Queenside: e8(60) → c8(58), rook a8(56) → d8(59)
        if board.castling_rights & CASTLING_BQ != 0
            && board.black_rooks & (1u64 << 56) != 0
            && occupied & ((1u64 << 57) | (1u64 << 58) | (1u64 << 59)) == 0
            && !is_square_attacked(board, 60, opponent)
            && !is_square_attacked(board, 58, opponent)
            && !is_square_attacked(board, 59, opponent)
        {
            moves.push(Move {
                from_sq: 60,
                to_sq: 58,
                promotion: None,
                flags: FLAG_CASTLING,
            });
        }
    }
}

// ---------------------------------------------------------------------------
// Perft (for testing)
// ---------------------------------------------------------------------------

pub fn perft(board: &Board, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }
    let moves = generate_moves(board);
    if depth == 1 {
        return moves.len() as u64;
    }
    let mut nodes = 0u64;
    for mv in &moves {
        let new_board = make_move(board, mv);
        nodes += perft(&new_board, depth - 1);
    }
    nodes
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startpos_has_20_legal_moves() {
        let board = Board::startpos();
        let moves = generate_moves(&board);
        assert_eq!(
            moves.len(),
            20,
            "Starting position should have 20 legal moves, got {}:\n{}",
            moves.len(),
            moves.iter().map(|m| m.to_uci()).collect::<Vec<_>>().join(", ")
        );
    }

    #[test]
    fn perft_1_startpos_is_20() {
        let board = Board::startpos();
        assert_eq!(perft(&board, 1), 20);
    }

    #[test]
    fn perft_2_startpos() {
        let board = Board::startpos();
        assert_eq!(perft(&board, 2), 400);
    }

    #[test]
    fn perft_3_startpos() {
        let board = Board::startpos();
        assert_eq!(perft(&board, 3), 8902);
    }

    #[test]
    fn no_moves_in_checkmate() {
        // Scholar's mate final position: black is checkmated
        let board =
            Board::from_fen("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")
                .unwrap();
        let moves = generate_moves(&board);
        assert_eq!(moves.len(), 0, "Checkmate should have 0 legal moves");
    }

    #[test]
    fn king_cannot_move_into_check() {
        // King on e1, black rook on a2 — king can't go to d1 or d2 or e2 (rook covers rank 2 + file a)
        let board =
            Board::from_fen("8/8/8/8/8/8/r7/4K3 w - - 0 1").unwrap();
        let moves = generate_moves(&board);
        // King on e1 has 5 potential squares: d1, d2, e2, f2, f1
        // Rook on a2 attacks all of rank 2 → d2, e2, f2 are illegal
        // d1, f1 remain legal
        for mv in &moves {
            assert!(
                mv.to_sq != 11 && mv.to_sq != 12 && mv.to_sq != 13,
                "King should not be able to move to rank 2 (sq {})",
                mv.to_sq
            );
        }
    }

    #[test]
    fn en_passant_generation() {
        // White pawn on e5, black just played d7-d5, en passant target d6
        let board =
            Board::from_fen("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
                .unwrap();
        let moves = generate_moves(&board);
        let ep_moves: Vec<_> = moves
            .iter()
            .filter(|m| m.flags & FLAG_EN_PASSANT != 0)
            .collect();
        assert_eq!(ep_moves.len(), 1, "Should have exactly 1 en passant move");
        assert_eq!(ep_moves[0].to_uci(), "e5d6");
    }

    #[test]
    fn castling_both_sides() {
        let board =
            Board::from_fen("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1").unwrap();
        let moves = generate_moves(&board);
        let castle_moves: Vec<_> = moves
            .iter()
            .filter(|m| m.flags & FLAG_CASTLING != 0)
            .collect();
        assert_eq!(castle_moves.len(), 2, "Should have 2 castling moves (KQ)");
    }

    #[test]
    fn promotion_generates_four_moves() {
        // White pawn on e7, empty e8
        let board = Board::from_fen("8/4P3/8/8/8/8/8/4K2k w - - 0 1").unwrap();
        let moves = generate_moves(&board);
        let promo_moves: Vec<_> = moves.iter().filter(|m| m.promotion.is_some()).collect();
        assert_eq!(
            promo_moves.len(),
            4,
            "Pawn on 7th rank should generate 4 promotion moves"
        );
    }

    #[test]
    fn knight_attack_table_corners() {
        // a1 knight has 2 attacks
        assert_eq!(KNIGHT_ATTACKS[0].count_ones(), 2);
        // h8 knight has 2 attacks
        assert_eq!(KNIGHT_ATTACKS[63].count_ones(), 2);
        // d4 knight has 8 attacks
        assert_eq!(KNIGHT_ATTACKS[27].count_ones(), 8);
    }

    #[test]
    fn king_attack_table_corners() {
        // a1 king has 3 moves
        assert_eq!(KING_ATTACKS[0].count_ones(), 3);
        // e4 king has 8 moves
        assert_eq!(KING_ATTACKS[28].count_ones(), 8);
    }

    #[test]
    fn is_in_check_detects_check() {
        // Black king on e8, white rook on e1 — king in check
        let board = Board::from_fen("4k3/8/8/8/8/8/8/4R2K b - - 0 1").unwrap();
        assert!(is_in_check(&board));
    }

    #[test]
    fn startpos_not_in_check() {
        assert!(!is_in_check(&Board::startpos()));
    }
}
