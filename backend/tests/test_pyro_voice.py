"""Unit tests for the G13/G15 voice module (app/engine/pyro_voice.py).

Run from backend/:  python -m unittest discover -s tests -v

Synthetic game snippets exercise: sac detection, eval-jump blunder,
king-hunt episodes, losing slide, game end, taunt cooldown, no line
repeats, heat levels, and the R3 fail-open guarantee.
"""

import unittest

import chess

from app.engine.pyro_voice import (
    LINES,
    PyroVoice,
    game_end_fields,
    heat_level,
    see_proxy,
    voice_fields,
    zone_attacker_count,
)

START = chess.STARTING_FEN

# Bishop takes the f7 pawn, defended by the king: see_proxy = 100 - 330 = -230.
SAC_FEN = "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 0 3"
SAC_MOVE = "c4f7"

# Qh5 + Nf3; Ng5 puts two non-pawn attackers on the g8 king's 3x3 zone.
HUNT2_FEN = "6k1/5ppp/8/7Q/8/5N2/5PPP/6K1 w - - 0 30"
# Same but the f2 pawn is gone and a rook sits on f1: Ng5 vacates f3 and
# opens the f-file, giving three zone attackers (Q, N, R).
HUNT3_FEN = "6k1/5ppp/8/7Q/8/5N2/6PP/5RK1 w - - 0 30"
HUNT_MOVE = "f3g5"

QUIET_FEN = START
QUIET_MOVE = "e2e4"


def board(fen: str) -> chess.Board:
    return chess.Board(fen)


class TestSeeProxy(unittest.TestCase):
    def test_defended_pawn_capture_is_sac(self):
        b = board(SAC_FEN)
        self.assertEqual(see_proxy(b, chess.Move.from_uci(SAC_MOVE)), 100 - 330)

    def test_non_capture_is_zero(self):
        b = board(START)
        self.assertEqual(see_proxy(b, chess.Move.from_uci(QUIET_MOVE)), 0)

    def test_free_queen_capture_is_positive(self):
        b = board("3q2k1/8/8/8/8/8/8/3R2K1 w - - 0 40")
        self.assertEqual(see_proxy(b, chess.Move.from_uci("d1d8")), 900)


