#!/usr/bin/env python3
"""SPSA tuner for Pyro chess engine.

Runs two copies of pyro.exe with perturbed parameters against each other
via cutechess-cli and uses the SPSA gradient estimator to converge on
better parameter values.

Usage (from backend/):
    python -m scripts.spsa_tune [--iterations 200] [--resume spsa_results.json]

Requires cutechess-cli at CUTECHESS path below.
"""

import argparse
import io
import json
import math
import os
import random
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output — Windows consoles default to cp1252 which can't
# encode non-ASCII characters printed by this script.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── Configuration ───────────────────────────────────────────────────

CUTECHESS = r"C:\tools\cutechess\cutechess-1.3.1-win64\cutechess-cli.exe"
PYRO_CMD  = r"C:\Users\shami\OneDrive\Documents\torch\engine\target\release\pyro.exe"
PYRO_ARGS = "--no-nnue"

TC               = "5+0.1"   # time control per game
ROUNDS_PER_ITER  = 10        # 10 rounds × 2 colors = 20 games per iteration
CONCURRENCY      = 1         # one game at a time — avoids CPU contention

# SPSA hyperparameters (Spall 1998 standard values)
A_CONST = 10       # stability constant for learning-rate decay
ALPHA   = 0.602    # learning-rate decay exponent
GAMMA   = 0.101    # perturbation-size decay exponent

# ─── Parameter definitions ───────────────────────────────────────────
# (name, default, min, max, c_step)
# c_step is the initial perturbation size for this parameter.

PARAMS = [
    ("TAL_AGGRESSION",      25,  10,  50,   3),
    ("FUTILITY_MARGIN_D1",  100, 30,  250,  15),
    ("FUTILITY_MARGIN_D2",  300, 100, 600,  30),
    ("ASPIRATION_DELTA",    50,  15,  150,  8),
    ("NMP_REDUCTION",       2,   1,   4,    1),
    ("LMR_MOVE_INDEX",      3,   1,   8,    1),
    ("SE_BETA_MARGIN",      50,  20,  100,  8),
    ("QUEEN_ATTACK_WT",     40,  15,  80,   5),
    ("CASTLING_BONUS",      80,  20,  200,  12),
    ("EARLY_QUEEN_PENALTY", 60,  15,  120,  8),
]

# ─── Helpers ─────────────────────────────────────────────────────────

def build_engine_opts(values: dict) -> list:
    """Return a list of cutechess-cli 'option.NAME=VALUE' tokens."""
    tokens = []
    for name, val in values.items():
        tokens.append(f"option.{name}={int(round(val))}")
    tokens.append("option.Threads=1")   # 1 thread each; concurrency=1
    return tokens


