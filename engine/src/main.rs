mod board;
mod movegen;

use std::io::{self, BufRead};

fn main() {
    println!("Pyro Chess Engine v0.1 (Rust)");

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let trimmed = line.trim();

        match trimmed {
            "uci" => {
                println!("id name Pyro 0.1");
                println!("id author Shamik");
                println!("uciok");
            }
            "isready" => {
                println!("readyok");
            }
            "quit" => {
                break;
            }
            _ => {}
        }
    }
}
