"""Production/default and PeSTO fallback launch-policy tests."""

from __future__ import annotations

import os
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from app.engine.rust_engine import RustEngine


def fake_process() -> MagicMock:
    proc = MagicMock()
    proc.stdin = StringIO()
    proc.stdout = StringIO("uciok\nreadyok\n")
    proc.stderr = StringIO()
    proc.poll.return_value = None
    return proc


class TestRustEngineStartup(unittest.TestCase):
    @patch("app.engine.rust_engine.os.path.isfile", return_value=True)
    @patch("app.engine.rust_engine.subprocess.Popen")
    def test_nnue_is_the_production_default(self, popen: MagicMock, _isfile: MagicMock) -> None:
        popen.return_value = fake_process()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYRO_NO_NNUE", None)
            engine = RustEngine(path="pyro.exe")

        self.assertEqual(popen.call_args.args[0], ["pyro.exe"])
        self.assertFalse(engine.no_nnue)
        self.assertEqual(engine.eval_mode, "SCReLU-512 NNUE")
        self.assertIn("setoption name Threads value 4\n", engine.proc.stdin.getvalue())

    @patch("app.engine.rust_engine.os.path.isfile", return_value=True)
    @patch("app.engine.rust_engine.subprocess.Popen")
    def test_env_retains_pesto_fallback(self, popen: MagicMock, _isfile: MagicMock) -> None:
        popen.return_value = fake_process()
        with patch.dict(os.environ, {"PYRO_NO_NNUE": "1"}):
            engine = RustEngine(path="pyro.exe")

        self.assertEqual(popen.call_args.args[0], ["pyro.exe", "--no-nnue"])
        self.assertTrue(engine.no_nnue)
        self.assertEqual(engine.eval_mode, "PeSTO+Tal (--no-nnue)")
        self.assertIn("setoption name Threads value 4\n", engine.proc.stdin.getvalue())


if __name__ == "__main__":
    unittest.main()