def run_match(opts_plus: list, opts_minus: list) -> float:
    """Run a cutechess match between Engine+ and Engine-.

    Returns the score from Engine+'s perspective as a fraction [0.0, 1.0].
    Returns 0.5 if the match output cannot be parsed.
    """
    cmd = [
        CUTECHESS,
        # Engine+ — each key=value is a separate argument
        "-engine", "name=Pyro+", f"cmd={PYRO_CMD}", f"arg={PYRO_ARGS}",
        *opts_plus,
        # Engine-
        "-engine", "name=Pyro-", f"cmd={PYRO_CMD}", f"arg={PYRO_ARGS}",
        *opts_minus,
        # Match settings
        "-each", "proto=uci", f"tc={TC}",
        "-rounds", str(ROUNDS_PER_ITER),
        "-games", "2",          # 2 games per round (color swap)
        "-repeat",              # same opening for both colors
        "-recover",             # don't abort on engine crash
        "-concurrency", str(CONCURRENCY),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print("  WARNING: cutechess-cli timed out — returning 0.5")
        return 0.5
    except FileNotFoundError:
        print(f"  ERROR: cutechess-cli not found at {CUTECHESS}")
        raise

    # Parse: "Score of Pyro+ vs Pyro-: W - L - D  [score] N"
    m = re.search(
        r"Score of Pyro\+ vs Pyro-:\s+(\d+)\s+-\s+(\d+)\s+-\s+(\d+)",
        output,
    )
    if not m:
        print(f"  WARNING: could not parse cutechess output. Tail:\n{output[-400:]}")
        return 0.5

    wins, losses, draws = int(m.group(1)), int(m.group(2)), int(m.group(3))
    total = wins + losses + draws
    if total == 0:
        return 0.5

    return (wins + draws * 0.5) / total


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ─── SPSA loop ───────────────────────────────────────────────────────

def run_spsa(iterations: int, resume_path: str = None):
    # Build lookup tables
    defaults   = {p[0]: float(p[1]) for p in PARAMS}
    param_info = {p[0]: {"min": p[2], "max": p[3], "c_step": p[4]} for p in PARAMS}

    # Initialise from defaults; overwrite if resuming
    theta    = dict(defaults)
    history  = []
    start_k  = 0

    if resume_path and os.path.exists(resume_path):
        with open(resume_path) as f:
            saved = json.load(f)
        theta    = {k: float(v) for k, v in saved["theta"].items()}
        history  = saved.get("history", [])
        start_k  = len(history)
        print(f"Resuming from iteration {start_k} (loaded {resume_path})")
    else:
        print("Starting fresh SPSA run.")

    output_path = Path(__file__).parent / "spsa_results.json"

    for k in range(start_k, iterations):
        # Decay schedules
        a_k = 1.0 / (A_CONST + k + 1) ** ALPHA   # learning rate

        # Random ±1 perturbation vector
        delta = {name: random.choice([-1, 1]) for name in theta}

        # Perturbed parameter sets
        theta_plus  = {}
        theta_minus = {}
        for name in theta:
            info = param_info[name]
            c_k  = info["c_step"] / (k + 1) ** GAMMA
            theta_plus[name]  = clamp(theta[name] + c_k * delta[name],
                                      info["min"], info["max"])
            theta_minus[name] = clamp(theta[name] - c_k * delta[name],
                                      info["min"], info["max"])

        opts_plus  = build_engine_opts(theta_plus)
        opts_minus = build_engine_opts(theta_minus)

        # ── Run match ────────────────────────────────────────────────
        print(f"\n=== SPSA iteration {k + 1}/{iterations} ===")
        print(f"  theta+  TAL={theta_plus['TAL_AGGRESSION']:.1f}  "
              f"FUT1={theta_plus['FUTILITY_MARGIN_D1']:.0f}  "
              f"ASP={theta_plus['ASPIRATION_DELTA']:.0f}")
        print(f"  theta-  TAL={theta_minus['TAL_AGGRESSION']:.1f}  "
              f"FUT1={theta_minus['FUTILITY_MARGIN_D1']:.0f}  "
              f"ASP={theta_minus['ASPIRATION_DELTA']:.0f}")

        score_plus = run_match(opts_plus, opts_minus)
        score_diff = score_plus - 0.5   # centred on 0

        print(f"  Score+: {score_plus:.3f}  (diff: {score_diff:+.3f})")

        # ── SPSA gradient update ──────────────────────────────────────
        for name in theta:
            info = param_info[name]
            c_k  = info["c_step"] / (k + 1) ** GAMMA

            # Gradient estimate for this parameter
            gradient = score_diff / (2.0 * c_k * delta[name])

            # Update theta; scale step by c_step so all params move at
            # commensurate rates regardless of their natural magnitude.
            theta[name] = clamp(
                theta[name] + a_k * info["c_step"] * gradient,
                info["min"], info["max"],
            )

        # Round pure-integer parameters (step size = 1)
        for name in theta:
            if param_info[name]["c_step"] == 1:
                theta[name] = float(round(theta[name]))

        print("  Updated theta: " + ", ".join(
            f"{n}={v:.1f}" for n, v in sorted(theta.items())
        ))

        # ── Persist progress ─────────────────────────────────────────
        history.append({
            "iteration": k + 1,
            "score_plus": round(score_plus, 4),
            "theta_plus":  {n: round(v, 2) for n, v in theta_plus.items()},
            "theta_minus": {n: round(v, 2) for n, v in theta_minus.items()},
            "theta": {n: round(v, 2) for n, v in theta.items()},
        })
        with open(output_path, "w") as f:
            json.dump({"theta": theta, "history": history}, f, indent=2)

    # ── Final summary ─────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("SPSA tuning complete.")
    print("Final parameters (vs defaults):")
    for name, val in sorted(theta.items()):
        diff = val - defaults[name]
        sign = "+" if diff >= 0 else ""
        print(f"  {name:25s} {val:7.1f}  (default {defaults[name]:.0f}, "
              f"change {sign}{diff:.1f})")
    print(f"\nResults saved to: {output_path}")


# ─── Entry point ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SPSA parameter tuner for Pyro")
    parser.add_argument("--iterations", type=int, default=200,
                        help="Number of SPSA iterations (default: 200)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Resume from a previous spsa_results.json file")
    args = parser.parse_args()

    run_spsa(args.iterations, args.resume)


if __name__ == "__main__":
    main()
