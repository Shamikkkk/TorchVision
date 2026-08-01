//! Deterministic fixed-work benchmark for search-throughput measurements.
//!
//! Bench v1 always searches the canonical ten-position suite at depth 8 and
//! Threads=1.  Its checksum covers deterministic work/results only; elapsed
//! time and NPS are deliberately excluded.

use crate::board::Board;
use crate::nnue::Network;
use crate::search::best_move;

use std::time::Instant;

pub const BENCH_VERSION: u32 = 1;
pub const BENCH_DEPTH: u32 = 8;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

pub const BENCH_SUITE: [(&str, &str); 10] = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("after_1e4", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"),
    ("italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("french", "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3"),
    ("sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    ("kgambit", "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq - 0 2"),
    ("kid", "rnbqk2r/ppp1ppbp/3p1np1/8/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5"),
    ("dragon", "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"),
    ("greek_gift_attack", "r1bq1rk1/ppp2ppp/2n5/3pn3/1bB1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7"),
    ("king_attack_pos", "r1b1k2r/ppp2ppp/2n5/3qp3/1bB5/2N2N2/PPPP1PPP/R1BQ1RK1 w kq - 0 7"),
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BenchPosition {
    pub index: usize,
    pub label: &'static str,
    pub best_move: String,
    pub score: i32,
    pub depth: u32,
    pub nodes: u64,
}

#[derive(Debug)]
pub struct BenchReport {
    pub mode: &'static str,
    pub positions: Vec<BenchPosition>,
    pub nodes: u64,
    pub time_ms: u128,
    pub nps: u64,
    pub checksum: u64,
}

/// Integer NPS calculation shared by normal UCI reporting and bench output.
pub fn nodes_per_second(nodes: u64, time_ms: u128) -> u64 {
    let value = (nodes as u128)
        .saturating_mul(1_000)
        / time_ms.max(1);
    value.min(u64::MAX as u128) as u64
}

fn fnv_add(mut hash: u64, bytes: &[u8]) -> u64 {
    for byte in bytes {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

fn deterministic_checksum(mode: &str, positions: &[BenchPosition]) -> u64 {
    let mut hash = FNV_OFFSET;
    hash = fnv_add(hash, b"pyro-bench-v1\0");
    hash = fnv_add(hash, mode.as_bytes());
    hash = fnv_add(hash, b"\0");
    hash = fnv_add(hash, &BENCH_DEPTH.to_le_bytes());

    for position in positions {
        hash = fnv_add(hash, &(position.index as u32).to_le_bytes());
        hash = fnv_add(hash, position.label.as_bytes());
        hash = fnv_add(hash, b"\0");
        hash = fnv_add(hash, position.best_move.as_bytes());
        hash = fnv_add(hash, b"\0");
        hash = fnv_add(hash, &position.score.to_le_bytes());
        hash = fnv_add(hash, &position.depth.to_le_bytes());
        hash = fnv_add(hash, &position.nodes.to_le_bytes());
    }
    hash
}

pub fn run(network: Option<&Network>) -> Result<BenchReport, String> {
    let mode = if network.is_some() { "nnue" } else { "pesto" };
    let started = Instant::now();
    let mut positions = Vec::with_capacity(BENCH_SUITE.len());
    let mut total_nodes = 0u64;

    for (offset, (label, fen)) in BENCH_SUITE.iter().enumerate() {
        let board = Board::from_fen(fen)
            .map_err(|error| format!("bench position {label} has invalid FEN: {error}"))?;
        let outcome = best_move(&board, BENCH_DEPTH, network)
            .ok_or_else(|| format!("bench position {label} has no legal move"))?;
        total_nodes = total_nodes.saturating_add(outcome.nodes);
        positions.push(BenchPosition {
            index: offset + 1,
            label,
            best_move: outcome.best_move.to_uci(),
            score: outcome.score,
            depth: outcome.depth,
            nodes: outcome.nodes,
        });
    }

    let time_ms = started.elapsed().as_millis();
    let checksum = deterministic_checksum(mode, &positions);
    Ok(BenchReport {
        mode,
        positions,
        nodes: total_nodes,
        time_ms,
        nps: nodes_per_second(total_nodes, time_ms),
        checksum,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(nodes: u64) -> Vec<BenchPosition> {
        vec![BenchPosition {
            index: 1,
            label: "sample",
            best_move: "e2e4".to_string(),
            score: 17,
            depth: BENCH_DEPTH,
            nodes,
        }]
    }

    #[test]
    fn bench_suite_is_fixed_and_valid() {
        assert_eq!(BENCH_SUITE.len(), 10);
        for (_, fen) in BENCH_SUITE {
            Board::from_fen(fen).expect("bench FEN must remain valid");
        }
    }

    #[test]
    fn nps_uses_one_millisecond_floor() {
        assert_eq!(nodes_per_second(123, 0), 123_000);
        assert_eq!(nodes_per_second(123, 1), 123_000);
        assert_eq!(nodes_per_second(1_000, 2_000), 500);
    }

    #[test]
    fn checksum_is_deterministic_and_work_sensitive() {
        let first = deterministic_checksum("nnue", &sample(1_000));
        assert_eq!(first, deterministic_checksum("nnue", &sample(1_000)));
        assert_ne!(first, deterministic_checksum("nnue", &sample(1_001)));
        assert_ne!(first, deterministic_checksum("pesto", &sample(1_000)));
    }
}
