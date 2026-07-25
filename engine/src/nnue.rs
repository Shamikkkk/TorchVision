use crate::board::Board;
use std::fs::File;
use std::io::{Read as IoRead, Write as IoWrite};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// 768 input features: 2 colors × 6 piece types × 64 squares
pub const INPUT_SIZE: usize = 768;
/// Hidden layer width
pub const HIDDEN_SIZE: usize = 512;
/// Quantization parameter for activations (SCReLU clamp range)
pub const QA: i32 = 255;
/// Quantization parameter for output weights
pub const QB: i32 = 64;
/// Centipawn scaling factor — must equal eval_scale in the champion trainer
pub const SCALE: i32 = 400;

// ---------------------------------------------------------------------------
// Quantized SCReLU-512 inference contract
//
// Sources:
//   HIDDEN_SIZE = 512:
//     backend/scripts/bullet_port/pyro_v2_screlu512.rs
//   QA = 255, QB = 64, SCALE = 400:
//     that trainer and bullet/examples/simple.rs
//   Serialization multipliers:
//     l0w/l0b × QA, l1w × QB, l1b × (QA·QB), all rounded to i16 by
//     SavedFormat in the champion trainer.
//
// For each accumulator element:
//   q   = clamp(accumulator, 0, QA)
//   sum = Σ (q² · l1_weight)       // i64; SCReLU squares the clipped value
//   sum = sum / QA                 // integer division, truncating toward zero
//   sum = sum + l1_bias
//   cp  = sum · SCALE / (QA · QB)  // integer division, truncating toward zero
//
// Scale proof:
//   q²·l1_weight has scale QA²·QB. Dividing by QA yields QA·QB, which
//   matches the saved l1 bias scale exactly. The final QA·QB division then
//   restores the trainer's float output before multiplying by eval SCALE.
//
// IMPORTANT: the /QA division MUST remain separate and before the bias add.
// Merging it algebraically with the final SCALE division changes integer
// truncation, especially for negative sums, and is not trainer-equivalent.
// ---------------------------------------------------------------------------

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

