"""
Phase B pipeline runner.

Waits for data/lichess_positions.csv to finish downloading, then:
  1. Trains NNUE on the downloaded data
  2. Runs 200-game SPRT validation

All output is mirrored to logs/phase_b_run.txt with timestamps.

Run from backend/:
    python scripts/run_phase_b.py

    # Skip the download-wait and go straight to training:
    python scripts/run_phase_b.py --skip-download
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (all relative to backend/)
# ---------------------------------------------------------------------------
_BACKEND_DIR  = Path(__file__).resolve().parent.parent
_CSV_PATH     = _BACKEND_DIR / "data" / "lichess_positions.csv"
_LOG_PATH     = _BACKEND_DIR / "logs" / "phase_b_run.txt"
_TRAIN_SCRIPT = _BACKEND_DIR / "scripts" / "train_nnue_selfplay.py"
_VAL_SCRIPT   = _BACKEND_DIR / "scripts" / "validate_nnue.py"

_POLL_INTERVAL_S = 60   # seconds between row-count checks
_STABLE_ROUNDS   = 2    # consecutive unchanged counts = download done


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Tee:
    """Write to both stdout and the log file simultaneously."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("a", encoding="utf-8", buffering=1)

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        self._fh.write(text)
        sys.stdout.flush()
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


_tee: _Tee | None = None


def log(msg: str = "") -> None:
    line = f"[{_ts()}] {msg}\n" if msg else "\n"
    if _tee:
        _tee.write(line)
    else:
        sys.stdout.write(line)


# ---------------------------------------------------------------------------
# Row counting (fast: count newlines without parsing CSV)
# ---------------------------------------------------------------------------

def _count_rows(path: Path) -> int:
    """Return data-row count (header not counted). Returns 0 if file absent."""
    if not path.exists():
        return 0
    try:
        with path.open("rb") as fh:
            return max(0, fh.read().count(b"\n") - 1)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Step 1 -- wait for download
# ---------------------------------------------------------------------------

def wait_for_download() -> int:
    """
    Block until lichess_positions.csv stops growing.

    Polls every _POLL_INTERVAL_S seconds. When the row count is unchanged
    for _STABLE_ROUNDS consecutive checks, the download is considered done.

    Returns the final row count.
    """
    log("=" * 60)
    log("STEP 1 -- Waiting for lichess_positions.csv to finish")
    log(f"  File : {_CSV_PATH}")
    log(f"  Poll : every {_POLL_INTERVAL_S}s")
    log("=" * 60)

    if not _CSV_PATH.exists():
        log(f"WARNING: {_CSV_PATH} not found -- waiting for it to appear...")

    prev_count    = -1
    stable_rounds = 0

    while True:
        count = _count_rows(_CSV_PATH)
        delta = count - prev_count if prev_count >= 0 else None

        if delta is None:
            log(f"Rows so far: {count:,}  (first check)")
        else:
            log(f"Rows so far: {count:,}  (delta {delta:+,} since last check)")

        if count == prev_count and count > 0:
            stable_rounds += 1
            log(f"  Row count unchanged ({stable_rounds}/{_STABLE_ROUNDS} stable rounds)")
            if stable_rounds >= _STABLE_ROUNDS:
                log(f"Download complete -- {count:,} positions.")
                return count
        else:
            stable_rounds = 0

        prev_count = count
        log(f"  Sleeping {_POLL_INTERVAL_S}s...")
        time.sleep(_POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------

def run_step(label: str, cmd: list[str]) -> int:
    """
    Run *cmd* as a subprocess, streaming output through _tee.

    Returns the process exit code.
    """
    log()
    log("=" * 60)
    log(label)
    log(f"  Command: {' '.join(cmd)}")
    log("=" * 60)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_BACKEND_DIR),
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        if _tee:
            _tee.write(line)
        else:
            sys.stdout.write(line)

    proc.wait()

    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    log()
    log(f"{label} -> {status}")
    return proc.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _tee

    parser = argparse.ArgumentParser(
        description="Phase B pipeline: train NNUE then validate."
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip the download-wait and go straight to training.",
    )
    args = parser.parse_args()

    _tee = _Tee(_LOG_PATH)

    log()
    log("+----------------------------------------------------------+")
    log("|         PHASE B PIPELINE -- run_phase_b.py               |")
    log("+----------------------------------------------------------+")
    log(f"Log file : {_LOG_PATH}")
    log(f"Backend  : {_BACKEND_DIR}")
    if args.skip_download:
        log("Mode     : --skip-download (starting from Step 2)")
    log()

    # ------------------------------------------------------------------
    # Step 1 -- wait for download (skippable)
    # ------------------------------------------------------------------
    if args.skip_download:
        final_rows = _count_rows(_CSV_PATH)
        log("=" * 60)
        log("STEP 1 -- SKIPPED (--skip-download)")
        log(f"  CSV rows found: {final_rows:,}")
        log("=" * 60)
        if final_rows == 0:
            log(f"ERROR: {_CSV_PATH} is empty or missing. Cannot train.")
            _tee.close()
            sys.exit(1)
    else:
        final_rows = wait_for_download()

    # ------------------------------------------------------------------
    # Step 2 -- train
    # ------------------------------------------------------------------
    train_rc = run_step(
        "STEP 2 -- Training NNUE on Lichess data",
        [
            sys.executable, str(_TRAIN_SCRIPT),
            "--csv", str(_CSV_PATH),
        ],
    )

    if train_rc != 0:
        log()
        log("ERROR: Training failed -- skipping validation.")
        _tee.close()
        sys.exit(train_rc)

    # ------------------------------------------------------------------
    # Step 3 -- validate
    # ------------------------------------------------------------------
    val_rc = run_step(
        "STEP 3 -- SPRT Validation (200 games, NNUE vs classical)",
        [
            sys.executable, str(_VAL_SCRIPT),
            "--games", "200",
        ],
    )

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    log()
    log("+----------------------------------------------------------+")
    log("|                   PHASE B COMPLETE                       |")
    log("+----------------------------------------------------------+")
    log(f"  Positions trained on : {final_rows:,}")
    log(f"  Training             : {'PASSED' if train_rc == 0 else 'FAILED'}")
    log(f"  Validation (200 g)   : {'PASSED' if val_rc == 0 else 'FAILED'}")
    log()

    if val_rc == 0:
        log("  Next step: wire nnue_selfplay.pt into model.py and run full 2000-game match.")
    else:
        log("  Next step: collect more data or adjust training, then re-run.")

    log()
    _tee.close()
    sys.exit(val_rc)


if __name__ == "__main__":
    main()
