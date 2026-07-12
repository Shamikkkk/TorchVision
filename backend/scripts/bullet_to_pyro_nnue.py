"""
Convert Bullet's quantised.bin output to pyro.nnue format.

Bullet saves weights in this order (raw i16 LE, no header):
  ft_weights : [768][256] i16  (feature_weights, column per input feature)
  ft_bias    : [256]      i16
  out_weights: [512]      i16  (STM half then NSTM half)
  out_bias   : [1]        i16

Bullet appends a variable-length "bullet"-repeated footer signature
after the weight data. This converter strips it before writing.

pyro.nnue format (engine/src/nnue.rs):
  magic   : [0x4E, 0x4E, 0x55, 0x45]  ("NNUE")
  version : u32 LE  (= 1)
  ft_weights, ft_bias, out_weights, out_bias  (same layout as Bullet)

The weight layouts are identical — just strip the footer and prepend
the 8-byte header.

Usage:
    python -m scripts.bullet_to_pyro_nnue \\
        --input  ../bullet/checkpoints/pyro-d1/pyro-d1-30/quantised.bin \\
        --output ../engine/pyro.nnue
"""

import argparse
import os
import struct


HIDDEN_SIZE  = 256   # default; override with --hidden (engine loader is 256-only)
INPUT_SIZE   = 768
MAGIC        = b"\x4E\x4E\x55\x45"   # "NNUE"
VERSION      = 1


def expected_weights_bytes(hidden: int) -> int:
    return (
        INPUT_SIZE * hidden * 2   # ft_weights  [768][hidden] i16
        + hidden * 2              # ft_bias     [hidden] i16
        + hidden * 2 * 2          # out_weights [2*hidden] i16
        + 2                       # out_bias    [1]  i16
    )


BULLET_FOOTER = b"bullet"


def strip_bullet_footer(data: bytes, expected_bytes: int) -> bytes:
    """Strip Bullet's repeated 'bullet' footer signature from weight bytes."""
    if len(data) == expected_bytes:
        return data
    if len(data) > expected_bytes:
        trailer = data[expected_bytes:]
        # Verify it is all "bullet" repetitions (any partial tail is fine)
        expected_repeat = (BULLET_FOOTER * ((len(trailer) // len(BULLET_FOOTER)) + 1))[:len(trailer)]
        if trailer == expected_repeat:
            print(f"Stripped {len(trailer)}-byte Bullet footer signature.")
            return data[:expected_bytes]
    raise ValueError(
        f"File size {len(data):,} does not match expected {expected_bytes:,} "
        f"and does not appear to have a recognisable Bullet footer."
    )


def write_nnue(path: str, payload: bytes, expected_bytes: int) -> None:
    """Write header + weights to path and verify."""
    with open(path, "wb") as fout:
        fout.write(MAGIC)
        fout.write(struct.pack("<I", VERSION))
        fout.write(payload)
    out_size = os.path.getsize(path)
    assert out_size == 8 + expected_bytes, "Output size mismatch"
    with open(path, "rb") as f:
        magic_read = f.read(4)
        ver_read   = struct.unpack("<I", f.read(4))[0]
    assert magic_read == MAGIC,   f"Magic mismatch: {magic_read!r}"
    assert ver_read   == VERSION, f"Version mismatch: {ver_read}"
    print(f"  Written and verified: {path}  ({out_size:,} bytes)")


def convert(input_path: str, output_path: str, hidden: int = HIDDEN_SIZE) -> None:
    expected_bytes = expected_weights_bytes(hidden)
    file_size = os.path.getsize(input_path)
    print(f"Input : {input_path}  ({file_size:,} bytes, hidden={hidden})")

    with open(input_path, "rb") as fin:
        raw = fin.read()

    weights = strip_bullet_footer(raw, expected_bytes)

    if len(weights) != expected_bytes:
        raise ValueError(
            f"Weight block is {len(weights):,} bytes, expected {expected_bytes:,}. "
            f"Make sure --hidden {hidden} matches your training config."
        )

    if hidden != 256:
        print(f"  WARNING: engine/src/nnue.rs loads HIDDEN=256 only — a {hidden}-wide "
              f"net needs a matching engine build.")

    # Write to primary output path
    write_nnue(output_path, weights, expected_bytes)

    # The engine binary searches for pyro.nnue next to the executable
    # (engine/target/release/pyro.nnue) BEFORE the current directory.
    # Mirror the file there so the engine always loads the freshest weights.
    exe_dir_copy = os.path.join(
        os.path.dirname(output_path), "target", "release", "pyro.nnue"
    )
    if os.path.isdir(os.path.dirname(exe_dir_copy)):
        write_nnue(exe_dir_copy, weights, expected_bytes)
        print(f"  (mirrored to engine binary directory)")
    else:
        print(f"  (skipped mirror: {exe_dir_copy} — directory not found)")

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Bullet .bin weights to pyro.nnue format"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Bullet checkpoint .bin file (e.g. bullet/checkpoints/pyro-d2v1/pyro-d2v1-30/quantised.bin)",
    )
    parser.add_argument(
        "--output",
        default="C:/Users/shami/OneDrive/Documents/torch/engine/pyro.nnue",
        help="Output path for pyro.nnue (default: engine/pyro.nnue)",
    )
    parser.add_argument(
        "--hidden",
        type=int,
        default=HIDDEN_SIZE,
        help="Hidden size of the trained net (default 256; engine loader is 256-only)",
    )
    args = parser.parse_args()
    convert(args.input, args.output, args.hidden)


if __name__ == "__main__":
    main()
