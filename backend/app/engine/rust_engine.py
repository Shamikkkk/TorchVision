"""UCI interface to the Rust Pyro engine.

Launches engine/target/release/pyro.exe as a subprocess and communicates
via UCI protocol over stdin/stdout.

SCReLU-512 NNUE is the production default. Set PYRO_NO_NNUE=1 to retain the
PeSTO+Tal comparison/fallback path.

Falls back gracefully if the binary is not found.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_PATH = os.environ.get(
    "PYRO_ENGINE_PATH",
    os.path.normpath(
        os.path.join(_SCRIPT_DIR, "..", "..", "..", "engine", "target", "release", "pyro.exe")
    ),
)

NODE_LIMIT = 100000
THREADS = 4
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


class RustEngine:
    """Manages a persistent UCI engine subprocess."""

    def __init__(self, path: str = _ENGINE_PATH, no_nnue: bool | None = None):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Rust engine not found: {path}")

        if no_nnue is None:
            no_nnue = _env_flag("PYRO_NO_NNUE")
        command = [path]
        if no_nnue:
            command.append("--no-nnue")

        self.no_nnue = no_nnue
        self.eval_mode = "PeSTO+Tal (--no-nnue)" if no_nnue else "SCReLU-512 NNUE"
        self.threads = THREADS
        self.startup_command = subprocess.list2cmdline(command)
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name Threads value {self.threads}")
        self._send("isready")
        self._wait_for("readyok")
        logger.info(
            "Rust engine loaded (eval=%s, Threads=%d, nodes=%d, command=%s)",
            self.eval_mode,
            self.threads,
            NODE_LIMIT,
            self.startup_command,
        )

    def _send(self, cmd: str) -> None:
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _wait_for(self, token: str) -> list[str]:
        lines: list[str] = []
        while True:
            line = self.proc.stdout.readline().strip()
            if not line and self.proc.poll() is not None:
                raise RuntimeError("Rust engine process died")
            lines.append(line)
            if line.startswith(token):
                return lines

    def best_move(
        self,
        fen: str,
        wtime_ms: int | None = None,
        btime_ms: int | None = None,
        movetime_ms: int | None = None,
    ) -> tuple[str, int]:
        """Send position + go, return (uci_move, eval_cp).

        Priority: movetime_ms > wtime_ms/btime_ms > node limit.

        eval_cp is from side-to-move perspective.
        """
        self._send(f"position fen {fen}")
        if movetime_ms is not None:
            self._send(f"go movetime {movetime_ms}")
        elif wtime_ms is not None and btime_ms is not None:
            self._send(f"go wtime {wtime_ms} btime {btime_ms}")
        else:
            self._send(f"go nodes {NODE_LIMIT}")
        lines = self._wait_for("bestmove")

        # Parse eval from info lines
        eval_cp = 0
        for line in lines:
            if "score cp" in line:
                parts = line.split()
                for i, tok in enumerate(parts):
                    if tok == "cp" and i + 1 < len(parts):
                        try:
                            eval_cp = int(parts[i + 1])
                        except ValueError:
                            pass

        # Parse bestmove
        bestmove = ""
        for line in lines:
            if line.startswith("bestmove"):
                tok = line.split()[1]
                if tok != "(none)":
                    bestmove = tok
                break

        return bestmove, eval_cp

    def quit(self) -> None:
        try:
            self._send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def try_load_rust_engine() -> RustEngine | None:
    """Try to load the Rust engine. Returns None if not available."""
    try:
        return RustEngine()
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        logger.info("Rust engine not available: %s", exc)
        return None
