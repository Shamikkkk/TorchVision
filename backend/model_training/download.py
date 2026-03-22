"""
Download and decompress a Lichess rated-games PGN database file.

Usage (from backend/):
    python -m model_training.download --year 2024 --month 1 --out data/

The Lichess database URL format:
    https://database.lichess.org/standard/lichess_db_standard_rated_YYYY-MM.pgn.zst

Files are large (10–30 GB compressed). This script streams and decompresses
on the fly so you never need to hold the full compressed file in RAM.

Progress is printed every 50 MB of compressed data received.
"""

import argparse
import sys
from pathlib import Path

import requests
import zstandard as zstd

_BASE_URL = "https://database.lichess.org/standard"


def download(year: int, month: int, out_dir: Path) -> Path:
    filename = f"lichess_db_standard_rated_{year}-{month:02d}.pgn"
    url = f"{_BASE_URL}/{filename}.zst"
    out_path = out_dir / filename

    if out_path.exists():
        print(f"[download] {out_path} already exists — skipping download.")
        return out_path

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[download] Fetching {url}")
    print(f"[download] Writing decompressed PGN to {out_path}")

    dctx = zstd.ZstdDecompressor()

    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total_compressed = 0
        with open(out_path, "wb") as out_fh:
            with dctx.stream_reader(resp.raw) as reader:
                chunk_size = 1 << 20  # 1 MB
                while True:
                    chunk = reader.read(chunk_size)
                    if not chunk:
                        break
                    out_fh.write(chunk)
                    total_compressed += len(chunk)
                    if total_compressed % (50 * 1 << 20) < chunk_size:
                        mb = total_compressed / (1 << 20)
                        print(f"[download]   {mb:.0f} MB decompressed…", flush=True)

    print(f"[download] Done → {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a Lichess PGN database month.")
    parser.add_argument("--year",  type=int, required=True, help="e.g. 2024")
    parser.add_argument("--month", type=int, required=True, help="1–12")
    parser.add_argument("--out",   type=Path, default=Path("data"), help="Output directory")
    args = parser.parse_args()
    download(args.year, args.month, args.out)


if __name__ == "__main__":
    main()