class TestEvents(unittest.TestCase):
    def test_sac_sequence(self):
        v = PyroVoice()
        event, line, _heat = v.observe(board(SAC_FEN), SAC_MOVE, 50, ply=5)
        self.assertEqual(event, "pyro_sac")
        self.assertIn(line, LINES["pyro_sac"])

    def test_sac_outranks_check(self):
        # Bxf7+ is both a sac and a check; priority says sac.
        v = PyroVoice()
        event, _line, _heat = v.observe(board(SAC_FEN), SAC_MOVE, 50, ply=5)
        self.assertEqual(event, "pyro_sac")

    def test_opp_blunder_on_eval_jump(self):
        v = PyroVoice()
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 20, ply=1)
        self.assertIsNone(event)
        event, line, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 250, ply=3)
        self.assertEqual(event, "opp_blunder")
        self.assertIn(line, LINES["opp_blunder"])

    def test_cooldown_honored(self):
        v = PyroVoice()
        v.observe(board(QUIET_FEN), QUIET_MOVE, 20, ply=1)
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 250, ply=3)
        self.assertEqual(event, "opp_blunder")  # speaks, last_taunt_ply=3
        # +170 jump only 2 plies later: silenced by the 4-ply cooldown.
        event, line, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 420, ply=5)
        self.assertIsNone(event)
        self.assertIsNone(line)
        # 4 plies after the last taunt: speaks again.
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 600, ply=7)
        self.assertEqual(event, "opp_blunder")

    def test_game_start_exempt_then_cooldown_applies(self):
        v = PyroVoice()
        event, line, _h = v.observe(board(START), QUIET_MOVE, 0, ply=1, game_start=True)
        self.assertEqual(event, "game_start")
        self.assertIn(line, LINES["game_start"])
        # A blunder 2 plies later is inside the cooldown window.
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 200, ply=3)
        self.assertIsNone(event)

    def test_king_hunt_buildup_and_episode(self):
        v = PyroVoice()
        event, line, heat = v.observe(board(HUNT2_FEN), HUNT_MOVE, 100, ply=5)
        self.assertEqual(event, "king_hunt")
        self.assertIn(line, LINES["king_hunt"])
        self.assertEqual(heat, 1)  # 2 attackers, eval < 150
        # Attackers still >= 2: same episode, no re-fire — but heat persists.
        event, _l, heat = v.observe(board(HUNT2_FEN), HUNT_MOVE, 100, ply=11)
        self.assertIsNone(event)
        self.assertEqual(heat, 1)
        # Attack dissolves (quiet position): episode resets.
        v.observe(board(QUIET_FEN), QUIET_MOVE, 100, ply=13)
        # Pressure returns: a new episode fires.
        event, _l, _h = v.observe(board(HUNT2_FEN), HUNT_MOVE, 100, ply=21)
        self.assertEqual(event, "king_hunt")

    def test_losing_slide_fires_once_and_is_defiant(self):
        v = PyroVoice()
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, -100, ply=1)[0])
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, -250, ply=3)[0])
        event, line, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, -350, ply=5)
        self.assertEqual(event, "pyro_losing")
        self.assertIn(line, LINES["pyro_losing"])
        # Once per game.
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, -400, ply=11)
        self.assertIsNone(event)

    def test_winning_and_crushing_once_per_game(self):
        # Eval climbs in sub-150 steps so opp_blunder never outranks.
        v = PyroVoice()
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, 100, ply=1)[0])
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, 240, ply=5)[0])
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 310, ply=9)
        self.assertEqual(event, "pyro_winning")
        # Above 300 again: no re-fire.
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 320, ply=13)
        self.assertIsNone(event)
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, 460, ply=17)[0])
        self.assertIsNone(v.observe(board(QUIET_FEN), QUIET_MOVE, 590, ply=21)[0])
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 710, ply=25)
        self.assertEqual(event, "pyro_crushing")
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 730, ply=29)
        self.assertIsNone(event)

    def test_mate_announced(self):
        v = PyroVoice()
        event, line, heat = v.observe(board(QUIET_FEN), QUIET_MOVE, 49_995, ply=9)
        self.assertEqual(event, "mate_announced")
        self.assertIn(line, LINES["mate_announced"])
        self.assertEqual(heat, 3)

    def test_queen_capture(self):
        v = PyroVoice()
        v.observe(board(QUIET_FEN), QUIET_MOVE, 140, ply=1)  # establish prev eval
        event, line, _h = v.observe(board("3q2k1/8/8/8/8/8/8/3R2K1 w - - 0 40"), "d1d8", 250, ply=9)
        self.assertEqual(event, "queen_capture")
        self.assertIn(line, LINES["queen_capture"])

    def test_promotion(self):
        v = PyroVoice()
        v.observe(board(QUIET_FEN), QUIET_MOVE, 140, ply=1)  # establish prev eval
        event, line, _h = v.observe(board("8/5P2/8/8/8/7k/8/6K1 w - - 0 50"), "f7f8q", 200, ply=9)
        self.assertEqual(event, "promotion")
        self.assertIn(line, LINES["promotion"])

    def test_syzygy_win(self):
        v = PyroVoice()
        event, line, _h = v.observe(
            board("8/8/8/8/8/7k/4Q3/6K1 w - - 0 50"), "g1f2", 0, ply=9, tb_wdl=2
        )
        self.assertEqual(event, "syzygy_win")
        self.assertIn(line, LINES["syzygy_win"])
        # Once per game.
        event, _l, _h = v.observe(
            board("8/8/8/8/8/7k/4Q3/6K1 w - - 0 50"), "g1f2", 0, ply=15, tb_wdl=2
        )
        self.assertIsNone(event)


class TestGameEnd(unittest.TestCase):
    def test_always_speaks_no_cooldown(self):
        v = PyroVoice()
        # Taunt on the immediately preceding ply...
        event, _l, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 250, ply=9)
        self.assertEqual(event, "opp_blunder")
        # ...and the game-end line still fires.
        event, line, heat = v.on_game_end("win")
        self.assertEqual(event, "game_end_win")
        self.assertIn(line, LINES["game_end_win"])
        self.assertEqual(heat, 3)

    def test_loss_and_draw(self):
        event, line, heat = PyroVoice().on_game_end("loss")
        self.assertEqual(event, "game_end_loss")
        self.assertIn(line, LINES["game_end_loss"])
        self.assertEqual(heat, 0)
        event, line, _h = PyroVoice().on_game_end("draw")
        self.assertEqual(event, "game_end_draw")
        self.assertIn(line, LINES["game_end_draw"])


