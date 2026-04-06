use crate::board::Board;
use std::fs::File;
use std::io::{Read as IoRead, Write as IoWrite};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// 768 input features: 2 colors × 6 piece types × 64 squares
pub const INPUT_SIZE: usize = 768;
/// Hidden layer width
pub const HIDDEN_SIZE: usize = 256;
/// Quantization parameter for activations (CReLU clamp range)
pub const QA: i32 = 255;
/// Quantization parameter for output weights
pub const QB: i32 = 64;
/// Centipawn scaling factor
pub const SCALE: i32 = 400;

// Piece types (must match movegen constants)
const PAWN: u8 = 0;
const KNIGHT: u8 = 1;
const BISHOP: u8 = 2;
const ROOK: u8 = 3;
const QUEEN: u8 = 4;
const KING: u8 = 5;

// ---------------------------------------------------------------------------
// Network weights
// ---------------------------------------------------------------------------

/// NNUE network: 768 → 256×2 (perspectives) → 1
pub struct Network {
    /// First-layer weights: [INPUT_SIZE][HIDDEN_SIZE], stored as i16
    pub ft_weights: Box<[[i16; HIDDEN_SIZE]; INPUT_SIZE]>,
    /// First-layer bias: [HIDDEN_SIZE]
    pub ft_bias: [i16; HIDDEN_SIZE],
    /// Output weights: [HIDDEN_SIZE * 2] (STM half ++ NSTM half)
    pub out_weights: [i16; HIDDEN_SIZE * 2],
    /// Output bias
    pub out_bias: i16,
}

// ---------------------------------------------------------------------------
// Accumulator (incrementally updated hidden layer)
// ---------------------------------------------------------------------------

/// Holds the pre-activation values for white and black perspectives.
#[derive(Clone)]
pub struct Accumulator {
    pub white: [i32; HIDDEN_SIZE],
    pub black: [i32; HIDDEN_SIZE],
}

// ---------------------------------------------------------------------------
// Feature index calculation
// ---------------------------------------------------------------------------

/// Compute the input feature index for a piece from a given perspective.
///
/// Layout: `color_idx * 384 + piece_type * 64 + sq`
///   - color_idx: 0 if piece is same color as perspective, 1 if opponent
///   - sq: for white perspective use sq directly, for black perspective mirror (sq ^ 56)
#[inline]
pub fn feature_index(perspective: bool, sq: u8, piece_type: u8, piece_color: bool) -> usize {
    let mirrored_sq = if perspective { sq } else { sq ^ 56 };
    let color_idx = if piece_color == perspective { 0 } else { 1 };
    color_idx * 6 * 64 + piece_type as usize * 64 + mirrored_sq as usize
}

// ---------------------------------------------------------------------------
// Accumulator methods
// ---------------------------------------------------------------------------

impl Accumulator {
    /// Initialize both perspectives from the network's first-layer bias.
    pub fn new(network: &Network) -> Self {
        let mut acc = Accumulator {
            white: [0i32; HIDDEN_SIZE],
            black: [0i32; HIDDEN_SIZE],
        };
        for i in 0..HIDDEN_SIZE {
            acc.white[i] = network.ft_bias[i] as i32;
            acc.black[i] = network.ft_bias[i] as i32;
        }
        acc
    }

    /// Add a feature (piece placed on the board) to both perspectives.
    pub fn add_feature(&mut self, network: &Network, sq: u8, piece_type: u8, piece_color: bool) {
        let w_idx = feature_index(true, sq, piece_type, piece_color);
        let b_idx = feature_index(false, sq, piece_type, piece_color);
        for i in 0..HIDDEN_SIZE {
            self.white[i] += network.ft_weights[w_idx][i] as i32;
            self.black[i] += network.ft_weights[b_idx][i] as i32;
        }
    }

    /// Remove a feature (piece removed from the board) from both perspectives.
    pub fn remove_feature(&mut self, network: &Network, sq: u8, piece_type: u8, piece_color: bool) {
        let w_idx = feature_index(true, sq, piece_type, piece_color);
        let b_idx = feature_index(false, sq, piece_type, piece_color);
        for i in 0..HIDDEN_SIZE {
            self.white[i] -= network.ft_weights[w_idx][i] as i32;
            self.black[i] -= network.ft_weights[b_idx][i] as i32;
        }
    }

    /// Build an accumulator from scratch by scanning all pieces on the board.
    pub fn from_board(network: &Network, board: &Board) -> Self {
        let mut acc = Accumulator::new(network);

        // (bitboard, piece_type, is_white)
        let pieces: [(u64, u8, bool); 12] = [
            (board.white_pawns,   PAWN,   true),
            (board.white_knights, KNIGHT, true),
            (board.white_bishops, BISHOP, true),
            (board.white_rooks,   ROOK,   true),
            (board.white_queens,  QUEEN,  true),
            (board.white_kings,   KING,   true),
            (board.black_pawns,   PAWN,   false),
            (board.black_knights, KNIGHT, false),
            (board.black_bishops, BISHOP, false),
            (board.black_rooks,   ROOK,   false),
            (board.black_queens,  QUEEN,  false),
            (board.black_kings,   KING,   false),
        ];

        for &(mut bb, piece_type, is_white) in &pieces {
            while bb != 0 {
                let sq = bb.trailing_zeros() as u8;
                bb &= bb - 1;
                acc.add_feature(network, sq, piece_type, is_white);
            }
        }

        acc
    }
}

