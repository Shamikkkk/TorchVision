"""
Download PGN collections for historical GMs from pgnmentor.com.

Each zip contains one or more .pgn files which are extracted and merged
into a single <Name>.pgn in backend/data/.

Usage (from backend/):
    python scripts/download_historical_pgns.py
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://www.pgnmentor.com/players"

PLAYERS: list[str] = [
    # Already in repo
    "Tal",              # Mikhail Tal, 2431 games
    "Kasparov",         # Garry Kasparov, 2128 games
    "Fischer",          # Robert James Fischer, 827 games
    "Carlsen",          # Magnus Carlsen, 6615 games

    # Classical / positional giants
    "Karpov",           # Anatoly Karpov, 3529 games
    "Petrosian",        # Tigran Petrosian, 1893 games
    "Spassky",          # Boris Spassky, 2231 games
    "Smyslov",          # Vasily Smyslov, 2627 games
    "Korchnoi",         # Viktor Korchnoi, 4569 games
    "Capablanca",       # Jose Raul Capablanca, 597 games

    # Romantic / attacking era
    "Morphy",           # Paul Morphy, 211 games
    "Anderssen",        # Adolf Anderssen, 681 games
    "Spielmann",        # Rudolf Spielmann, 1057 games
    "Alekhine",         # Alexander Alekhine, 1661 games
    "Najdorf",          # Miguel Najdorf, 1604 games

    # Soviet attacking school
    "Bronstein",        # David Bronstein, 1930 games
    "Geller",           # Efim Geller, 2198 games
    "Larsen",           # Bent Larsen, 2383 games
    "Ljubojevic",       # Ljubomir Ljubojevic, 1944 games

    # Modern attacking players
    "Shirov",           # Alexei Shirov, 5644 games
    "Topalov",          # Veselin Topalov, 2614 games
    "Morozevich",       # Alexander Morozevich, 2753 games
    "Ivanchuk",         # Vassily Ivanchuk, 4950 games
    "Grischuk",         # Alexander Grischuk, 5918 games
    "Aronian",          # Levon Aronian, 5107 games
    "Nakamura",         # Hikaru Nakamura, 8727 games
    "VachierLagrave",   # Maxime Vachier-Lagrave, 5106 games
    "Jobava",           # Baadur Jobava, 4440 games
    "Rapport",          # Richard Rapport, 2040 games
    "Firouzja",         # Alireza Firouzja, 4204 games
    "Gukesh",           # Dommaraju Gukesh, 2053 games
    "Praggnanandhaa",   # Rameshbabu Praggnanandhaa, 2443 games

    # NOT on pgnmentor — 404 expected, skipped gracefully
    # "Nezhmetdinov"
    # "Gurgenidze"
    # "Nijdorf"          # use Najdorf above
]

_BACKEND  = Path(__file__).resolve().parent.parent
_DATA_DIR = _BACKEND / "data"

REQUEST_SLEEP = 1.0   # seconds between downloads (be polite)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_zip(url: str) -> bytes | None:
    """Download *url* and return raw bytes, or None on 404 / error."""
    headers = {"User-Agent": "TorchChess-pgn-downloader/1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 404:
            print(f"  [404] Not found: {url}")
            return None
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        print(f"  [error] {url} — {exc}")
        return None


def _extract_pgn(zip_bytes: bytes, player: str) -> str | None:
    """
    Extract all .pgn files from *zip_bytes* and concatenate their contents.
    Returns the combined PGN text, or None if the zip contains no .pgn files.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            pgn_names = [n for n in zf.namelist() if n.lower().endswith(".pgn")]
            if not pgn_names:
                print(f"  [warn] {player}.zip contains no .pgn files: {zf.namelist()}")
                return None
            parts: list[str] = []
            for name in pgn_names:
                raw = zf.read(name)
                try:
                    parts.append(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    parts.append(raw.decode("latin-1"))
            return "\n\n".join(parts)
    except zipfile.BadZipFile as exc:
        print(f"  [error] Bad zip for {player}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _count_games(path: Path) -> int:
    """Count [Event tags in an existing PGN file without loading it fully."""
    count = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("[Event "):
                count += 1
    return count


def run() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    ok:          list[str] = []
    fail:        list[str] = []
    total_games: int       = 0

    for player in PLAYERS:
        url      = f"{BASE_URL}/{player}.zip"
        out_path = _DATA_DIR / f"{player}.pgn"

        if out_path.exists():
            games = _count_games(out_path)
            total_games += games
            print(f"[skip] {player}.pgn already exists ({games:,} games)")
            ok.append(player)
            continue

        print(f"Downloading {player}.zip … ", end="", flush=True)
        zip_bytes = _download_zip(url)
        time.sleep(REQUEST_SLEEP)

        if zip_bytes is None:
            fail.append(player)
            continue

        pgn_text = _extract_pgn(zip_bytes, player)
        if pgn_text is None:
            fail.append(player)
            continue

        out_path.write_text(pgn_text, encoding="utf-8")
        games = pgn_text.count("[Event ")
        total_games += games
        print(f"{len(zip_bytes) / 1024:.0f} KB → {games:,} games → {out_path.name}")
        ok.append(player)

    print()
    print(f"Total games across all PGNs: {total_games:,}")
    print(f"Done. {len(ok)} succeeded: {', '.join(ok)}")
    if fail:
        print(f"      {len(fail)} failed:    {', '.join(fail)}")
        print("      Check spellings at https://www.pgnmentor.com/files.html#players")


if __name__ == "__main__":
    run()