class TestNoRepeats(unittest.TestCase):
    def test_lines_never_repeat_within_a_game(self):
        v = PyroVoice()
        spoken = []
        # Force opp_blunder repeatedly (+200 jumps, cooldown satisfied).
        for i, ply in enumerate(range(1, 100, 4)):
            eval_cp = 200 * (i + 1)
            if eval_cp > 40_000:
                break
            event, line, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, eval_cp, ply=ply)
            if line is not None:
                spoken.append(line)
        # Bank exhausted at some point; every spoken line unique + from banks.
        self.assertEqual(len(spoken), len(set(spoken)))
        self.assertGreaterEqual(len(spoken), len(LINES["opp_blunder"]))
        # After exhaustion, the same event stays silent.
        event, line, _h = v.observe(board(QUIET_FEN), QUIET_MOVE, 41_000, ply=99)
        # (eval jump still >= 150 → opp_blunder detected, but no line left)
        self.assertIsNone(line)


class TestHeat(unittest.TestCase):
    def test_heat_levels_from_positions(self):
        # 0: no pressure
        _e, _l, heat = PyroVoice().observe(board(QUIET_FEN), QUIET_MOVE, 0, ply=1)
        self.assertEqual(heat, 0)
        # 1: two attackers, modest eval
        _e, _l, heat = PyroVoice().observe(board(HUNT2_FEN), HUNT_MOVE, 100, ply=1)
        self.assertEqual(heat, 1)
        # 2: two attackers + eval >= 150
        _e, _l, heat = PyroVoice().observe(board(HUNT2_FEN), HUNT_MOVE, 200, ply=1)
        self.assertEqual(heat, 2)
        # 2: three attackers, modest eval
        _e, _l, heat = PyroVoice().observe(board(HUNT3_FEN), HUNT_MOVE, 100, ply=1)
        self.assertEqual(heat, 2)
        # 3: three attackers + eval >= 300
        _e, _l, heat = PyroVoice().observe(board(HUNT3_FEN), HUNT_MOVE, 400, ply=1)
        self.assertEqual(heat, 3)

    def test_zone_attacker_counts(self):
        b = board(HUNT3_FEN)
        b.push(chess.Move.from_uci(HUNT_MOVE))
        self.assertEqual(zone_attacker_count(b, chess.WHITE), 3)
        b2 = board(HUNT2_FEN)
        b2.push(chess.Move.from_uci(HUNT_MOVE))
        self.assertEqual(zone_attacker_count(b2, chess.WHITE), 2)

    def test_heat_level_table(self):
        self.assertEqual(heat_level(0, 500, False), 0)
        self.assertEqual(heat_level(2, 0, False), 1)
        self.assertEqual(heat_level(2, 150, False), 2)
        self.assertEqual(heat_level(3, 0, False), 2)
        self.assertEqual(heat_level(3, 300, False), 3)
        self.assertEqual(heat_level(0, 0, True), 3)


class TestFailOpen(unittest.TestCase):
    """R3 — a raised exception inside pyro_voice never propagates."""

    SILENT = {"pyro_says": None, "voice_event": None, "heat": 0}

    def test_invalid_move_is_swallowed(self):
        v = PyroVoice()
        out = voice_fields(v, board(START), "not_a_move", 0, ply=1)
        self.assertEqual(out, self.SILENT)

    def test_internal_exception_is_swallowed(self):
        v = PyroVoice()

        def boom(*args, **kwargs):
            raise RuntimeError("voice module crashed")

        v.observe = boom  # type: ignore[method-assign]
        out = voice_fields(v, board(START), QUIET_MOVE, 0, ply=1)
        self.assertEqual(out, self.SILENT)

        v.on_game_end = boom  # type: ignore[method-assign]
        out = game_end_fields(v, "win")
        self.assertEqual(out, self.SILENT)

    def test_disabled_is_silent_and_never_calls_voice(self):
        v = PyroVoice()

        def boom(*args, **kwargs):
            raise RuntimeError("should not be called")

        v.observe = boom  # type: ignore[method-assign]
        out = voice_fields(v, board(START), QUIET_MOVE, 0, ply=1, enabled=False)
        self.assertEqual(out, self.SILENT)


class TestVoiceSpec(unittest.TestCase):
    def test_all_lines_pg_and_short(self):
        for event, lines in LINES.items():
            self.assertGreaterEqual(len(lines), 6, f"{event} needs >= 6 lines")
            for line in lines:
                self.assertLessEqual(len(line), 80, f"line too long: {line!r}")


if __name__ == "__main__":
    unittest.main()
