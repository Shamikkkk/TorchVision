/// Bitboard-based chess board representation.
///
/// Each piece type per color is stored as a single u64 where bit index 0 = a1,
/// bit index 7 = h1, bit index 56 = a8, bit index 63 = h8.
/// Square mapping: index = rank * 8 + file  (file: a=0 .. h=7, rank: 1=0 .. 8=7)

#[derive(Clone, Debug)]
pub struct Board {
    // White pieces
    pub white_pawns: u64,
    pub white_knights: u64,
    pub white_bishops: u64,
    pub white_rooks: u64,
    pub white_queens: u64,
    pub white_kings: u64,

    // Black pieces
    pub black_pawns: u64,
    pub black_knights: u64,
    pub black_bishops: u64,
    pub black_rooks: u64,
    pub black_queens: u64,
    pub black_kings: u64,

    /// true = white to move, false = black to move
    pub side_to_move: bool,

    /// Castling rights packed into lower 4 bits:
    /// bit 0 = white kingside  (K)
    /// bit 1 = white queenside (Q)
    /// bit 2 = black kingside  (k)
    /// bit 3 = black queenside (q)
    pub castling_rights: u8,

    /// En passant target square index (0..63), or None
    pub en_passant: Option<u8>,

    pub halfmove_clock: u32,
    pub fullmove_number: u32,
}

pub const CASTLING_WK: u8 = 0b0001;
pub const CASTLING_WQ: u8 = 0b0010;
pub const CASTLING_BK: u8 = 0b0100;
pub const CASTLING_BQ: u8 = 0b1000;

impl Board {
    /// Returns the standard starting position.
    pub fn startpos() -> Self {
        Board {
            white_pawns:   0x0000_0000_0000_FF00,
            white_knights: 0x0000_0000_0000_0042,
            white_bishops: 0x0000_0000_0000_0024,
            white_rooks:   0x0000_0000_0000_0081,
            white_queens:  0x0000_0000_0000_0008,
            white_kings:   0x0000_0000_0000_0010,

            black_pawns:   0x00FF_0000_0000_0000,
            black_knights: 0x4200_0000_0000_0000,
            black_bishops: 0x2400_0000_0000_0000,
            black_rooks:   0x8100_0000_0000_0000,
            black_queens:  0x0800_0000_0000_0000,
            black_kings:   0x1000_0000_0000_0000,

            side_to_move: true,
            castling_rights: CASTLING_WK | CASTLING_WQ | CASTLING_BK | CASTLING_BQ,
            en_passant: None,
            halfmove_clock: 0,
            fullmove_number: 1,
        }
    }

    /// Parse a FEN string into a Board.
    ///
    /// Example: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    pub fn from_fen(fen: &str) -> Result<Self, String> {
        let parts: Vec<&str> = fen.split_whitespace().collect();
        if parts.len() < 4 {
            return Err(format!("FEN needs at least 4 fields, got {}", parts.len()));
        }

        let mut board = Board {
            white_pawns: 0, white_knights: 0, white_bishops: 0,
            white_rooks: 0, white_queens: 0, white_kings: 0,
            black_pawns: 0, black_knights: 0, black_bishops: 0,
            black_rooks: 0, black_queens: 0, black_kings: 0,
            side_to_move: true,
            castling_rights: 0,
            en_passant: None,
            halfmove_clock: 0,
            fullmove_number: 1,
        };

        // --- Field 1: piece placement (rank 8 down to rank 1) ---
        let ranks: Vec<&str> = parts[0].split('/').collect();
        if ranks.len() != 8 {
            return Err(format!("FEN piece placement needs 8 ranks, got {}", ranks.len()));
        }

        for (rank_idx, rank_str) in ranks.iter().enumerate() {
            let rank = 7 - rank_idx as u8; // FEN starts at rank 8
            let mut file: u8 = 0;
            for ch in rank_str.chars() {
                if file > 7 {
                    return Err(format!("Too many squares on rank {}", 8 - rank_idx));
                }
                if let Some(skip) = ch.to_digit(10) {
                    file += skip as u8;
                } else {
                    let sq = rank * 8 + file;
                    let bit = 1u64 << sq;
                    match ch {
                        'P' => board.white_pawns |= bit,
                        'N' => board.white_knights |= bit,
                        'B' => board.white_bishops |= bit,
                        'R' => board.white_rooks |= bit,
                        'Q' => board.white_queens |= bit,
                        'K' => board.white_kings |= bit,
                        'p' => board.black_pawns |= bit,
                        'n' => board.black_knights |= bit,
                        'b' => board.black_bishops |= bit,
                        'r' => board.black_rooks |= bit,
                        'q' => board.black_queens |= bit,
                        'k' => board.black_kings |= bit,
                        _ => return Err(format!("Unknown piece char '{}'", ch)),
                    }
                    file += 1;
                }
            }
        }

