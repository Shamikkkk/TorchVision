#[path = "../board.rs"]
mod board;
#[path = "../movegen.rs"]
mod movegen;
#[path = "../nnue.rs"]
mod nnue;

use board::Board;
use nnue::{Accumulator, Network, HIDDEN_SIZE};
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};

const OUTPUT_MAGIC: [u8; 4] = *b"NVR1";

fn usage() -> String {
    "usage: nnue_verify --net <versioned.nnue> --positions <category-tab-fen.tsv> \
     --output <results.bin>"
        .to_string()
}

fn parse_args() -> Result<(String, String, String), String> {
    let mut net = None;
    let mut positions = None;
    let mut output = None;
    let mut args = env::args().skip(1);

    while let Some(arg) = args.next() {
        let value = args.next().ok_or_else(usage)?;
        match arg.as_str() {
            "--net" => net = Some(value),
            "--positions" => positions = Some(value),
            "--output" => output = Some(value),
            _ => return Err(format!("unknown argument {arg}\n{}", usage())),
        }
    }

    Ok((
        net.ok_or_else(usage)?,
        positions.ok_or_else(usage)?,
        output.ok_or_else(usage)?,
    ))
}

fn load_fens(path: &str) -> Result<Vec<String>, String> {
    let file = File::open(path).map_err(|e| format!("open positions {path}: {e}"))?;
    let reader = BufReader::new(file);
    let mut fens = Vec::new();

    for (line_index, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("read positions line {}: {e}", line_index + 1))?;
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let fen = trimmed
            .split_once('\t')
            .map(|(_, fen)| fen)
            .unwrap_or(trimmed);
        Board::from_fen(fen)
            .map_err(|e| format!("positions line {} invalid FEN: {e}: {fen}", line_index + 1))?;
        fens.push(fen.to_string());
    }

    if fens.is_empty() {
        return Err("position set is empty".to_string());
    }
    Ok(fens)
}

fn write_i32(writer: &mut BufWriter<File>, value: i32) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|e| format!("write result: {e}"))
}

fn run() -> Result<(), String> {
    let (net_path, positions_path, output_path) = parse_args()?;
    let network = Network::from_file(&net_path)?;
    let fens = load_fens(&positions_path)?;
    let count = u32::try_from(fens.len()).map_err(|_| "too many positions".to_string())?;

    let output =
        File::create(&output_path).map_err(|e| format!("create output {output_path}: {e}"))?;
    let mut writer = BufWriter::new(output);
    writer
        .write_all(&OUTPUT_MAGIC)
        .map_err(|e| format!("write header: {e}"))?;
    writer
        .write_all(&count.to_le_bytes())
        .map_err(|e| format!("write count: {e}"))?;
    writer
        .write_all(&(HIDDEN_SIZE as u32).to_le_bytes())
        .map_err(|e| format!("write hidden size: {e}"))?;

    for fen in fens {
        let board = Board::from_fen(&fen)?;
        let accumulator = Accumulator::from_board(&network, &board);
        let cp = network.evaluate(&accumulator, board.side_to_move);
        write_i32(&mut writer, cp)?;
        for value in accumulator.white {
            write_i32(&mut writer, value)?;
        }
        for value in accumulator.black {
            write_i32(&mut writer, value)?;
        }
    }

    writer.flush().map_err(|e| format!("flush output: {e}"))
}

fn main() {
    if let Err(err) = run() {
        eprintln!("FATAL: {err}");
        std::process::exit(2);
    }
}
