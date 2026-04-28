"""NNUE vs PeSTO SPRT validation via cutechess-cli.

Runs a Sequential Probability Ratio Test comparing the freshly-trained
NNUE-loaded pyro against the PeSTO-only baseline.

Test parameters:
  H0: Elo difference = 0  (no improvement)
  H1: Elo difference = 10 (real improvement)
  alpha = beta = 0.05     (5% Type I and Type II error rates)

The test terminates early when one hypothesis is significantly more
likely than the other, or after --games if neither bound is reached.

Time control matches the gauntlet baseline (10+0.1) so the resulting
Elo estimate is directly comparable to existing measurements.

Exit codes:
  0 = H1 accepted — NNUE is significantly stronger than PeSTO
  1 = H0 accepted — no significant improvement, OR cutechess error
  2 = Inconclusive — verdict line not detected; manual review needed
      (game cap reached without SPRT convergence, OR verdict phrasing
      differs from what this script expects — check the last-20-lines
      dump and validate_nnue_games.pgn)

Usage:
  cd backend && source venv/Scripts/activate
  python -m scripts.validate_nnue_rust
  python -m scripts.validate_nnue_rust --games 2000
"""

import argparse
import io
import subprocess
import sys
from collections import deque
from pathlib import Path

# Force UTF-8 output — Windows consoles default to cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Paths ──────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent

ENGINE_PATH    = _ROOT / "engine" / "target" / "release" / "pyro.exe"
NNUE_PATH      = _ROOT / "engine" / "pyro.nnue"
CUTECHESS_PATH = Path(r"C:\tools\cutechess\cutechess-1.3.1-win64\cutechess-cli.exe")
PGN_OUT        = _HERE / "validate_nnue_games.pgn"

# Expected size for (768→256)×2→1 architecture (Phase D1).
# Phase D2 will use (768×8kb→512)×2→1 — file size will change.
# Update this constant when transitioning to D2 weights or the
# preflight will fail on the new file. The failure message is
# clear, but it's better to update proactively.
EXPECTED_NNUE_SIZE = 394_762

# ── SPRT parameters ────────────────────────────────────────────────────

ELO0  = 0     # H0: no improvement
ELO1  = 10    # H1: +10 Elo
ALPHA = 0.05  # max Type I error  (false positive — wrongly accept H1)
BETA  = 0.05  # max Type II error (false negative — wrongly accept H0)

# Hard game cap — SPRT usually terminates well before this.
MAX_GAMES = 1000

# Time control — matches gauntlet baseline for comparable Elo estimates.
TC = "10+0.1"


# ── Pre-flight ─────────────────────────────────────────────────────────

def preflight_checks() -> None:
    """Refuse to run if anything obvious is broken."""
    if not ENGINE_PATH.exists():
        sys.exit(f"FATAL: pyro.exe not found at {ENGINE_PATH}")

    if not CUTECHESS_PATH.exists():
        sys.exit(f"FATAL: cutechess-cli not found at {CUTECHESS_PATH}")

    if not NNUE_PATH.exists():
        sys.exit(f"FATAL: pyro.nnue not found at {NNUE_PATH}")

    actual_size = NNUE_PATH.stat().st_size
    if actual_size != EXPECTED_NNUE_SIZE:
        sys.exit(
            f"FATAL: pyro.nnue size mismatch — without a valid weight file,\n"
            f"  pyro.exe silently falls back to PeSTO and the test is meaningless.\n"
            f"  Expected : {EXPECTED_NNUE_SIZE:,} bytes\n"
            f"  Actual   : {actual_size:,} bytes\n"
            f"  If you changed the NNUE architecture, update EXPECTED_NNUE_SIZE."
        )

    print(f"[preflight] pyro.exe    : {ENGINE_PATH}")
    print(f"[preflight] pyro.nnue   : {actual_size:,} bytes ✓")
    print(f"[preflight] cutechess   : {CUTECHESS_PATH}")
    print(f"[preflight] SPRT        : elo0={ELO0}, elo1={ELO1}, α={ALPHA}, β={BETA}")
    print(f"[preflight] TC          : {TC}")
    print()


# ── SPRT match ─────────────────────────────────────────────────────────