        // --- Field 2: side to move ---
        board.side_to_move = match parts[1] {
            "w" => true,
            "b" => false,
            other => return Err(format!("Invalid side to move '{}'", other)),
        };

        // --- Field 3: castling rights ---
        if parts[2] != "-" {
            for ch in parts[2].chars() {
                match ch {
                    'K' => board.castling_rights |= CASTLING_WK,
                    'Q' => board.castling_rights |= CASTLING_WQ,
                    'k' => board.castling_rights |= CASTLING_BK,
                    'q' => board.castling_rights |= CASTLING_BQ,
                    _ => return Err(format!("Invalid castling char '{}'", ch)),
                }
            }
        }

        // --- Field 4: en passant target square ---
        if parts[3] != "-" {
            let ep = parts[3].as_bytes();
            if ep.len() != 2 {
                return Err(format!("Invalid en passant square '{}'", parts[3]));
            }
            let file = ep[0].wrapping_sub(b'a');
            let rank = ep[1].wrapping_sub(b'1');
            if file > 7 || rank > 7 {
                return Err(format!("Invalid en passant square '{}'", parts[3]));
            }
            board.en_passant = Some(rank * 8 + file);
        }

        // --- Field 5: halfmove clock (optional) ---
        if parts.len() > 4 {
            board.halfmove_clock = parts[4]
                .parse()
                .map_err(|_| format!("Invalid halfmove clock '{}'", parts[4]))?;
        }

        // --- Field 6: fullmove number (optional) ---
        if parts.len() > 5 {
            board.fullmove_number = parts[5]
                .parse()
                .map_err(|_| format!("Invalid fullmove number '{}'", parts[5]))?;
        }

        Ok(board)
    }

    /// Combined bitboard of all white pieces.
    pub fn white_pieces(&self) -> u64 {
        self.white_pawns | self.white_knights | self.white_bishops
            | self.white_rooks | self.white_queens | self.white_kings
    }

    /// Combined bitboard of all black pieces.
    pub fn black_pieces(&self) -> u64 {
        self.black_pawns | self.black_knights | self.black_bishops
            | self.black_rooks | self.black_queens | self.black_kings
    }

    /// Combined bitboard of all occupied squares.
    pub fn occupied(&self) -> u64 {
        self.white_pieces() | self.black_pieces()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startpos_piece_counts() {
        let b = Board::startpos();
        assert_eq!(b.white_pawns.count_ones(), 8);
        assert_eq!(b.white_knights.count_ones(), 2);
        assert_eq!(b.white_bishops.count_ones(), 2);
        assert_eq!(b.white_rooks.count_ones(), 2);
        assert_eq!(b.white_queens.count_ones(), 1);
        assert_eq!(b.white_kings.count_ones(), 1);
        assert_eq!(b.black_pawns.count_ones(), 8);
        assert_eq!(b.black_knights.count_ones(), 2);
        assert_eq!(b.black_bishops.count_ones(), 2);
        assert_eq!(b.black_rooks.count_ones(), 2);
        assert_eq!(b.black_queens.count_ones(), 1);
        assert_eq!(b.black_kings.count_ones(), 1);
        assert_eq!(b.occupied().count_ones(), 32);
        assert!(b.side_to_move);
        assert_eq!(b.castling_rights, 0b1111);
        assert_eq!(b.en_passant, None);
    }

    #[test]
    fn fen_startpos_matches() {
        let fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
        let from_fen = Board::from_fen(fen).unwrap();
        let startpos = Board::startpos();
        assert_eq!(from_fen.white_pawns, startpos.white_pawns);
        assert_eq!(from_fen.black_kings, startpos.black_kings);
        assert_eq!(from_fen.occupied(), startpos.occupied());
        assert_eq!(from_fen.castling_rights, startpos.castling_rights);
    }

    #[test]
    fn fen_with_en_passant() {
        let fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1";
        let b = Board::from_fen(fen).unwrap();
        assert!(!b.side_to_move);
        // e3 = file 4, rank 2 → index 20
        assert_eq!(b.en_passant, Some(20));
    }

    #[test]
    fn fen_partial_castling() {
        let fen = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w Kq - 0 1";
        let b = Board::from_fen(fen).unwrap();
        assert_eq!(b.castling_rights, CASTLING_WK | CASTLING_BQ);
    }

    #[test]
    fn fen_no_castling() {
        let fen = "8/8/8/8/8/8/8/8 w - - 0 1";
        let b = Board::from_fen(fen).unwrap();
        assert_eq!(b.castling_rights, 0);
        assert_eq!(b.occupied(), 0);
    }
}
