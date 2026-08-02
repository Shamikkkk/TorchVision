"""Verify ticket #19 search accounting and deterministic bench behavior.

The harness compares fixed-depth baseline/candidate decision tuples in NNUE
and PeSTO modes, validates candidate ``info nodes time nps`` arithmetic, and
runs repeated candidate bench-v1 processes.  Timing fields may vary; every
deterministic result/work field must match exactly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import chess


DEPTH = 8
SUITE = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("after_1e4", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"),
    ("italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("french", "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3"),
    ("sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    ("kgambit", "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq - 0 2"),
    ("kid", "rnbqk2r/ppp1ppbp/3p1np1/8/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5"),
    ("dragon", "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"),
    (
        "greek_gift_attack",
        "r1bq1rk1/ppp2ppp/2n5/3pn3/1bB1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7",
    ),
    (
        "king_attack_pos",
        "r1b1k2r/ppp2ppp/2n5/3qp3/1bB5/2N2N2/PPPP1PPP/R1BQ1RK1 w kq - 0 7",
    ),
]

INFO_RE = re.compile(r"\bdepth\s+(\d+)\b.*\bscore\s+cp\s+(-?\d+)\b")
STATS_RE = re.compile(r"\bnodes\s+(\d+)\b.*\btime\s+(\d+)\b.*\bnps\s+(\d+)\b")
BENCH_POSITION_RE = re.compile(
    r"^info string bench position (?P<index>\d+) label (?P<label>\S+) "
    r"bestmove (?P<bestmove>\S+) score (?P<score>-?\d+) "
    r"depth (?P<depth>\d+) nodes (?P<nodes>\d+)$"
)
BENCH_COMPLETE_RE = re.compile(
    r"^info string bench complete version (?P<version>\d+) mode (?P<mode>\S+) "
    r"threads (?P<threads>\d+) positions (?P<positions>\d+) "
    r"depth (?P<depth>\d+) nodes (?P<nodes>\d+) time (?P<time_ms>\d+) "
    r"nps (?P<nps>\d+) checksum (?P<checksum>[0-9a-f]{16})$"
)
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")

FNV_OFFSET = 14_695_981_039_346_656_037
FNV_PRIME = 1_099_511_628_211
U64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class FixedResult:
    engine: str
    mode: str
    label: str
    fen: str
    bestmove: str
    score: int
    depth: int
    nodes: int | None
    time_ms: int | None
    nps: int | None
    legal: bool

    def decision_tuple(self) -> tuple[str, int, int]:
        return (self.bestmove, self.score, self.depth)


@dataclass(frozen=True)
class BenchPosition:
    mode: str
    repetition: int
    index: int
    label: str
    bestmove: str
    score: int
    depth: int
    nodes: int


@dataclass(frozen=True)
class BenchRun:
    mode: str
    repetition: int
    version: int
    threads: int
    positions: int
    depth: int
    nodes: int
    time_ms: int
    nps: int
    checksum: str
    recomputed_checksum: str


@dataclass(frozen=True)
class PairedBenchSample:
    mode: str
    phase: str
    execution_index: int
    artifact: str
    artifact_sample: int
    nodes: int
    time_ms: int
    nps: int
    checksum: str


@dataclass(frozen=True)
class PairedBenchPosition:
    mode: str
    artifact: str
    execution_index: int
    artifact_sample: int
    index: int
    label: str
    bestmove: str
    score: int
    depth: int
    nodes: int


@dataclass(frozen=True)
class PairedBenchDelta:
    mode: str
    pair: int
    baseline_time_ms: int
    candidate_time_ms: int
    candidate_minus_baseline_ms: int
    elapsed_improvement_percent: float
    baseline_nps: int
    candidate_nps: int
    nps_improvement_percent: float
    candidate_won: bool
    contaminated: bool
    contamination_reason: str


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_expected_sha256(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be exactly 64 hexadecimal characters")
    return value.lower()


def resolve_distinct_artifacts(
    baseline: Path,
    candidate: Path,
    expected_baseline_sha256: str | None = None,
    expected_candidate_sha256: str | None = None,
) -> tuple[Path, Path, str, str]:
    """Resolve and authenticate both binaries before either can execute."""
    baseline = baseline.resolve(strict=True)
    candidate = candidate.resolve(strict=True)
    if not baseline.is_file():
        raise FileNotFoundError(baseline)
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    if baseline == candidate:
        raise ValueError("baseline and candidate resolve to the same path")
    try:
        if baseline.samefile(candidate):
            raise ValueError("baseline and candidate refer to the same filesystem object")
    except OSError as error:
        raise OSError("could not establish baseline/candidate filesystem identity") from error

    baseline_sha256 = digest(baseline, "sha256")
    candidate_sha256 = digest(candidate, "sha256")
    if baseline_sha256 == candidate_sha256:
        raise ValueError("baseline and candidate have identical SHA-256 hashes")

    expected_baseline = normalize_expected_sha256(
        expected_baseline_sha256, "expected baseline SHA-256"
    )
    expected_candidate = normalize_expected_sha256(
        expected_candidate_sha256, "expected candidate SHA-256"
    )
    if expected_baseline is not None and baseline_sha256 != expected_baseline:
        raise ValueError(
            f"baseline SHA-256 mismatch: expected {expected_baseline}, "
            f"got {baseline_sha256}"
        )
    if expected_candidate is not None and candidate_sha256 != expected_candidate:
        raise ValueError(
            f"candidate SHA-256 mismatch: expected {expected_candidate}, "
            f"got {candidate_sha256}"
        )
    return baseline, candidate, baseline_sha256, candidate_sha256


def fnv_add(hash_value: int, data: bytes) -> int:
    for byte in data:
        hash_value ^= byte
        hash_value = (hash_value * FNV_PRIME) & U64_MAX
    return hash_value


def encode_unsigned(value: int, width: int, label: str) -> bytes:
    maximum = (1 << (width * 8)) - 1
    if not 0 <= value <= maximum:
        raise ValueError(f"{label} does not fit unsigned {width * 8}-bit encoding")
    return value.to_bytes(width, byteorder="little", signed=False)


def encode_signed(value: int, width: int, label: str) -> bytes:
    minimum = -(1 << (width * 8 - 1))
    maximum = (1 << (width * 8 - 1)) - 1
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} does not fit signed {width * 8}-bit encoding")
    return value.to_bytes(width, byteorder="little", signed=True)


def recompute_bench_checksum(mode: str, positions: list[BenchPosition]) -> str:
    """Mirror engine/src/bench.rs using independent fixed-width encoders."""
    if mode not in {"nnue", "pesto"}:
        raise ValueError(f"unsupported bench mode {mode!r}")
    hash_value = FNV_OFFSET
    for data in (
        b"pyro-bench-v1\0",
        mode.encode("utf-8"),
        b"\0",
        encode_unsigned(DEPTH, 4, "bench depth"),
    ):
        hash_value = fnv_add(hash_value, data)

    for position in positions:
        for data in (
            encode_unsigned(position.index, 4, "position index"),
            position.label.encode("utf-8"),
            b"\0",
            position.bestmove.encode("utf-8"),
            b"\0",
            encode_signed(position.score, 4, "position score"),
            encode_unsigned(position.depth, 4, "completed depth"),
            encode_unsigned(position.nodes, 8, "position nodes"),
        ):
            hash_value = fnv_add(hash_value, data)
    return f"{hash_value:016x}"


def run_engine(
    engine: Path,
    commands: str,
    no_nnue: bool,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    command = [str(engine.resolve())]
    if no_nnue:
        command.append("--no-nnue")
    result = subprocess.run(
        command,
        cwd=str(engine.resolve().parent),
        input=commands,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{engine} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def fixed_search(
    engine: Path,
    mode: str,
    label: str,
    fen: str,
    timeout_seconds: float,
) -> FixedResult:
    result = run_engine(
        engine,
        "uci\n"
        "setoption name Threads value 1\n"
        "isready\n"
        f"position fen {fen}\n"
        f"go depth {DEPTH}\n"
        "quit\n",
        mode == "pesto",
        timeout_seconds,
    )
    info_lines = [line for line in result.stdout.splitlines() if line.startswith("info ")]
    bestmoves = [
        line.split(maxsplit=1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("bestmove ")
    ]
    if len(bestmoves) != 1 or not info_lines:
        raise AssertionError(
            f"{engine}/{mode}/{label}: incomplete output\n{result.stdout}"
        )
    info = info_lines[-1]
    decision = INFO_RE.search(info)
    if decision is None:
        raise AssertionError(f"{engine}/{mode}/{label}: unparseable info line: {info}")
    stats = STATS_RE.search(info)
    nodes = int(stats.group(1)) if stats else None
    time_ms = int(stats.group(2)) if stats else None
    nps = int(stats.group(3)) if stats else None
    if stats and nps != nodes * 1000 // max(time_ms, 1):
        raise AssertionError(f"{engine}/{mode}/{label}: incorrect NPS arithmetic: {info}")

    board = chess.Board(fen)
    move = chess.Move.from_uci(bestmoves[0])
    legal = move in board.legal_moves
    if not legal:
        raise AssertionError(f"{engine}/{mode}/{label}: illegal move {bestmoves[0]}")
    return FixedResult(
        engine=str(engine.resolve()),
        mode=mode,
        label=label,
        fen=fen,
        bestmove=bestmoves[0],
        score=int(decision.group(2)),
        depth=int(decision.group(1)),
        nodes=nodes,
        time_ms=time_ms,
        nps=nps,
        legal=legal,
    )


def parse_bench_output(
    stdout: str,
    mode: str,
    repetition: int,
) -> tuple[BenchRun, list[BenchPosition]]:
    positions: list[BenchPosition] = []
    completions: list[dict[str, str]] = []
    fens = {label: fen for label, fen in SUITE}
    seen_labels: set[str] = set()
    seen_indices: set[int] = set()
    for line in stdout.splitlines():
        position_match = BENCH_POSITION_RE.match(line)
        if position_match:
            values = position_match.groupdict()
            label = values["label"]
            index = int(values["index"])
            if label not in fens:
                raise AssertionError(f"bench returned unknown label {label}")
            if label in seen_labels:
                raise AssertionError(f"bench {mode}: duplicate position label {label}")
            if index in seen_indices:
                raise AssertionError(f"bench {mode}: duplicate position index {index}")
            seen_labels.add(label)
            seen_indices.add(index)
            board = chess.Board(fens[label])
            move = chess.Move.from_uci(values["bestmove"])
            if move not in board.legal_moves:
                raise AssertionError(f"bench {mode}/{label}: illegal move {move}")
            positions.append(
                BenchPosition(
                    mode=mode,
                    repetition=repetition,
                    index=index,
                    label=label,
                    bestmove=values["bestmove"],
                    score=int(values["score"]),
                    depth=int(values["depth"]),
                    nodes=int(values["nodes"]),
                )
            )
            continue
        if line.startswith("info string bench position "):
            raise AssertionError(f"bench {mode}: malformed position line: {line}")
        complete_match = BENCH_COMPLETE_RE.match(line)
        if complete_match:
            completions.append(complete_match.groupdict())
            continue
        if line.startswith("info string bench complete "):
            raise AssertionError(f"bench {mode}: malformed completion line: {line}")

    if not completions:
        raise AssertionError(f"bench {mode}: completion line missing\n{stdout}")
    if len(completions) != 1:
        raise AssertionError(
            f"bench {mode}: expected one completion line, got {len(completions)}"
        )
    values = completions[0]
    engine_checksum = values["checksum"]
    recomputed_checksum = recompute_bench_checksum(mode, positions)
    complete = BenchRun(
        mode=values["mode"],
        repetition=repetition,
        version=int(values["version"]),
        threads=int(values["threads"]),
        positions=int(values["positions"]),
        depth=int(values["depth"]),
        nodes=int(values["nodes"]),
        time_ms=int(values["time_ms"]),
        nps=int(values["nps"]),
        checksum=engine_checksum,
        recomputed_checksum=recomputed_checksum,
    )
    if complete.mode != mode or complete.version != 1 or complete.threads != 1:
        raise AssertionError(f"bench {mode}: incorrect identity fields: {complete}")
    if complete.positions != len(SUITE) or complete.depth != DEPTH:
        raise AssertionError(f"bench {mode}: incorrect suite/depth: {complete}")
    if len(positions) != len(SUITE):
        raise AssertionError(f"bench {mode}: expected {len(SUITE)} rows, got {len(positions)}")
    expected_indices = list(range(1, len(SUITE) + 1))
    actual_indices = [position.index for position in positions]
    if actual_indices != expected_indices:
        raise AssertionError(
            f"bench {mode}: wrong position indices/order: {actual_indices}"
        )
    if [position.label for position in positions] != [label for label, _ in SUITE]:
        raise AssertionError(f"bench {mode}: suite ordering changed")
    if len({position.label for position in positions}) != len(positions):
        raise AssertionError(f"bench {mode}: duplicate position label")
    for position in positions:
        if position.depth != DEPTH:
            raise AssertionError(
                f"bench {mode}: position {position.index} label {position.label} "
                f"expected depth {DEPTH}, got {position.depth}"
            )
    if complete.nodes != sum(position.nodes for position in positions):
        raise AssertionError(f"bench {mode}: summary node total does not equal row sum")
    if complete.nps != complete.nodes * 1000 // max(complete.time_ms, 1):
        raise AssertionError(f"bench {mode}: incorrect NPS arithmetic: {complete}")
    if complete.checksum != complete.recomputed_checksum:
        raise AssertionError(
            f"bench {mode}: checksum mismatch: engine={complete.checksum}, "
            f"python={complete.recomputed_checksum}"
        )
    return complete, positions


def run_bench(
    engine: Path,
    mode: str,
    repetition: int,
    timeout_seconds: float,
) -> tuple[BenchRun, list[BenchPosition]]:
    result = run_engine(
        engine,
        "uci\nisready\nbench\nquit\n",
        mode == "pesto",
        timeout_seconds,
    )
    return parse_bench_output(result.stdout, mode, repetition)


def deterministic_signature(
    run: BenchRun, positions: list[BenchPosition]
) -> tuple[object, ...]:
    return (
        run.mode,
        run.version,
        run.threads,
        run.positions,
        run.depth,
        run.nodes,
        run.checksum,
        run.recomputed_checksum,
        tuple(
            (
                position.index,
                position.label,
                position.bestmove,
                position.score,
                position.depth,
                position.nodes,
            )
            for position in positions
        ),
    )


def write_tsv(path: Path, rows: list[object]) -> None:
    if not rows:
        return
    dictionaries = [asdict(row) for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dictionaries[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(dictionaries)


def file_metadata(path: Path, expected_sha256: str | None = None) -> dict[str, object]:
    sha256 = digest(path, "sha256")
    if expected_sha256 is not None and sha256 != expected_sha256:
        raise AssertionError(f"{path}: SHA-256 changed during verification")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "md5": digest(path, "md5"),
        "sha256": sha256,
    }


def median_mad(values: list[int]) -> tuple[float, float, float]:
    if not values:
        raise ValueError("cannot summarize an empty sample")
    median_value = float(statistics.median(values))
    mad = float(statistics.median(abs(value - median_value) for value in values))
    noise_percent = 0.0 if median_value == 0 else 300.0 * mad / median_value
    return median_value, mad, noise_percent


def parse_contaminated_pairs(values: list[str], repetitions: int) -> dict[tuple[str, int], str]:
    contaminated: dict[tuple[str, int], str] = {}
    for value in values:
        fields = value.split(":", 2)
        if len(fields) != 3:
            raise ValueError(
                "--contaminated-pair must be MODE:PAIR:RECORDED_REASON"
            )
        mode, pair_text, reason = fields
        if mode not in {"nnue", "pesto"}:
            raise ValueError(f"invalid contaminated-pair mode {mode!r}")
        try:
            pair = int(pair_text)
        except ValueError as error:
            raise ValueError(f"invalid contaminated-pair index {pair_text!r}") from error
        if not 1 <= pair <= repetitions:
            raise ValueError(
                f"contaminated-pair index {pair} outside 1..{repetitions}"
            )
        if not reason.strip():
            raise ValueError("contaminated-pair reason must not be empty")
        key = (mode, pair)
        if key in contaminated:
            raise ValueError(f"duplicate contaminated-pair declaration {mode}:{pair}")
        contaminated[key] = reason.strip()
    return contaminated


def run_paired_performance(
    baseline: Path,
    candidate: Path,
    timeout_seconds: float,
    repetitions: int,
    contaminated: dict[tuple[str, int], str],
    output_dir: Path,
) -> tuple[
    list[PairedBenchSample],
    list[PairedBenchPosition],
    list[PairedBenchDelta],
    dict[str, object],
]:
    samples: list[PairedBenchSample] = []
    positions_out: list[PairedBenchPosition] = []
    deltas: list[PairedBenchDelta] = []
    summaries: dict[str, object] = {}

    for mode in ("nnue", "pesto"):
        reference_signature: tuple[object, ...] | None = None
        print(f"Running excluded paired {mode} warm-ups...", flush=True)
        for artifact, engine in (("baseline", baseline), ("candidate", candidate)):
            run, positions = run_bench(engine, mode, 0, timeout_seconds)
            signature = deterministic_signature(run, positions)
            if reference_signature is None:
                reference_signature = signature
            elif signature != reference_signature:
                raise AssertionError(
                    f"paired bench {mode}: warm-up deterministic signature differs "
                    f"for {artifact}"
                )
            samples.append(
                PairedBenchSample(
                    mode=mode,
                    phase="warmup",
                    execution_index=0,
                    artifact=artifact,
                    artifact_sample=0,
                    nodes=run.nodes,
                    time_ms=run.time_ms,
                    nps=run.nps,
                    checksum=run.checksum,
                )
            )

        order = ["baseline", "candidate", "candidate", "baseline"] * (
            repetitions // 2
        )
        if repetitions % 2:
            order.extend(("baseline", "candidate"))
        artifact_counts = {"baseline": 0, "candidate": 0}
        measured_runs: dict[str, list[BenchRun]] = {"baseline": [], "candidate": []}

        for execution_index, artifact in enumerate(order, 1):
            artifact_counts[artifact] += 1
            artifact_sample = artifact_counts[artifact]
            engine = baseline if artifact == "baseline" else candidate
            run, positions = run_bench(
                engine, mode, artifact_sample, timeout_seconds
            )
            signature = deterministic_signature(run, positions)
            if signature != reference_signature:
                raise AssertionError(
                    f"paired bench {mode} execution {execution_index} artifact {artifact}: "
                    "deterministic signature changed"
                )
            measured_runs[artifact].append(run)
            positions_out.extend(
                PairedBenchPosition(
                    mode=position.mode,
                    artifact=artifact,
                    execution_index=execution_index,
                    artifact_sample=artifact_sample,
                    index=position.index,
                    label=position.label,
                    bestmove=position.bestmove,
                    score=position.score,
                    depth=position.depth,
                    nodes=position.nodes,
                )
                for position in positions
            )
            samples.append(
                PairedBenchSample(
                    mode=mode,
                    phase="measured",
                    execution_index=execution_index,
                    artifact=artifact,
                    artifact_sample=artifact_sample,
                    nodes=run.nodes,
                    time_ms=run.time_ms,
                    nps=run.nps,
                    checksum=run.checksum,
                )
            )
            print(
                f"mode={mode} execution={execution_index:02d} artifact={artifact} "
                f"sample={artifact_sample:02d} nodes={run.nodes} time={run.time_ms} "
                f"nps={run.nps} checksum={run.checksum}",
                flush=True,
            )

        if artifact_counts != {"baseline": repetitions, "candidate": repetitions}:
            raise AssertionError(
                f"paired bench {mode}: incorrect ABBA sample counts {artifact_counts}"
            )

        for pair in range(1, repetitions + 1):
            baseline_run = measured_runs["baseline"][pair - 1]
            candidate_run = measured_runs["candidate"][pair - 1]
            reason = contaminated.get((mode, pair), "")
            elapsed_improvement = (
                100.0 * (baseline_run.time_ms - candidate_run.time_ms)
                / max(baseline_run.time_ms, 1)
            )
            nps_improvement = (
                100.0 * (candidate_run.nps - baseline_run.nps)
                / max(baseline_run.nps, 1)
            )
            deltas.append(
                PairedBenchDelta(
                    mode=mode,
                    pair=pair,
                    baseline_time_ms=baseline_run.time_ms,
                    candidate_time_ms=candidate_run.time_ms,
                    candidate_minus_baseline_ms=(
                        candidate_run.time_ms - baseline_run.time_ms
                    ),
                    elapsed_improvement_percent=round(elapsed_improvement, 6),
                    baseline_nps=baseline_run.nps,
                    candidate_nps=candidate_run.nps,
                    nps_improvement_percent=round(nps_improvement, 6),
                    candidate_won=candidate_run.time_ms < baseline_run.time_ms,
                    contaminated=bool(reason),
                    contamination_reason=reason,
                )
            )

        mode_deltas = [delta for delta in deltas if delta.mode == mode]
        valid_deltas = [delta for delta in mode_deltas if not delta.contaminated]
        baseline_times = [delta.baseline_time_ms for delta in valid_deltas]
        candidate_times = [delta.candidate_time_ms for delta in valid_deltas]
        baseline_nps = [delta.baseline_nps for delta in valid_deltas]
        candidate_nps = [delta.candidate_nps for delta in valid_deltas]
        baseline_median, baseline_mad, baseline_noise = median_mad(baseline_times)
        candidate_median, candidate_mad, candidate_noise = median_mad(candidate_times)
        summaries[mode] = {
            "execution_order": order,
            "measured_samples_per_artifact": repetitions,
            "valid_pairs": len(valid_deltas),
            "contaminated_pairs": [
                {"pair": delta.pair, "reason": delta.contamination_reason}
                for delta in mode_deltas
                if delta.contaminated
            ],
            "baseline_times_ms": baseline_times,
            "candidate_times_ms": candidate_times,
            "baseline_nps": baseline_nps,
            "candidate_nps": candidate_nps,
            "baseline_median_time_ms": baseline_median,
            "baseline_mad_time_ms": baseline_mad,
            "baseline_three_mad_over_median_percent": baseline_noise,
            "candidate_median_time_ms": candidate_median,
            "candidate_mad_time_ms": candidate_mad,
            "candidate_three_mad_over_median_percent": candidate_noise,
            "elapsed_median_improvement_percent": (
                100.0 * (baseline_median - candidate_median)
                / max(baseline_median, 1.0)
            ),
            "baseline_median_nps": float(statistics.median(baseline_nps)),
            "candidate_median_nps": float(statistics.median(candidate_nps)),
            "candidate_pair_wins": sum(delta.candidate_won for delta in valid_deltas),
            "nodes": reference_signature[5],
            "checksum": reference_signature[6],
            "python_recomputed_checksum": reference_signature[7],
            "deterministic_signature_equal": True,
        }

    write_tsv(output_dir / "paired_bench_samples.tsv", samples)
    write_tsv(output_dir / "paired_bench_positions.tsv", positions_out)
    write_tsv(output_dir / "paired_bench_deltas.tsv", deltas)
    return samples, positions_out, deltas, summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--net", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--expected-baseline-sha256")
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument(
        "--paired-performance",
        action="store_true",
        help="run pinned baseline/candidate warm-ups and measured ABBA pairs",
    )
    parser.add_argument(
        "--contaminated-pair",
        action="append",
        default=[],
        metavar="MODE:PAIR:RECORDED_REASON",
        help="retain but exclude an externally contaminated whole pair",
    )
    args = parser.parse_args()

    if args.repetitions < 5:
        raise ValueError("--repetitions must be at least 5")
    if args.paired_performance and args.repetitions != 10:
        raise ValueError("paired performance mode requires exactly 10 repetitions")
    if args.paired_performance:
        missing_pins = [
            option
            for option, value in (
                ("--expected-baseline-sha256", args.expected_baseline_sha256),
                ("--expected-candidate-sha256", args.expected_candidate_sha256),
            )
            if value is None
        ]
        if missing_pins:
            raise ValueError(
                "paired performance mode requires both artifact SHA-256 pins; "
                f"missing {', '.join(missing_pins)}"
            )
        normalize_expected_sha256(
            args.expected_baseline_sha256, "expected baseline SHA-256"
        )
        normalize_expected_sha256(
            args.expected_candidate_sha256, "expected candidate SHA-256"
        )
    baseline_path, candidate_path, baseline_sha256, candidate_sha256 = (
        resolve_distinct_artifacts(
            args.baseline,
            args.candidate,
            args.expected_baseline_sha256,
            args.expected_candidate_sha256,
        )
    )
    net = args.net.resolve(strict=True)
    if not net.is_file():
        raise FileNotFoundError(net)

    net_hash = digest(net, "sha256")
    for engine in (baseline_path, candidate_path):
        sibling_net = engine.resolve().parent / "pyro.nnue"
        if not sibling_net.is_file():
            raise FileNotFoundError(sibling_net)
        if digest(sibling_net, "sha256") != net_hash:
            raise AssertionError(f"{sibling_net}: net hash differs from --net")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    fixed_rows: list[FixedResult] = []
    print("Checking fixed-depth baseline/candidate decision tuples...", flush=True)
    for mode in ("nnue", "pesto"):
        for label, fen in SUITE:
            baseline_result = fixed_search(
                baseline_path, mode, label, fen, args.timeout_seconds
            )
            candidate_result = fixed_search(
                candidate_path, mode, label, fen, args.timeout_seconds
            )
            if baseline_result.decision_tuple() != candidate_result.decision_tuple():
                raise AssertionError(
                    f"{mode}/{label}: decision tuple changed: "
                    f"baseline={baseline_result.decision_tuple()} "
                    f"candidate={candidate_result.decision_tuple()}"
                )
            if (
                candidate_result.nodes is None
                or candidate_result.time_ms is None
                or candidate_result.nps is None
            ):
                raise AssertionError(f"{mode}/{label}: candidate omitted search statistics")
            if args.paired_performance:
                if (
                    baseline_result.nodes is None
                    or baseline_result.time_ms is None
                    or baseline_result.nps is None
                ):
                    raise AssertionError(
                        f"{mode}/{label}: metric-bearing baseline omitted search statistics"
                    )
                if baseline_result.nodes != candidate_result.nodes:
                    raise AssertionError(
                        f"{mode}/{label}: fixed-depth nodes changed: "
                        f"baseline={baseline_result.nodes} candidate={candidate_result.nodes}"
                    )
            fixed_rows.extend((baseline_result, candidate_result))
    write_tsv(output_dir / "fixed_depth_equivalence.tsv", fixed_rows)

    if args.paired_performance:
        contaminated = parse_contaminated_pairs(
            args.contaminated_pair, args.repetitions
        )
        _samples, _positions, _deltas, performance_summary = run_paired_performance(
            baseline_path,
            candidate_path,
            args.timeout_seconds,
            args.repetitions,
            contaminated,
            output_dir,
        )
        signatures = {
            mode: (
                None,
                None,
                None,
                None,
                None,
                performance_summary[mode]["nodes"],
                performance_summary[mode]["checksum"],
                performance_summary[mode]["python_recomputed_checksum"],
            )
            for mode in ("nnue", "pesto")
        }
    else:
        performance_summary = None
        bench_runs: list[BenchRun] = []
        bench_positions: list[BenchPosition] = []
        signatures: dict[str, tuple[object, ...]] = {}
        for mode in ("nnue", "pesto"):
            print(f"Running excluded {mode} warm-up...", flush=True)
            run_bench(candidate_path, mode, 0, args.timeout_seconds)
            for repetition in range(1, args.repetitions + 1):
                run, positions = run_bench(
                    candidate_path, mode, repetition, args.timeout_seconds
                )
                signature = deterministic_signature(run, positions)
                if mode in signatures and signature != signatures[mode]:
                    raise AssertionError(
                        f"bench {mode} repetition {repetition}: deterministic fields changed"
                    )
                signatures.setdefault(mode, signature)
                bench_runs.append(run)
                bench_positions.extend(positions)
                print(
                    f"mode={mode} repetition={repetition} nodes={run.nodes} "
                    f"time={run.time_ms} nps={run.nps} checksum={run.checksum}",
                    flush=True,
                )

        write_tsv(output_dir / "bench_runs.tsv", bench_runs)
        write_tsv(output_dir / "bench_positions.tsv", bench_positions)
    summary = {
        "baseline": file_metadata(baseline_path, baseline_sha256),
        "candidate": file_metadata(candidate_path, candidate_sha256),
        "net": file_metadata(net, net_hash),
        "fixed_depth": DEPTH,
        "fixed_positions_per_mode": len(SUITE),
        "decision_tuples_identical": True,
        "candidate_stats_present": True,
        "artifacts_distinct": True,
        "expected_baseline_sha256": normalize_expected_sha256(
            args.expected_baseline_sha256, "expected baseline SHA-256"
        ),
        "expected_candidate_sha256": normalize_expected_sha256(
            args.expected_candidate_sha256, "expected candidate SHA-256"
        ),
        "bench_version": 1,
        "bench_repetitions_per_mode": args.repetitions,
        "paired_performance_mode": args.paired_performance,
        "bench_deterministic": True,
        "python_checksums_match_engine": True,
        "bench": {
            mode: {
                "nodes": signatures[mode][5],
                "checksum": signatures[mode][6],
                "python_recomputed_checksum": signatures[mode][7],
            }
            for mode in ("nnue", "pesto")
        },
        "performance": performance_summary,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"PASS: reports written to {output_dir}", flush=True)


if __name__ == "__main__":
    main()
