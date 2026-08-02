#[path = "../board.rs"]
mod board;
#[path = "../movegen.rs"]
mod movegen;
#[path = "../nnue.rs"]
mod nnue;

use board::Board;
use movegen::{generate_moves, make_move};
use nnue::{Accumulator, Network, HIDDEN_SIZE};
use std::collections::HashSet;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Write};

const POSITION_OUTPUT_MAGIC: [u8; 4] = *b"NVR1";
const SEQUENCE_OUTPUT_MAGIC: [u8; 4] = *b"NVS1";

enum InputMode {
    Positions(String),
    Sequences(String),
}

struct Args {
    net: String,
    input: InputMode,
    output: String,
}

struct SequenceCase {
    case_id: String,
    category: String,
    initial_fen: String,
    moves: Vec<String>,
}

fn usage() -> String {
    "usage: nnue_verify --net <versioned.nnue> \
     (--positions <category-tab-fen.tsv> | --sequences <case-category-fen-moves.tsv>) \
     --output <results.bin>"
        .to_string()
}

fn parse_args() -> Result<Args, String> {
    let mut net = None;
    let mut positions = None;
    let mut sequences = None;
    let mut output = None;
    let mut args = env::args().skip(1);

    while let Some(arg) = args.next() {
        let value = args.next().ok_or_else(usage)?;
        match arg.as_str() {
            "--net" => net = Some(value),
            "--positions" => positions = Some(value),
            "--sequences" => sequences = Some(value),
            "--output" => output = Some(value),
            _ => return Err(format!("unknown argument {arg}\n{}", usage())),
        }
    }

    let input = match (positions, sequences) {
        (Some(path), None) => InputMode::Positions(path),
        (None, Some(path)) => InputMode::Sequences(path),
        _ => {
            return Err(format!(
                "exactly one of --positions or --sequences is required\n{}",
                usage()
            ));
        }
    };

    Ok(Args {
        net: net.ok_or_else(usage)?,
        input,
        output: output.ok_or_else(usage)?,
    })
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

fn load_sequences(path: &str) -> Result<Vec<SequenceCase>, String> {
    let file = File::open(path).map_err(|e| format!("open sequences {path}: {e}"))?;
    let reader = BufReader::new(file);
    let mut cases = Vec::new();
    let mut case_ids = HashSet::new();

    for (line_index, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("read sequences line {}: {e}", line_index + 1))?;
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let fields: Vec<&str> = trimmed.split('\t').collect();
        if fields.len() != 4 {
            return Err(format!(
                "sequences line {} must have four tab-separated fields, got {}",
                line_index + 1,
                fields.len()
            ));
        }
        let case_id = fields[0].to_string();
        if case_id.is_empty() || !case_ids.insert(case_id.clone()) {
            return Err(format!(
                "sequences line {} has an empty or duplicate case ID: {}",
                line_index + 1,
                fields[0]
            ));
        }
        Board::from_fen(fields[2]).map_err(|e| {
            format!(
                "sequences line {} invalid initial FEN: {e}: {}",
                line_index + 1,
                fields[2]
            )
        })?;
        let moves: Vec<String> = fields[3]
            .split_whitespace()
            .map(str::to_string)
            .collect();
        if moves.is_empty() {
            return Err(format!("sequences line {} contains no moves", line_index + 1));
        }
        cases.push(SequenceCase {
            case_id,
            category: fields[1].to_string(),
            initial_fen: fields[2].to_string(),
            moves,
        });
    }

    if cases.is_empty() {
        return Err("sequence set is empty".to_string());
    }
    Ok(cases)
}

fn write_u16(writer: &mut BufWriter<File>, value: u16) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|e| format!("write result: {e}"))
}

fn write_u32(writer: &mut BufWriter<File>, value: u32) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|e| format!("write result: {e}"))
}

fn write_i32(writer: &mut BufWriter<File>, value: i32) -> Result<(), String> {
    writer
        .write_all(&value.to_le_bytes())
        .map_err(|e| format!("write result: {e}"))
}

fn write_accumulator(writer: &mut BufWriter<File>, acc: &Accumulator) -> Result<(), String> {
    for value in acc.white {
        write_i32(writer, value)?;
    }
    for value in acc.black {
        write_i32(writer, value)?;
    }
    Ok(())
}

fn run_positions(
    network: &Network,
    positions_path: &str,
    output_path: &str,
) -> Result<(), String> {
    let fens = load_fens(positions_path)?;
    let count = u32::try_from(fens.len()).map_err(|_| "too many positions".to_string())?;

    let output =
        File::create(output_path).map_err(|e| format!("create output {output_path}: {e}"))?;
    let mut writer = BufWriter::new(output);
    writer
        .write_all(&POSITION_OUTPUT_MAGIC)
        .map_err(|e| format!("write header: {e}"))?;
    write_u32(&mut writer, count)?;
    write_u32(&mut writer, HIDDEN_SIZE as u32)?;

    for fen in fens {
        let board = Board::from_fen(&fen)?;
        let accumulator = Accumulator::from_board(network, &board);
        let cp = network.evaluate(&accumulator, board.side_to_move);
        write_i32(&mut writer, cp)?;
        write_accumulator(&mut writer, &accumulator)?;
    }

    writer.flush().map_err(|e| format!("flush output: {e}"))
}

