"""
Convert selfplay .plain format to Bullet binary format (STM-normalised).

Input:  FEN | eval_cp_stm | result_white
        eval_cp_stm  = centipawns from side-to-move perspective (positive = STM winning)
        result_white = 1.0 / 0.5 / 0.0 (white wins / draw / black wins)

Output: 32-byte BulletFormat per position, STM-normalised so that:
        - bit3=0 in pcs nibble  ← STM's piece (friendly)
        - bit3=1 in pcs nibble  ← NSTM's piece (opponent)
        - squares are mirrored (sq^56) when black is to move
        - score is STM-relative (positive = STM winning)
        - result is STM-relative (2 = STM wins, 0 = STM loses)

        This matches what bulletformat::ChessBoard::from_raw and
        ChessBoard::FromStr produce internally — Bullet's Chess768 input
        then correctly puts STM pieces in features [0,383] and NSTM in
        [384,767] regardless of which colour is moving.

        occ      u64  (offset  0): occupancy bitboard in STM-normalised squares
        pcs    [u8;16](offset  8): nibbles, sorted by normalised sq ascending
        score    i16  (offset 24): STM-relative centipawns
        result    u8  (offset 26): 2=STM wins, 1=Draw, 0=STM loses
        ksq       u8  (offset 27): STM king square (normalised)
        opp_ksq   u8  (offset 28): NSTM king square (normalised, then XOR 56 for white-STM
                                    positions; raw for black-STM positions — unused by Chess768)
        extra  [u8;3] (offset 29): padding zeros

Usage:
    python -m scripts.convert_plain_to_bullet \\
        --input  data/selfplay_d6_combined.plain \\
        --output data/selfplay_d6.data \\
        [--limit 1000]   # for smoke test
"""

import argparse
import struct
import sys
import time

import chess


def encode_position(fen: str, eval_stm: int, result_white: float) -> bytes:
    board = chess.Board(fen)
    white_to_move = board.turn == chess.WHITE

    # Score: STM-relative — eval_stm is already from the side-to-move's perspective.
    score = max(-32767, min(32767, eval_stm))

    # Result: STM-relative (2 = STM wins, 0 = STM loses).
    result_key = round(result_white * 2) / 2
    if white_to_move:
        # white is STM: white win → STM win = 2
        result = {0.0: 0, 0.5: 1, 1.0: 2}[result_key]
    else:
        # black is STM: black win (result_white=0.0) → STM win = 2
        result = {0.0: 2, 0.5: 1, 1.0: 0}[result_key]

    # Build piece list normalised to STM perspective.
    # When black to move: mirror squares (sq^56) and treat black as "friendly" (bit3=0).
    # Bullet's Chess768 encodes: bit3=0 → STM pieces → features [0,383]
    #                            bit3=1 → NSTM pieces → features [384,767]
    pieces: list[tuple[int, int]] = []  # (normalised_sq, nibble)
    temp = int(board.occupied)
    while temp:
        lsb = temp & (-temp)
        raw_sq = lsb.bit_length() - 1
        piece = board.piece_at(raw_sq)

        if white_to_move:
            norm_sq = raw_sq
            is_stm = (piece.color == chess.WHITE)
        else:
            norm_sq = raw_sq ^ 56          # mirror board rank
            is_stm = (piece.color == chess.BLACK)

        color_bit = 0 if is_stm else 1    # 0 = STM (friendly), 1 = NSTM (opponent)
        type_bits = piece.piece_type - 1  # chess.PAWN=1 → 0, ..., chess.KING=6 → 5
        pieces.append((norm_sq, (color_bit << 3) | type_bits))
        temp ^= lsb

    # After mirroring, ascending square order may change — re-sort.
    if not white_to_move:
        pieces.sort()

    # Build occupancy bitboard from normalised squares.
    occ = 0
    for norm_sq, _ in pieces:
        occ |= (1 << norm_sq)

    # Pack nibbles.
    pcs = bytearray(16)
    for i, (_, nib) in enumerate(pieces):
        if i % 2 == 0:
            pcs[i // 2] = nib
        else:
            pcs[i // 2] |= nib << 4

    # King squares (STM = ksq, NSTM = opp_ksq). Chess768 doesn't use these,
    # but populate them correctly for future king-bucket compatibility.
    if white_to_move:
        ksq = board.king(chess.WHITE)
        opp_ksq = board.king(chess.BLACK) ^ 56
    else:
        ksq = board.king(chess.BLACK) ^ 56  # STM (black) king in normalised coords
        opp_ksq = board.king(chess.WHITE)   # NSTM (white) king raw sq

    return (
        struct.pack("<Q", occ)          # 8 bytes
        + bytes(pcs)                    # 16 bytes
        + struct.pack("<h", score)      # 2 bytes
        + struct.pack("<B", result)     # 1 byte
        + struct.pack("<B", ksq)        # 1 byte
        + struct.pack("<B", opp_ksq)    # 1 byte
        + b"\x00\x00\x00"              # 3 bytes padding
    )  # total: 32 bytes


def convert(input_path: str, output_path: str, limit: int | None) -> None:
    t0 = time.time()
    written = 0
    skipped = 0
    report_every = 500_000

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "wb") as fout:

        for lineno, line in enumerate(fin, 1):
            if limit is not None and written >= limit:
                break

            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) != 3:
                skipped += 1
                continue

            fen_str = parts[0].strip()
            try:
                eval_stm = int(parts[1].strip())
                result_white = float(parts[2].strip())
            except ValueError:
                skipped += 1
                continue

            try:
                record = encode_position(fen_str, eval_stm, result_white)
            except Exception:
                skipped += 1
                continue

            fout.write(record)
            written += 1

            if written % report_every == 0:
                elapsed = time.time() - t0
                rate = written / elapsed if elapsed > 0 else 0
                print(f"  Converted {written:,} positions  ({rate:,.0f} pos/s)", flush=True)

    elapsed = time.time() - t0
    size_mb = written * 32 / 1_048_576
    print(f"\nDone: {written:,} positions written, {skipped:,} skipped")
    print(f"Output: {output_path}  ({size_mb:.1f} MB)")
    print(f"Elapsed: {elapsed:.1f}s  ({written/elapsed:,.0f} pos/s)" if elapsed > 0 else "")
    assert written * 32 == __import__("os").path.getsize(output_path), \
        "File size mismatch — output may be corrupt"
    print("Integrity check: OK (file size matches record count)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert .plain selfplay data to Bullet binary format")
    parser.add_argument("--input",  default="data/selfplay_d6_combined.plain",
                        help="Input .plain file")
    parser.add_argument("--output", default="data/selfplay_d6.data",
                        help="Output Bullet .data file")
    parser.add_argument("--limit",  type=int, default=None,
                        help="Stop after N positions (for smoke testing)")
    args = parser.parse_args()

    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    if args.limit:
        print(f"Limit:  {args.limit:,} positions (smoke test)")
    print()

    convert(args.input, args.output, args.limit)


if __name__ == "__main__":
    main()
