"""UCI interface to the Rust Pyro engine.

Launches engine/target/release/pyro.exe as a subprocess and communicates
via UCI protocol over stdin/stdout.

Falls back gracefully if the binary is not found.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_PATH = os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "..", "..", "engine", "target", "release", "pyro.exe")
)

NODE_LIMIT = 100000


class RustEngine:
    """Manages a persistent UCI engine subprocess."""

    def __init__(self, path: str = _ENGINE_PATH):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Rust engine not found: {path}")

        self.proc = subprocess.Popen(
            [path, "--no-nnue"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send("isready")
        self._wait_for("readyok")
        logger.info("Rust engine loaded (nodes=%d): %s", NODE_LIMIT, os.path.abspath(path))

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

    def best_move(self, fen: str) -> tuple[str, int]:
        """Send position + go nodes, return (uci_move, eval_cp).

        eval_cp is from side-to-move perspective.
        """
        self._send(f"position fen {fen}")
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
