"""Exact integer reference and v2 serializer for the Phase D SCReLU-512 net.

This module deliberately does not share inference code with Rust. It derives the
same integers independently from Bullet's raw float32 export, using Bullet's
documented/save-code rounding semantics, and is used by the exhaustive agreement
harness.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

INPUT_SIZE = 768
HIDDEN_SIZE = 512
QA = 255
QB = 64
SCALE = 400

MAGIC = b"NNUE"
FORMAT_VERSION = 2
ACTIVATION_SCRELU = 2
HEADER = struct.Struct("<4s7I")

CHAMPION_SHA256 = "50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184"
RAW_FLOATS = INPUT_SIZE * HIDDEN_SIZE + HIDDEN_SIZE + 2 * HIDDEN_SIZE + 1
PAYLOAD_BYTES = RAW_FLOATS * 2
FILE_BYTES = HEADER.size + PAYLOAD_BYTES

PIECE_MAP = {
    "P": 0,
    "N": 1,
    "B": 2,
    "R": 3,
    "Q": 4,
    "K": 5,
    "p": 0,
    "n": 1,
    "b": 2,
    "r": 3,
    "q": 4,
    "k": 5,
}


@dataclass(frozen=True)
class QuantizedNetwork:
    ft_weights: np.ndarray
    ft_bias: np.ndarray
    out_weights: np.ndarray
    out_bias: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bullet_round_i16(values: np.ndarray, multiplier: int) -> np.ndarray:
    """Mirror Bullet QuantTarget::I16 with SavedFormat::round().

    Bullet converts each f32 to f64, multiplies in f64, then uses Rust
    f64::round (half away from zero) before checking that the value fits i16.
    """

    scaled = values.astype(np.float64) * float(multiplier)
    rounded = np.where(scaled >= 0.0, np.floor(scaled + 0.5), np.ceil(scaled - 0.5))
    if not np.all(np.isfinite(rounded)):
        raise ValueError("non-finite value encountered during Bullet quantization")
    if np.any(rounded < np.iinfo(np.int16).min) or np.any(rounded > np.iinfo(np.int16).max):
        low = float(np.min(rounded))
        high = float(np.max(rounded))
        raise ValueError(f"quantized value outside i16: range [{low}, {high}]")
    return rounded.astype("<i2")


def load_champion_raw(path: Path, *, verify_hash: bool = True) -> QuantizedNetwork:
    path = path.resolve()
    if verify_hash:
        actual_hash = sha256_file(path)
        if actual_hash != CHAMPION_SHA256:
            raise ValueError(
                f"champion raw SHA-256 mismatch: {actual_hash} "
                f"(expected {CHAMPION_SHA256})"
            )

    raw = np.fromfile(path, dtype="<f4")
    if raw.size != RAW_FLOATS:
        raise ValueError(
            f"raw float count {raw.size:,}, expected exactly {RAW_FLOATS:,} "
            f"for 768->512x2->1"
        )

    n_l0w = INPUT_SIZE * HIDDEN_SIZE
    l0w = raw[:n_l0w].reshape(INPUT_SIZE, HIDDEN_SIZE)
    l0b = raw[n_l0w : n_l0w + HIDDEN_SIZE]
    l1w = raw[n_l0w + HIDDEN_SIZE : n_l0w + HIDDEN_SIZE + 2 * HIDDEN_SIZE]
    l1b = raw[-1:]

    return QuantizedNetwork(
        ft_weights=_bullet_round_i16(l0w, QA),
        ft_bias=_bullet_round_i16(l0b, QA),
        out_weights=_bullet_round_i16(l1w, QB),
        out_bias=int(_bullet_round_i16(l1b, QA * QB)[0]),
    )


def _payload(net: QuantizedNetwork) -> bytes:
    payload = b"".join(
        (
            np.asarray(net.ft_weights, dtype="<i2").tobytes(order="C"),
            np.asarray(net.ft_bias, dtype="<i2").tobytes(order="C"),
            np.asarray(net.out_weights, dtype="<i2").tobytes(order="C"),
            struct.pack("<h", net.out_bias),
        )
    )
    if len(payload) != PAYLOAD_BYTES:
        raise AssertionError(f"payload size {len(payload)}, expected {PAYLOAD_BYTES}")
    return payload


def write_versioned_net(
    raw_path: Path,
    output_path: Path,
    *,
    protected_paths: tuple[Path, ...] = (),
) -> QuantizedNetwork:
    raw_path = raw_path.resolve()
    output_path = output_path.resolve()
    protected = {path.resolve() for path in protected_paths}
    if output_path in protected:
        raise ValueError(f"refusing to overwrite protected live net: {output_path}")

    net = load_champion_raw(raw_path)
    header = HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        ACTIVATION_SCRELU,
        INPUT_SIZE,
        HIDDEN_SIZE,
        QA,
        QB,
        SCALE,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + _payload(net))
    if output_path.stat().st_size != FILE_BYTES:
        raise AssertionError(
            f"versioned net size {output_path.stat().st_size}, expected {FILE_BYTES}"
        )

    loaded = load_versioned_net(output_path)
    for field in ("ft_weights", "ft_bias", "out_weights"):
        if not np.array_equal(getattr(net, field), getattr(loaded, field)):
            raise AssertionError(f"versioned net round-trip mismatch in {field}")
    if net.out_bias != loaded.out_bias:
        raise AssertionError("versioned net round-trip mismatch in out_bias")
    return net


def load_versioned_net(path: Path) -> QuantizedNetwork:
    data = path.read_bytes()
    if len(data) != FILE_BYTES:
        raise ValueError(f"versioned net is {len(data)} bytes, expected {FILE_BYTES}")
    fields = HEADER.unpack_from(data)
    expected = (
        MAGIC,
        FORMAT_VERSION,
        ACTIVATION_SCRELU,
        INPUT_SIZE,
        HIDDEN_SIZE,
        QA,
        QB,
        SCALE,
    )
    if fields != expected:
        raise ValueError(f"versioned net header mismatch: {fields!r} != {expected!r}")

    offset = HEADER.size
    n_l0w = INPUT_SIZE * HIDDEN_SIZE
    ft_weights = np.frombuffer(data, dtype="<i2", count=n_l0w, offset=offset).copy()
    ft_weights = ft_weights.reshape(INPUT_SIZE, HIDDEN_SIZE)
    offset += n_l0w * 2
    ft_bias = np.frombuffer(data, dtype="<i2", count=HIDDEN_SIZE, offset=offset).copy()
    offset += HIDDEN_SIZE * 2
    out_weights = np.frombuffer(
        data, dtype="<i2", count=2 * HIDDEN_SIZE, offset=offset
    ).copy()
    offset += 2 * HIDDEN_SIZE * 2
    out_bias = struct.unpack_from("<h", data, offset)[0]
    return QuantizedNetwork(ft_weights, ft_bias, out_weights, out_bias)


def feature_index(perspective_white: bool, square: int, piece_type: int, is_white: bool) -> int:
    mirrored_square = square if perspective_white else square ^ 56
    color_index = 0 if is_white == perspective_white else 1
    return color_index * 384 + piece_type * 64 + mirrored_square


def fen_to_pieces(fen: str) -> tuple[list[tuple[int, int, bool]], bool]:
    fields = fen.split()
    if len(fields) < 2:
        raise ValueError(f"FEN has fewer than two fields: {fen}")
    ranks = fields[0].split("/")
    if len(ranks) != 8:
        raise ValueError(f"FEN has {len(ranks)} ranks: {fen}")

    pieces: list[tuple[int, int, bool]] = []
    for rank_index, rank_text in enumerate(ranks):
        rank = 7 - rank_index
        file_index = 0
        for char in rank_text:
            if char.isdigit():
                file_index += int(char)
            else:
                if char not in PIECE_MAP or file_index >= 8:
                    raise ValueError(f"invalid piece placement in FEN: {fen}")
                pieces.append(
                    (rank * 8 + file_index, PIECE_MAP[char], char.isupper())
                )
                file_index += 1
        if file_index != 8:
            raise ValueError(f"rank does not contain eight squares in FEN: {fen}")

    if fields[1] not in ("w", "b"):
        raise ValueError(f"invalid side to move in FEN: {fen}")
    return pieces, fields[1] == "w"


def accumulators(net: QuantizedNetwork, fen: str) -> tuple[np.ndarray, np.ndarray, bool]:
    pieces, white_to_move = fen_to_pieces(fen)
    white = net.ft_bias.astype(np.int32).copy()
    black = net.ft_bias.astype(np.int32).copy()
    for square, piece_type, is_white in pieces:
        white += net.ft_weights[
            feature_index(True, square, piece_type, is_white)
        ].astype(np.int32)
        black += net.ft_weights[
            feature_index(False, square, piece_type, is_white)
        ].astype(np.int32)
    return white, black, white_to_move


def trunc_div(numerator: int, denominator: int) -> int:
    """Signed integer division truncating toward zero, like Rust."""

    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return numerator // denominator
    return -((-numerator) // denominator)


def screlu_square(value: int) -> int:
    q = max(0, min(QA, value))
    return q * q


def evaluate(
    net: QuantizedNetwork,
    white_acc: np.ndarray,
    black_acc: np.ndarray,
    white_to_move: bool,
) -> int:
    stm = white_acc if white_to_move else black_acc
    nstm = black_acc if white_to_move else white_acc
    q_stm = np.clip(stm, 0, QA).astype(np.int64)
    q_nstm = np.clip(nstm, 0, QA).astype(np.int64)
    activation_sum = int(
        np.sum(
            q_stm * q_stm * net.out_weights[:HIDDEN_SIZE].astype(np.int64),
            dtype=np.int64,
        )
        + np.sum(
            q_nstm
            * q_nstm
            * net.out_weights[HIDDEN_SIZE:].astype(np.int64),
            dtype=np.int64,
        )
    )
    normalized = trunc_div(activation_sum, QA)
    biased = normalized + net.out_bias
    return trunc_div(biased * SCALE, QA * QB)