// ---------------------------------------------------------------------------
// Network evaluation
// ---------------------------------------------------------------------------

impl Network {
    /// Evaluate the position from the accumulator.
    ///
    /// The output layer takes `[CReLU(STM_acc), CReLU(NSTM_acc)]` (512 values)
    /// and computes a dot product with `out_weights`, adds `out_bias`,
    /// then scales to centipawns.
    pub fn evaluate(&self, acc: &Accumulator, side_to_move: bool) -> i32 {
        let (stm, nstm) = if side_to_move {
            (&acc.white, &acc.black)
        } else {
            (&acc.black, &acc.white)
        };

        let mut output = self.out_bias as i32;

        // STM half (first HIDDEN_SIZE weights)
        for i in 0..HIDDEN_SIZE {
            let clamped = stm[i].clamp(0, QA);
            output += clamped * self.out_weights[i] as i32;
        }

        // NSTM half (second HIDDEN_SIZE weights)
        for i in 0..HIDDEN_SIZE {
            let clamped = nstm[i].clamp(0, QA);
            output += clamped * self.out_weights[HIDDEN_SIZE + i] as i32;
        }

        // Scale: model outputs centipawns directly, just undo quantization
        output / (QA * QB)
    }

    /// Create a network with small random weights (for testing only).
    ///
    /// Uses a simple LCG PRNG seeded deterministically so tests are reproducible.
    pub fn from_random() -> Self {
        let mut rng_state: u64 = 0xDEAD_BEEF_CAFE_1234;

        let next_i16 = |state: &mut u64| -> i16 {
            // LCG: state = state * 6364136223846793005 + 1442695040888963407
            *state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1_442_695_040_888_963_407);
            // Extract bits 16..31 and map to small range [-16, 15]
            ((*state >> 16) as i16) % 16
        };

        let mut ft_weights = Box::new([[0i16; HIDDEN_SIZE]; INPUT_SIZE]);
        for input in 0..INPUT_SIZE {
            for hidden in 0..HIDDEN_SIZE {
                ft_weights[input][hidden] = next_i16(&mut rng_state);
            }
        }

        let mut ft_bias = [0i16; HIDDEN_SIZE];
        for i in 0..HIDDEN_SIZE {
            ft_bias[i] = next_i16(&mut rng_state);
        }

        let mut out_weights = [0i16; HIDDEN_SIZE * 2];
        for i in 0..HIDDEN_SIZE * 2 {
            out_weights[i] = next_i16(&mut rng_state);
        }

        let out_bias = next_i16(&mut rng_state);

