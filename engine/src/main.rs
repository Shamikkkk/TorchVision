mod board;
mod movegen;
mod nnue;
mod search;

use board::Board;
use nnue::Network;
use search::{best_move, best_move_nodes, parse_uci_move};
use std::io::{self, BufRead, Write};

struct Engine {
    position: Board,
    network: Option<Network>,
    num_threads: usize,
}

impl Engine {
    fn new(no_nnue: bool) -> Self {
        let network = if no_nnue {
            eprintln!("NNUE disabled (--no-nnue), using PST + Tal");
            None
        } else {
            let net = Self::try_load_nnue();
            match &net {
                Some(_) => eprintln!("NNUE loaded"),
                None => eprintln!("NNUE not found, using PST"),
            }
            net
        };
        Engine {
            position: Board::startpos(),
            network,
            num_threads: 1,
        }
    }

    fn try_load_nnue() -> Option<Network> {
        // Look for pyro.nnue next to the executable
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                let path = dir.join("pyro.nnue");
                if let Ok(net) = Network::from_file(path.to_str()?) {
                    return Some(net);
                }
            }
        }
        // Also try current working directory
        Network::from_file("pyro.nnue").ok()
    }
}

fn main() {
    let no_nnue = std::env::args().any(|a| a == "--no-nnue");
    let mut engine = Engine::new(no_nnue);

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let trimmed = line.trim();
        let tokens: Vec<&str> = trimmed.split_whitespace().collect();
        if tokens.is_empty() {
            continue;
        }

        match tokens[0] {
            "uci" => {
                println!("id name Pyro 0.1");
                println!("id author Shamik");
                println!("option name Threads type spin default 1 min 1 max 128");
                println!("uciok");
                io::stdout().flush().ok();
            }
            "isready" => {
                println!("readyok");
                io::stdout().flush().ok();
            }
            "ucinewgame" => {
                engine.position = Board::startpos();
            }
            "position" => {
                engine.position = handle_position(&tokens);
            }
            "go" => {
                let white_to_move = engine.position.side_to_move; // true = white

                let result =
                    if let Some(duration) = parse_go_deadline(&tokens, white_to_move) {
                        // Time-based: unlimited nodes, hard deadline.
                        let deadline = std::time::Instant::now() + duration;
                        best_move_nodes(
                            &engine.position, u64::MAX, Some(deadline),
                            engine.network.as_ref(), engine.num_threads,
                        )
                    } else if let Some(node_limit) = parse_go_nodes(&tokens) {
                        // Node-limited (existing behaviour).
                        best_move_nodes(
                            &engine.position, node_limit, None,
                            engine.network.as_ref(), engine.num_threads,
                        )
                    } else {
                        // Fixed depth (existing behaviour).
                        let depth = parse_go_depth(&tokens);
                        best_move(&engine.position, depth, engine.network.as_ref())
                            .map(|(mv, score)| (mv, score, depth))
                    };

                if let Some((mv, score, depth)) = result {
                    println!("info depth {} score cp {}", depth, score);
                    println!("bestmove {}", mv.to_uci());
                } else {
                    println!("bestmove (none)");
                }
                io::stdout().flush().ok();
            }
            "setoption" => {
                // setoption name <Name> value <Value>
                if tokens.len() >= 5 && tokens[1] == "name" && tokens[3] == "value" {
                    match tokens[2].to_lowercase().as_str() {
                        "threads" => {
                            if let Ok(n) = tokens[4].parse::<usize>() {
                                engine.num_threads = n.clamp(1, 128);
                            }
                        }
                        _ => {}
                    }
                }
            }
            "quit" => {
                break;
            }
            _ => {}
        }
    }
}

/// Parse "position startpos [moves ...]" or "position fen <fen> [moves ...]"
fn handle_position(tokens: &[&str]) -> Board {
    if tokens.len() < 2 {
        return Board::startpos();
    }

    let (mut board, moves_start) = if tokens[1] == "startpos" {
        let idx = tokens.iter().position(|&t| t == "moves").unwrap_or(tokens.len());
        (Board::startpos(), idx + 1)
    } else if tokens[1] == "fen" {
        // Collect FEN fields (up to 6 tokens after "fen", stopping at "moves")
        let mut fen_parts = Vec::new();
        let mut i = 2;
        while i < tokens.len() && tokens[i] != "moves" && fen_parts.len() < 6 {
            fen_parts.push(tokens[i]);
            i += 1;
        }
        let fen = fen_parts.join(" ");
        let idx = tokens.iter().position(|&t| t == "moves").unwrap_or(tokens.len());
        match Board::from_fen(&fen) {
            Ok(b) => (b, idx + 1),
            Err(_) => return Board::startpos(),
        }
    } else {
        return Board::startpos();
    };

    // Apply moves
    if moves_start < tokens.len() {
        for uci_str in &tokens[moves_start..] {
            if let Some(mv) = parse_uci_move(&board, uci_str) {
                board = movegen::make_move(&board, &mv);
            }
        }
    }

    board
}

/// Parse a u64 value for a named key in "go" tokens (e.g. "wtime", "btime").
fn parse_go_u64(tokens: &[&str], key: &str) -> Option<u64> {
    let idx = tokens.iter().position(|&t| t == key)?;
    tokens.get(idx + 1)?.parse::<u64>().ok()
}

/// Compute a search duration from "go" tokens and the side to move.
/// Returns Some(Duration) for movetime/wtime/btime, None if no time info.
fn parse_go_deadline(tokens: &[&str], white_to_move: bool) -> Option<std::time::Duration> {
    use std::time::Duration;

    // movetime N: use N ms exactly, minus safety margin.
    if let Some(mt) = parse_go_u64(tokens, "movetime") {
        return Some(Duration::from_millis(mt.saturating_sub(50).max(1)));
    }

    // wtime/btime: compute allocation.
    let (time_key, inc_key) = if white_to_move { ("wtime", "winc") } else { ("btime", "binc") };
    let time_left = parse_go_u64(tokens, time_key)?;
    let increment  = parse_go_u64(tokens, inc_key).unwrap_or(0);
    let moves_to_go = parse_go_u64(tokens, "movestogo").unwrap_or(30);

    // Allocation: (time / moves_to_go) + increment, capped at 25% of clock,
    // minus 50ms safety, minimum 10ms.
    let base      = time_left / moves_to_go.max(1);
    let allocated = base + increment;
    let ceiling   = time_left / 4;
    let safe      = allocated.min(ceiling).saturating_sub(50).max(10);

    Some(Duration::from_millis(safe))
}

/// Parse depth from "go depth N". Default to 4 if not specified.
fn parse_go_depth(tokens: &[&str]) -> u32 {
    for i in 0..tokens.len().saturating_sub(1) {
        if tokens[i] == "depth" {
            if let Ok(d) = tokens[i + 1].parse::<u32>() {
                return d;
            }
        }
    }
    4
}

/// Parse node limit from "go nodes N". Returns None if not specified.
fn parse_go_nodes(tokens: &[&str]) -> Option<u64> {
    for i in 0..tokens.len().saturating_sub(1) {
        if tokens[i] == "nodes" {
            if let Ok(n) = tokens[i + 1].parse::<u64>() {
                return Some(n);
            }
        }
    }
    None
}