fn first_lane_mismatch(incremental: &Accumulator, full: &Accumulator) -> Option<(&'static str, usize, i32, i32)> {
    for index in 0..HIDDEN_SIZE {
        if incremental.white[index] != full.white[index] {
            return Some(("white", index, incremental.white[index], full.white[index]));
        }
    }
    for index in 0..HIDDEN_SIZE {
        if incremental.black[index] != full.black[index] {
            return Some(("black", index, incremental.black[index], full.black[index]));
        }
    }
    None
}

fn run_sequences(
    network: &Network,
    sequences_path: &str,
    output_path: &str,
) -> Result<(), String> {
    let cases = load_sequences(sequences_path)?;
    let case_count = u32::try_from(cases.len()).map_err(|_| "too many sequence cases".to_string())?;
    let transition_count = cases.iter().try_fold(0u32, |total, case| {
        let moves = u32::try_from(case.moves.len()).map_err(|_| "too many moves in sequence".to_string())?;
        total
            .checked_add(moves)
            .ok_or_else(|| "too many total sequence transitions".to_string())
    })?;

    let output =
        File::create(output_path).map_err(|e| format!("create output {output_path}: {e}"))?;
    let mut writer = BufWriter::new(output);
    writer
        .write_all(&SEQUENCE_OUTPUT_MAGIC)
        .map_err(|e| format!("write sequence header: {e}"))?;
    write_u32(&mut writer, case_count)?;
    write_u32(&mut writer, transition_count)?;
    write_u32(&mut writer, HIDDEN_SIZE as u32)?;

    for (case_index, case) in cases.iter().enumerate() {
        let mut board = Board::from_fen(&case.initial_fen)?;
        let mut incremental = Accumulator::from_board(network, &board);

        for (move_index, uci) in case.moves.iter().enumerate() {
            let child = if uci == "0000" {
                board.make_null_move()
            } else {
                let mv = generate_moves(&board)
                    .into_iter()
                    .find(|mv| mv.to_uci() == *uci)
                    .ok_or_else(|| {
                        format!(
                            "illegal sequence move: case={} category={} ply={} move={} fen={}",
                            case.case_id,
                            case.category,
                            move_index + 1,
                            uci,
                            case.initial_fen
                        )
                    })?;
                make_move(&board, &mv)
            };

            let child_incremental = if uci == "0000" {
                incremental.clone()
            } else {
                incremental.updated_for_child(network, &board, &child)
            };
            let child_full = Accumulator::from_board(network, &child);
            let incremental_cp = network.evaluate(&child_incremental, child.side_to_move);
            let full_cp = network.evaluate(&child_full, child.side_to_move);

            if let Some((perspective, lane, incremental_value, full_value)) =
                first_lane_mismatch(&child_incremental, &child_full)
            {
                return Err(format!(
                    "incremental mismatch: case={} category={} ply={} move={} perspective={} lane={} incremental={} full={}",
                    case.case_id,
                    case.category,
                    move_index + 1,
                    uci,
                    perspective,
                    lane,
                    incremental_value,
                    full_value
                ));
            }
            if incremental_cp != full_cp {
                return Err(format!(
                    "incremental cp mismatch: case={} category={} ply={} move={} incremental_cp={} full_cp={}",
                    case.case_id,
                    case.category,
                    move_index + 1,
                    uci,
                    incremental_cp,
                    full_cp
                ));
            }

            write_u32(&mut writer, case_index as u32)?;
            write_u32(&mut writer, (move_index + 1) as u32)?;
            let move_bytes = uci.as_bytes();
            write_u16(
                &mut writer,
                u16::try_from(move_bytes.len()).map_err(|_| "sequence move token is too long".to_string())?,
            )?;
            writer
                .write_all(move_bytes)
                .map_err(|e| format!("write move token: {e}"))?;
            write_i32(&mut writer, incremental_cp)?;
            write_i32(&mut writer, full_cp)?;
            write_accumulator(&mut writer, &child_incremental)?;
            write_accumulator(&mut writer, &child_full)?;

            board = child;
            incremental = child_incremental;
        }
    }

    writer.flush().map_err(|e| format!("flush sequence output: {e}"))
}

fn run() -> Result<(), String> {
    let args = parse_args()?;
    let network = Network::from_file(&args.net)?;
    match args.input {
        InputMode::Positions(path) => run_positions(&network, &path, &args.output),
        InputMode::Sequences(path) => run_sequences(&network, &path, &args.output),
    }
}

fn main() {
    if let Err(err) = run() {
        eprintln!("FATAL: {err}");
        std::process::exit(2);
    }
}
