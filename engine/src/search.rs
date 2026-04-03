use crate::board::Board;
use crate::movegen::{self, Move, generate_moves, is_in_check, make_move};

// Material values (centipawns)
const PAWN_VAL: i32 = 100;
const KNIGHT_VAL: i32 = 320;
const BISHOP_VAL: i32 = 330;
const ROOK_VAL: i32 = 500;
const QUEEN_VAL: i32 = 900;
const KING_VAL: i32 = 20_000;

const INF: i32 = 100_000;
const CHECKMATE: i32 = 50_000;

// ---------------------------------------------------------------------------
// Evaluation (material only)
// ---------------------------------------------------------------------------

/// Evaluate the position. Positive = white advantage, negative = black.
/// Returns score from the side-to-move's perspective.
pub fn evaluate(board: &Board) -> i32 {
    let white = count_material_white(board);
    let black = count_material_black(board);
    let score = white - black;
    if board.side_to_move { score } else { -score }
}

fn count_material_white(board: &Board) -> i32 {
    board.white_pawns.count_ones() as i32 * PAWN_VAL
        + board.white_knights.count_ones() as i32 * KNIGHT_VAL
        + board.white_bishops.count_ones() as i32 * BISHOP_VAL
        + board.white_rooks.count_ones() as i32 * ROOK_VAL
        + board.white_queens.count_ones() as i32 * QUEEN_VAL
        + board.white_kings.count_ones() as i32 * KING_VAL
}

fn count_material_black(board: &Board) -> i32 {
    board.black_pawns.count_ones() as i32 * PAWN_VAL
        + board.black_knights.count_ones() as i32 * KNIGHT_VAL
        + board.black_bishops.count_ones() as i32 * BISHOP_VAL
        + board.black_rooks.count_ones() as i32 * ROOK_VAL
        + board.black_queens.count_ones() as i32 * QUEEN_VAL
        + board.black_kings.count_ones() as i32 * KING_VAL
}

// ---------------------------------------------------------------------------
// Alpha-beta search
// ---------------------------------------------------------------------------

/// Alpha-beta search returning the score from the side-to-move's perspective.
pub fn alpha_beta(board: &Board, depth: u32, mut alpha: i32, beta: i32) -> i32 {
    if depth == 0 {
        return evaluate(board);
    }

    let moves = generate_moves(board);

    if moves.is_empty() {
        if is_in_check(board) {
            // Checkmate — return a large negative score (we are mated)
            // Offset by depth so shallower mates are preferred
            return -(CHECKMATE - depth as i32);
        }
        // Stalemate
        return 0;
    }

    for mv in &moves {
        let new_board = make_move(board, mv);
        let score = -alpha_beta(&new_board, depth - 1, -beta, -alpha);
        if score >= beta {
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
pub fn best_move(board: &Board, depth: u32) -> Option<(Move, i32)> {
    let moves = generate_moves(board);
    if moves.is_empty() {
        return None;
    }

    let mut best: Option<(Move, i32)> = None;
    let mut alpha = -INF;
    let beta = INF;

    for mv in moves {
        let new_board = make_move(board, &mv);
        let score = -alpha_beta(&new_board, depth - 1, -beta, -alpha);
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
        // White has an extra queen
        let board = Board::from_fen("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1").unwrap();
        let eval = evaluate(&board);
        assert!(eval > 800, "White up a queen should eval > 800, got {}", eval);
    }

    #[test]
    fn best_move_finds_capture() {
        // White queen can capture undefended black queen
        let board = Board::from_fen("4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1").unwrap();
        let result = best_move(&board, 2);
        assert!(result.is_some());
        let (mv, score) = result.unwrap();
        assert_eq!(mv.to_uci(), "d1d5", "Should capture the queen");
        assert!(score > 800, "Score should reflect queen capture, got {}", score);
    }

    #[test]
    fn finds_checkmate_in_one() {
        // White to move, Qh5# is mate (back rank)
        let board = Board::from_fen("6k1/5ppp/8/8/8/8/8/4K2Q w - - 0 1").unwrap();
        let result = best_move(&board, 2);
        assert!(result.is_some());
        let (_, score) = result.unwrap();
        assert!(score > 40_000, "Should find checkmate, score={}", score);
    }

    #[test]
    fn no_moves_in_checkmate() {
        let board = Board::from_fen("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4").unwrap();
        assert!(best_move(&board, 1).is_none());
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
    fn depth_0_returns_eval() {
        let board = Board::startpos();
        let score = alpha_beta(&board, 0, -INF, INF);
        assert_eq!(score, 0);
    }

    #[test]
    fn search_doesnt_blunder_queen() {
        // White queen under attack by black pawn — shouldn't leave it there
        let board = Board::from_fen("4k3/8/8/8/3p4/4Q3/8/4K3 w - - 0 1").unwrap();
        let result = best_move(&board, 3);
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