/// NNUE network: 768 → 512×2 (perspectives) → 1 with SCReLU activation.
pub struct Network {
    /// First-layer weights: [INPUT_SIZE][HIDDEN_SIZE], stored as i16
    pub ft_weights: Box<[[i16; HIDDEN_SIZE]]>,
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
    /// The output layer takes `[SCReLU(STM_acc), SCReLU(NSTM_acc)]` (1024
    /// values) and applies the exact two-stage integer normalization documented
    /// in the inference contract above.
    pub fn evaluate(&self, acc: &Accumulator, side_to_move: bool) -> i32 {
        let (stm, nstm) = if side_to_move {
            (&acc.white, &acc.black)
        } else {
            (&acc.black, &acc.white)
        };

        let mut activation_sum = 0i64;

        // STM half (first HIDDEN_SIZE weights)
        for i in 0..HIDDEN_SIZE {
            activation_sum += screlu_square(stm[i]) * self.out_weights[i] as i64;
        }

        // NSTM half (second HIDDEN_SIZE weights)
        for i in 0..HIDDEN_SIZE {
            activation_sum +=
                screlu_square(nstm[i]) * self.out_weights[HIDDEN_SIZE + i] as i64;
        }

        // Keep these as two distinct integer divisions. Rust signed integer
        // division truncates toward zero, which the Python reference mirrors.
        let normalized = activation_sum / QA as i64;
        let biased = normalized + self.out_bias as i64;
        (biased * SCALE as i64 / (QA as i64 * QB as i64)) as i32
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

        let mut ft_weights = vec![[0i16; HIDDEN_SIZE]; INPUT_SIZE].into_boxed_slice();
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
    // Format v2 (32-byte activation-aware header):
    //   Magic:       [0x4E, 0x4E, 0x55, 0x45] ("NNUE")
    //   Version:     u32 LE = 2
    //   Activation:  u32 LE = 2 (SCReLU)
    //   Input size:  u32 LE = 768
    //   Hidden size: u32 LE = 512
    //   QA:          u32 LE = 255
    //   QB:          u32 LE = 64
    //   SCALE:       u32 LE = 400
    //   Data: all i16 values in little-endian order:
    //         ft_weights (768*512), ft_bias (512),
    //         out_weights (1024), out_bias (1)
    //
    // Version 1 was implicitly CReLU-256 and had only an 8-byte header. This
    // binary rejects it. Explicit architecture fields make width, activation,
    // and quantization mismatches fail closed rather than mis-evaluate.
    // -----------------------------------------------------------------------

    const MAGIC: [u8; 4] = [0x4E, 0x4E, 0x55, 0x45];
    const VERSION: u32 = 2;
    const ACTIVATION_SCRELU: u32 = 2;
    const HEADER_BYTES: u64 = 32;

    fn payload_bytes() -> u64 {
        ((INPUT_SIZE * HIDDEN_SIZE + HIDDEN_SIZE + HIDDEN_SIZE * 2 + 1)
            * std::mem::size_of::<i16>()) as u64
    }

    /// Write network weights to a binary file.
    pub fn to_file(&self, path: &str) -> Result<(), String> {
        let mut f = File::create(path).map_err(|e| format!("create {}: {}", path, e))?;

        f.write_all(&Self::MAGIC).map_err(|e| e.to_string())?;
        f.write_all(&Self::VERSION.to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&Self::ACTIVATION_SCRELU.to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&(INPUT_SIZE as u32).to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&(HIDDEN_SIZE as u32).to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&(QA as u32).to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&(QB as u32).to_le_bytes()).map_err(|e| e.to_string())?;
        f.write_all(&(SCALE as u32).to_le_bytes()).map_err(|e| e.to_string())?;

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

        let read_u32 = |file: &mut File, field: &str| -> Result<u32, String> {
            let mut buf = [0u8; 4];
            file.read_exact(&mut buf).map_err(|e| format!("read {}: {}", field, e))?;
            Ok(u32::from_le_bytes(buf))
        };

        // Architecture-aware v2 header. Every mismatch is fatal.
        let version = read_u32(&mut f, "version")?;
        if version != Self::VERSION {
            return Err(format!(
                "unsupported NNUE version {} (expected {}: SCReLU-512)",
                version,
                Self::VERSION
            ));
        }
        let activation = read_u32(&mut f, "activation")?;
        if activation != Self::ACTIVATION_SCRELU {
            return Err(format!(
                "activation mismatch: header {} (expected {} = SCReLU)",
                activation,
                Self::ACTIVATION_SCRELU
            ));
        }
        let input_size = read_u32(&mut f, "input size")?;
        if input_size != INPUT_SIZE as u32 {
            return Err(format!(
                "input-size mismatch: header {} (expected {})",
                input_size, INPUT_SIZE
            ));
        }
        let hidden_size = read_u32(&mut f, "hidden size")?;
        if hidden_size != HIDDEN_SIZE as u32 {
            return Err(format!(
                "hidden-size mismatch: header {} (expected {})",
                hidden_size, HIDDEN_SIZE
            ));
        }
        let qa = read_u32(&mut f, "QA")?;
        let qb = read_u32(&mut f, "QB")?;
        let scale = read_u32(&mut f, "SCALE")?;
        if qa != QA as u32 || qb != QB as u32 || scale != SCALE as u32 {
            return Err(format!(
                "quantization mismatch: header QA/QB/SCALE={}/{}/{} \
                 (expected {}/{}/{})",
                qa, qb, scale, QA, QB, SCALE
            ));
        }

        let actual_bytes = f
            .metadata()
            .map_err(|e| format!("read metadata: {}", e))?
            .len();
        let expected_bytes = Self::HEADER_BYTES + Self::payload_bytes();
        if actual_bytes != expected_bytes {
            return Err(format!(
                "NNUE file-size mismatch: {} bytes (expected {} for SCReLU-512)",
                actual_bytes, expected_bytes
            ));
        }

        let read_i16 = |file: &mut File| -> Result<i16, String> {
            let mut buf = [0u8; 2];
            file.read_exact(&mut buf).map_err(|e| format!("read i16: {}", e))?;
            Ok(i16::from_le_bytes(buf))
        };

        // ft_weights
        let mut ft_weights = vec![[0i16; HIDDEN_SIZE]; INPUT_SIZE].into_boxed_slice();
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

#[inline]
fn screlu_square(value: i32) -> i64 {
    let q = value.clamp(0, QA) as i64;
    q * q
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
            score > -100_000 && score < 100_000,
            "Startpos eval with random weights should be in [-100000, 100000], got {}",
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
        assert!(white_eval > -100_000 && white_eval < 100_000);
        assert!(black_eval > -100_000 && black_eval < 100_000);
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
    fn screlu_boundary_values_exact() {
        let cases = [
            (-100_000, 0i64),
            (-1, 0),
            (0, 0),
            (1, 1),
            (QA - 1, (QA as i64 - 1).pow(2)),
            (QA, (QA as i64).pow(2)),
            (QA + 1, (QA as i64).pow(2)),
            (100_000, (QA as i64).pow(2)),
        ];

        for (input, expected) in cases {
            assert_eq!(
                screlu_square(input),
                expected,
                "SCReLU boundary mismatch at accumulator {}",
                input
            );
        }
    }

    #[test]
    fn evaluation_preserves_two_division_order() {
        let mut net = Network::from_random();
        for weight in net.out_weights.iter_mut() {
            *weight = 0;
        }
        // A deliberately negative activation sum where moving /QA after the
        // bias add would change truncation.
        net.out_weights[0] = -1;
        net.out_bias = 205;

        let mut acc = Accumulator {
            white: [0; HIDDEN_SIZE],
            black: [0; HIDDEN_SIZE],
        };
        acc.white[0] = 17;

        let activation_sum = -(17i64 * 17);
        let normalized = activation_sum / QA as i64;
        let biased = normalized + 205;
        let expected = (biased * SCALE as i64 / (QA as i64 * QB as i64)) as i32;
        let merged = ((activation_sum + 205 * QA as i64) * SCALE as i64
            / (QA as i64 * QA as i64 * QB as i64)) as i32;

        assert_ne!(expected, merged, "test vector must detect merged divisions");
        assert_eq!(expected, 5);
        assert_eq!(merged, 4);
        assert_eq!(net.evaluate(&acc, true), expected);
    }

    fn write_header_only(path: &str, version: u32, activation: u32, hidden: u32) {
        let mut f = File::create(path).unwrap();
        f.write_all(&Network::MAGIC).unwrap();
        for value in [
            version,
            activation,
            INPUT_SIZE as u32,
            hidden,
            QA as u32,
            QB as u32,
            SCALE as u32,
        ] {
            f.write_all(&value.to_le_bytes()).unwrap();
        }
    }

    #[test]
    fn loader_rejects_v1_crelu_header() {
        let path = std::env::temp_dir().join("pyro_test_nnue_v1.bin");
        let mut f = File::create(&path).unwrap();
        f.write_all(&Network::MAGIC).unwrap();
        f.write_all(&1u32.to_le_bytes()).unwrap();
        drop(f);

        let err = Network::from_file(path.to_str().unwrap()).err().unwrap();
        assert!(err.contains("unsupported NNUE version 1"), "{err}");
        std::fs::remove_file(path).ok();
    }

    #[test]
    fn loader_rejects_wrong_activation_and_width() {
        let activation_path = std::env::temp_dir().join("pyro_test_nnue_crelu.bin");
        write_header_only(
            activation_path.to_str().unwrap(),
            Network::VERSION,
            1,
            HIDDEN_SIZE as u32,
        );
        let activation_err =
            Network::from_file(activation_path.to_str().unwrap()).err().unwrap();
        assert!(activation_err.contains("activation mismatch"), "{activation_err}");

        let width_path = std::env::temp_dir().join("pyro_test_nnue_256.bin");
        write_header_only(
            width_path.to_str().unwrap(),
            Network::VERSION,
            Network::ACTIVATION_SCRELU,
            256,
        );
        let width_err = Network::from_file(width_path.to_str().unwrap()).err().unwrap();
        assert!(width_err.contains("hidden-size mismatch"), "{width_err}");

        std::fs::remove_file(activation_path).ok();
        std::fs::remove_file(width_path).ok();
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