        Network { ft_weights, ft_bias, out_weights, out_bias }
    }

    // -----------------------------------------------------------------------
    // Binary file I/O
    //
    // Format:
    //   Magic:   [0x4E, 0x4E, 0x55, 0x45]  ("NNUE")
    //   Version: u32 little-endian = 1
    //   Data:    all i16 values in little-endian order:
    //            ft_weights (768*256), ft_bias (256),
    //            out_weights (512), out_bias (1)
    // -----------------------------------------------------------------------

    const MAGIC: [u8; 4] = [0x4E, 0x4E, 0x55, 0x45];
    const VERSION: u32 = 1;

    /// Write network weights to a binary file.
    pub fn to_file(&self, path: &str) -> Result<(), String> {
        let mut f = File::create(path).map_err(|e| format!("create {}: {}", path, e))?;

        f.write_all(&Self::MAGIC).map_err(|e| e.to_string())?;
        f.write_all(&Self::VERSION.to_le_bytes()).map_err(|e| e.to_string())?;

        // ft_weights: INPUT_SIZE * HIDDEN_SIZE i16 values
        for row in self.ft_weights.iter() {
            for &val in row.iter() {
                f.write_all(&val.to_le_bytes()).map_err(|e| e.to_string())?;
            }
        }
        // ft_bias
        for &val in &self.ft_bias {
            f.write_all(&val.to_le_bytes()).map_err(|e| e.to_string())?;
        }
        // out_weights
        for &val in &self.out_weights {
            f.write_all(&val.to_le_bytes()).map_err(|e| e.to_string())?;
        }
        // out_bias
        f.write_all(&self.out_bias.to_le_bytes()).map_err(|e| e.to_string())?;

        Ok(())
    }

    /// Load network weights from a binary file.
    pub fn from_file(path: &str) -> Result<Self, String> {
        let mut f = File::open(path).map_err(|e| format!("open {}: {}", path, e))?;

        // Magic
        let mut magic = [0u8; 4];
        f.read_exact(&mut magic).map_err(|e| format!("read magic: {}", e))?;
        if magic != Self::MAGIC {
            return Err(format!("bad magic: {:?}", magic));
        }

        // Version
        let mut ver_bytes = [0u8; 4];
        f.read_exact(&mut ver_bytes).map_err(|e| format!("read version: {}", e))?;
        let version = u32::from_le_bytes(ver_bytes);
        if version != Self::VERSION {
            return Err(format!("unsupported version {}", version));
        }

        let read_i16 = |file: &mut File| -> Result<i16, String> {
            let mut buf = [0u8; 2];
            file.read_exact(&mut buf).map_err(|e| format!("read i16: {}", e))?;
            Ok(i16::from_le_bytes(buf))
        };

        // ft_weights
        let mut ft_weights = Box::new([[0i16; HIDDEN_SIZE]; INPUT_SIZE]);
        for row in ft_weights.iter_mut() {
            for val in row.iter_mut() {
                *val = read_i16(&mut f)?;
            }
        }

        // ft_bias
        let mut ft_bias = [0i16; HIDDEN_SIZE];
        for val in ft_bias.iter_mut() {
            *val = read_i16(&mut f)?;
        }

        // out_weights
        let mut out_weights = [0i16; HIDDEN_SIZE * 2];
        for val in out_weights.iter_mut() {
            *val = read_i16(&mut f)?;
        }

        // out_bias
        let out_bias = read_i16(&mut f)?;

        Ok(Network { ft_weights, ft_bias, out_weights, out_bias })
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn feature_index_in_range() {
        // Every valid (perspective, sq, piece_type, piece_color) gives index < 768
        for &perspective in &[true, false] {
            for sq in 0..64u8 {
                for piece_type in 0..6u8 {
                    for &piece_color in &[true, false] {
                        let idx = feature_index(perspective, sq, piece_type, piece_color);
                        assert!(
                            idx < INPUT_SIZE,
                            "feature_index({}, {}, {}, {}) = {} >= {}",
                            perspective, sq, piece_type, piece_color, idx, INPUT_SIZE
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn accumulator_from_startpos_no_panic() {
        let net = Network::from_random();
        let board = Board::startpos();
        let _acc = Accumulator::from_board(&net, &board);
    }

    #[test]
    fn evaluate_startpos_reasonable_range() {
        let net = Network::from_random();
        let board = Board::startpos();
        let acc = Accumulator::from_board(&net, &board);
        let score = net.evaluate(&acc, board.side_to_move);
        assert!(
            score > -10_000 && score < 10_000,
            "Startpos eval with random weights should be in [-10000, 10000], got {}",
            score
        );
    }

    #[test]
    fn evaluate_flips_perspective() {
        let net = Network::from_random();
        let board = Board::startpos();
        let acc = Accumulator::from_board(&net, &board);
        let white_eval = net.evaluate(&acc, true);
        let black_eval = net.evaluate(&acc, false);
        // With symmetric position, flipping perspective may differ due to
        // different out_weights for STM vs NSTM halves. Just check both are valid.
        assert!(white_eval > -10_000 && white_eval < 10_000);
        assert!(black_eval > -10_000 && black_eval < 10_000);
    }

    #[test]
    fn add_remove_feature_roundtrip() {
        let net = Network::from_random();
        let mut acc = Accumulator::new(&net);
        let original = acc.clone();

        // Add then remove a white pawn on e4
        acc.add_feature(&net, 28, PAWN, true);
        acc.remove_feature(&net, 28, PAWN, true);

        // Should be back to original (bias-only) state
        for i in 0..HIDDEN_SIZE {
            assert_eq!(acc.white[i], original.white[i], "white[{}] mismatch", i);
            assert_eq!(acc.black[i], original.black[i], "black[{}] mismatch", i);
        }
    }

    #[test]
    fn file_roundtrip() {
        let net = Network::from_random();
        let path = std::env::temp_dir().join("pyro_test_nnue.bin");
        let path_str = path.to_str().unwrap();

        net.to_file(path_str).expect("write failed");
        let loaded = Network::from_file(path_str).expect("read failed");

        assert_eq!(net.out_bias, loaded.out_bias, "out_bias mismatch");
        assert_eq!(net.ft_bias, loaded.ft_bias, "ft_bias mismatch");
        assert_eq!(net.out_weights, loaded.out_weights, "out_weights mismatch");
        // Spot-check ft_weights
        for i in [0, 100, 400, 767] {
            assert_eq!(net.ft_weights[i], loaded.ft_weights[i], "ft_weights[{}] mismatch", i);
        }

        std::fs::remove_file(path_str).ok();
    }

    #[test]
    fn feature_index_white_vs_black_perspective() {
        // A white pawn on e2 from white's perspective
        let w_idx = feature_index(true, 12, PAWN, true);
        // Same piece from black's perspective: square mirrors, color flips
        let b_idx = feature_index(false, 12, PAWN, true);

        // White perspective: friendly pawn on e2 (sq 12)
        // index = 0 * 384 + 0 * 64 + 12 = 12
        assert_eq!(w_idx, 12);

        // Black perspective: opponent pawn, mirrored sq = 12 ^ 56 = 52
        // index = 1 * 384 + 0 * 64 + 52 = 436
        assert_eq!(b_idx, 436);
    }
}
