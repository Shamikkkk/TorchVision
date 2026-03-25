"""
Download a Lichess rated-games PGN database file (compressed, .zst).

Usage (from backend/):
    python -m model_training.download --year 2024 --month 1 --out data/

Saves the compressed .zst file to disk — much smaller than the decompressed
PGN (typically 1–3 GB vs 15–30 GB). parse.py and stream_parse.py both accept
.zst files and decompress on the fly, so you never need the raw PGN on disk.

Progress is printed every 50 MB of compressed data received.
"""

import argparse
from pathlib import Path

import requests
import zstandard as zstd

_LICHESS_IP   = "141.95.66.62"
_LICHESS_HOST = "database.lichess.org"
_BASE_PATH    = "/standard"


def _url(year: int, month: int) -> str:
    filename = f"lichess_db_standard_rated_{year}-{month:02d}.pgn.zst"
    return f"http://{_LICHESS_IP}{_BASE_PATH}/{filename}"


def download(year: int, month: int, out_dir: Path) -> Path:
    filename = f"lichess_db_standard_rated_{year}-{month:02d}.pgn.zst"
    out_path = out_dir / filename
    url = _url(year, month)

    if out_path.exists():
        print(f"[download] {out_path} already exists — skipping.")
        return out_path

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[download] Fetching {url}")
    print(f"[download] Saving compressed archive to {out_path}")

    with requests.get(
        url, stream=True, timeout=60, headers={"Host": _LICHESS_HOST}
    ) as resp:
        resp.raise_for_status()
        total = 0
        chunk_size = 1 << 20  # 1 MB
        report_every = 50 * chunk_size  # 50 MB
        with open(out_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                total += len(chunk)
                if total % report_every < chunk_size:
                    print(f"[download]   {total / (1 << 20):.0f} MB received…", flush=True)

    print(f"[download] Done → {out_path}  ({total / (1 << 20):.0f} MB)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a Lichess PGN month (saves compressed .zst)."
    )
    parser.add_argument("--year",  type=int, required=True, help="e.g. 2024")
    parser.add_argument("--month", type=int, required=True, help="1–12")
    parser.add_argument("--out",   type=Path, default=Path("data"),
                        help="Output directory (default: data/)")
    args = parser.parse_args()
    download(args.year, args.month, args.out)


if __name__ == "__main__":
    main()
