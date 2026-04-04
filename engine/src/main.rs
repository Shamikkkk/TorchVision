mod board;
mod movegen;
mod nnue;
mod search;

use board::Board;
use nnue::Network;
use search::{best_move, parse_uci_move};
use std::io::{self, BufRead, Write};

struct Engine {
    position: Board,
    network: Option<Network>,
}

impl Engine {
    fn new() -> Self {
        // Try to load NNUE weights from the executable's directory
        let network = Self::try_load_nnue();
        match &network {
            Some(_) => eprintln!("NNUE loaded"),
            None => eprintln!("NNUE not found, using PST"),
        }
        Engine {
            position: Board::startpos(),
            network,
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
    let mut engine = Engine::new();

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
                let depth = parse_go_depth(&tokens);
                if let Some((mv, score)) = best_move(&engine.position, depth, engine.network.as_ref()) {
                    println!("info depth {} score cp {}", depth, score);
                    println!("bestmove {}", mv.to_uci());
                } else {
                    println!("bestmove (none)");
                }
                io::stdout().flush().ok();
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
