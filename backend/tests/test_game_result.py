"""Result-truth tests: every terminal state message must carry the correct
status+winner, the voice must speak the matching game_end event, and finished
games must persist as valid PGN (fail-open).

Run from backend/:  python -m unittest discover -s tests -v
"""

import io
import tempfile
import unittest
from pathlib import Path

import chess
import chess.pgn

from app.chess_utils.board import result_of
from app.chess_utils.game_store import save_game
from app.engine.pyro_voice import PyroVoice, game_end_fields
from app.ws.handler import _pyro_result, _state


def board_from(*ucis: str) -> chess.Board:
    b = chess.Board()
    for u in ucis:
        b.push(chess.Move.from_uci(u))
    return b


# Black mates White (fool's mate) — Pyro mates when Pyro is black.
BLACK_MATES = ("f2f3", "e7e5", "g2g4", "d8h4")
# White mates Black (scholar's mate) — human mates when human is white.
WHITE_MATES = ("e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7")
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


class TestResultOf(unittest.TestCase):
    def test_checkmate_winner_is_the_mover(self):
        b = board_from(*BLACK_MATES)
        self.assertTrue(b.is_checkmate())
        self.assertEqual(result_of(b, "checkmate"), "b")
        b2 = board_from(*WHITE_MATES)
        self.assertTrue(b2.is_checkmate())
        self.assertEqual(result_of(b2, "checkmate"), "w")

    def test_resignation_winner_is_the_opponent(self):
        b = board_from("e2e4")
        self.assertEqual(result_of(b, "resigned", resigner="w"), "b")
        self.assertEqual(result_of(b, "resigned", resigner="b"), "w")
        self.assertIsNone(result_of(b, "resigned"))  # unknown resigner

    def test_draws_and_ongoing_have_no_winner(self):
        st = chess.Board(STALEMATE_FEN)
        self.assertTrue(st.is_stalemate())
        self.assertIsNone(result_of(st, "stalemate"))
        self.assertIsNone(result_of(chess.Board(), "ongoing"))
        self.assertIsNone(result_of(chess.Board(), "draw"))


class TestTerminalStateMessages(unittest.TestCase):
    """The five endings: state message status+winner + matching voice event."""

    def end_to_end(self, st: dict, human_color: str) -> str:
        """Return the voice event chosen for this terminal state."""
        fields = game_end_fields(PyroVoice(), _pyro_result(st.get("winner"), human_color))
        return fields["voice_event"]

    def test_pyro_mates(self):
        # Human is white; Pyro (black) delivers mate.
        b = board_from(*BLACK_MATES)
        st = _state(b, human_color="w")
        self.assertEqual(st["status"], "checkmate")
        self.assertEqual(st["winner"], "b")
        self.assertEqual(self.end_to_end(st, "w"), "game_end_win")

    def test_human_mates(self):
        # Human is white and delivers mate.
        b = board_from(*WHITE_MATES)
        st = _state(b, human_color="w")
        self.assertEqual(st["status"], "checkmate")
        self.assertEqual(st["winner"], "w")
        self.assertEqual(self.end_to_end(st, "w"), "game_end_loss")

    def test_stalemate(self):
        b = chess.Board(STALEMATE_FEN)
        st = _state(b, human_color="w")
        self.assertEqual(st["status"], "stalemate")
        self.assertNotIn("winner", st)
        self.assertEqual(self.end_to_end(st, "w"), "game_end_draw")

    def test_resignation_each_way(self):
        b = board_from("e2e4")
        # Human (white) resigns -> Pyro (black) wins.
        st = _state(b, resigned=True, human_color="w")
        self.assertEqual(st["status"], "resigned")
        self.assertEqual(st["winner"], "b")
        self.assertEqual(self.end_to_end(st, "w"), "game_end_win")
        # Human (black) resigns -> Pyro (white) wins.
        st = _state(b, resigned=True, human_color="b")
        self.assertEqual(st["status"], "resigned")
        self.assertEqual(st["winner"], "w")
        self.assertEqual(self.end_to_end(st, "b"), "game_end_win")

    def test_timeout(self):
        b = board_from("e2e4")
        # Human (white) flags -> Pyro (black) wins on time.
        st = _state(b, winner="b", human_color="w")
        self.assertEqual(st["status"], "timeout")
        self.assertEqual(st["winner"], "b")
        self.assertEqual(self.end_to_end(st, "w"), "game_end_win")
        # Pyro flags -> human wins on time.
        st = _state(b, winner="w", human_color="w")
        self.assertEqual(st["winner"], "w")
        self.assertEqual(self.end_to_end(st, "w"), "game_end_loss")

    def test_checkmate_never_looks_like_a_draw(self):
        """Regression for the ½–½ bug: every mate carries a winner."""
        for moves, expected in ((BLACK_MATES, "b"), (WHITE_MATES, "w")):
            st = _state(board_from(*moves), human_color="w")
            self.assertIn("winner", st)
            self.assertEqual(st["winner"], expected)


class TestGameStore(unittest.TestCase):
    def test_saves_parseable_pgn_with_result(self):
        b = board_from(*BLACK_MATES)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_game(b, human_color="w", status="checkmate", winner="b", directory=Path(tmp))
            self.assertIsNotNone(path)
            game = chess.pgn.read_game(io.StringIO(path.read_text(encoding="utf-8")))
            self.assertEqual(game.headers["Result"], "0-1")
            self.assertEqual(game.headers["White"], "You")
            self.assertEqual(game.headers["Black"], "Pyro")
            self.assertEqual(game.headers["Termination"], "checkmate")
            self.assertEqual(len(list(game.mainline_moves())), len(BLACK_MATES))

    def test_appends_multiple_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_game(board_from(*BLACK_MATES), human_color="w", status="checkmate", winner="b", directory=Path(tmp))
            path = save_game(board_from("e2e4"), human_color="b", status="resigned", winner="w", directory=Path(tmp))
            stream = io.StringIO(path.read_text(encoding="utf-8"))
            games = []
            while True:
                g = chess.pgn.read_game(stream)
                if g is None:
                    break
                games.append(g)
            self.assertEqual(len(games), 2)
            self.assertEqual(games[1].headers["Result"], "1-0")
            self.assertEqual(games[1].headers["White"], "Pyro")

    def test_draw_result_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_game(chess.Board(STALEMATE_FEN), human_color="w", status="stalemate", winner=None, directory=Path(tmp))
            game = chess.pgn.read_game(io.StringIO(path.read_text(encoding="utf-8")))
            self.assertEqual(game.headers["Result"], "1/2-1/2")

    def test_fail_open_on_bad_directory(self):
        # A directory path that is actually a file: mkdir/open fails -> None, no raise.
        with tempfile.NamedTemporaryFile(suffix=".notadir", delete=False) as f:
            blocker = Path(f.name)
        try:
            result = save_game(board_from("e2e4"), human_color="w", status="draw", directory=blocker)
            self.assertIsNone(result)
        finally:
            blocker.unlink()


if __name__ == "__main__":
    unittest.main()