def run_sprt(games_cap: int = MAX_GAMES) -> bool | None:
    """Run SPRT via cutechess-cli, streaming output to stdout.

    Returns:
      True   → H1 accepted (NNUE significantly better than PeSTO)
      False  → H0 accepted (no significant improvement)
      None   → inconclusive or verdict line not recognized

    Note on cutechess exit codes: cutechess-cli returns 0 for all normal
    completions regardless of SPRT verdict, so we parse stdout for
    "H1 was accepted" / "H0 was accepted" and set our own exit code.
    If cutechess returns non-zero, that indicates a real error (crash,
    bad arguments) and we sys.exit(1) directly.
    """
    rounds = games_cap // 2  # -rounds N -games 2 → N*2 total games

    cmd = [
        str(CUTECHESS_PATH),
        # NNUE side — loads pyro.nnue automatically at startup.
        "-engine", f"name=Pyro-NNUE", f"cmd={ENGINE_PATH}",
        # PeSTO baseline — same binary, NNUE disabled via --no-nnue.
        "-engine", f"name=Pyro-PeSTO", f"cmd={ENGINE_PATH}", "arg=--no-nnue",
        # Common engine settings.
        "-each", "proto=uci", f"tc={TC}",
        # Match structure: color swap every game, -repeat pairs colors per opening.
        "-rounds", str(rounds),
        "-games", "2",
        "-repeat",
        "-recover",       # restart crashed engines instead of aborting
        "-concurrency", "1",
        # Adjudication — skips drawn/won positions without affecting result quality.
        "-draw", "movenumber=40", "movecount=10", "score=10",
        "-resign", "movecount=5", "score=1000",
        # Real SPRT termination criterion.
        "-sprt",
        f"elo0={ELO0}", f"elo1={ELO1}",
        f"alpha={ALPHA}", f"beta={BETA}",
        # Save PGN for post-hoc analysis.
        "-pgnout", str(PGN_OUT),
    ]

    print("[run_sprt] Command:")
    print("  " + " ".join(str(c) for c in cmd))
    print()

    h1_accepted = False
    h0_accepted = False
    tail: deque[str] = deque(maxlen=20)  # ring buffer for last-N-lines dump

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr so all output is visible
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in proc.stdout:
            line_stripped = line.rstrip()
            print(line_stripped, flush=True)
            tail.append(line_stripped)

            if "H1 was accepted" in line_stripped:
                h1_accepted = True
            elif "H0 was accepted" in line_stripped:
                h0_accepted = True

        proc.wait()

    except FileNotFoundError:
        sys.exit(f"FATAL: could not launch cutechess-cli at {CUTECHESS_PATH}")
    except KeyboardInterrupt:
        proc.terminate()
        sys.exit("\nAborted by user.")

    # Non-zero exit from cutechess = real error (crash, bad arguments, etc.)
    if proc.returncode != 0:
        print(f"\n[error] cutechess-cli exited with code {proc.returncode}.")
        sys.exit(1)

    if h1_accepted:
        return True
    if h0_accepted:
        return False

    # Clean exit but no verdict detected — inconclusive or phrasing mismatch.
    print()
    print("=== SPRT INCONCLUSIVE — verdict line not recognized ===")
    print("cutechess exited cleanly but we could not detect H0/H1 acceptance.")
    print("This usually means cutechess hit the game cap without convergence,")
    print("OR the verdict phrasing differs from what this script expects.")
    print("\nLast 20 lines of cutechess output:")
    for saved_line in tail:
        print(f"  {saved_line}")
    print("\nManual review required. Check validate_nnue_games.pgn for results.")

    return None


# ── Entry point ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NNUE vs PeSTO SPRT validation via cutechess-cli"
    )
    parser.add_argument(
        "--games", type=int, default=MAX_GAMES,
        help=f"Hard game cap; SPRT terminates early if conclusive (default: {MAX_GAMES})",
    )
    args = parser.parse_args()

    preflight_checks()
    verdict = run_sprt(args.games)

    print()
    if verdict is True:
        print("=== SPRT PASS — H1 accepted: NNUE is significantly stronger than PeSTO ===")
        sys.exit(0)
    elif verdict is False:
        print("=== SPRT did not pass — H0 accepted: no significant improvement over PeSTO ===")
        sys.exit(1)
    else:
        # Inconclusive message already printed by run_sprt.
        sys.exit(2)


if __name__ == "__main__":
    main()
