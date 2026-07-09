"""G13/G15 — Pyro's voice and attack heat.

Pure module: (game state, move context) in -> optional (event, line, heat) out.
No engine calls, no I/O — event detection runs entirely on positions the
backend already has plus the eval history it accumulates per game (R4).

Integration contract (R3): callers go through ``voice_fields`` /
``game_end_fields``, which catch every exception and fall back to
silent + heat 0. A crashed voice never touches the move flow.

Eval convention: centipawns from Pyro's point of view (the engine reports
side-to-move scores and is always asked on positions where Pyro is to move).
Mate scores arrive as cp ±(50000 - ply), so anything above MATE_THRESHOLD
is a forced mate for Pyro.
"""

from __future__ import annotations

import logging
import random

import chess

logger = logging.getLogger(__name__)

MATE_THRESHOLD = 49_000

# SEE-proxy constants ported from backend/scripts/aggression_rate.py.
PIECE_VAL = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20_000,
}

SAC_THRESHOLD = -150

MIN_TAUNT_GAP = 4        # plies between taunts
CHECK_TAUNT_GAP = 12     # pyro_check is heavily rate-limited


def see_proxy(board: chess.Board, move: chess.Move) -> int:
    """Naive 2-ply SEE (ported from aggression_rate.py): captured_val if
    undefended after the move; otherwise captured_val - capturer_val.
    Returns 0 for non-captures."""
    if not board.is_capture(move):
        return 0

    if board.is_en_passant(move):
        captured_val = PIECE_VAL[chess.PAWN]
    else:
        target = board.piece_at(move.to_square)
        if target is None:
            return 0
        captured_val = PIECE_VAL[target.piece_type]

    capturer = board.piece_at(move.from_square)
    if capturer is None:
        return 0
    capturer_val = PIECE_VAL[capturer.piece_type]

    board.push(move)
    defenders = board.attackers(board.turn, move.to_square)
    board.pop()

    if not defenders:
        return captured_val
    return captured_val - capturer_val


def king_zone_squares(king_sq: int) -> set:
    """3x3 zone around a king square (clamped to the board)."""
    f = chess.square_file(king_sq)
    r = chess.square_rank(king_sq)
    out = set()
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                out.add(chess.square(nf, nr))
    return out


def zone_attacker_count(board: chess.Board, color: bool) -> int:
    """Distinct non-pawn, non-king pieces of *color* attacking any square in
    the 3x3 zone around the opposing king."""
    king_sq = board.king(not color)
    if king_sq is None:
        return 0
    attackers: set[int] = set()
    for sq in king_zone_squares(king_sq):
        for a_sq in board.attackers(color, sq):
            ptype = board.piece_type_at(a_sq)
            if ptype not in (chess.PAWN, chess.KING):
                attackers.add(a_sq)
    return len(attackers)


def heat_level(attackers: int, eval_cp: int, mate_announced: bool) -> int:
    """G15 heat 0..3 from king-zone pressure and eval (Pyro POV)."""
    if mate_announced or (attackers >= 3 and eval_cp >= 300):
        return 3
    if attackers >= 3 or (attackers >= 2 and eval_cp >= 150):
        return 2
    if attackers >= 2:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Line bank — Pyro is a flame: playful-menacing, dramatic, slightly
# overconfident. Losing lines are defiant-charming, never sulky. PG, ≤80 chars.
# ---------------------------------------------------------------------------

LINES: dict[str, list[str]] = {
    "game_start": [
        "Try not to disappoint me.",
        "Strike a match. Let's begin.",
        "I've been smoldering all day. Move.",
        "Fresh board. Fresh tinder.",
        "You brought pieces. How thoughtful — fuel.",
        "Light it up.",
    ],
    "mate_announced": [
        "The fire has your address.",
        "Count with me. It won't take long.",
        "Nowhere left to run. Everything's lit.",
        "This ends warm.",
        "The exits are all on fire. My apologies.",
        "Checkmate is scheduled. Please hold.",
    ],
    "pyro_sac": [
        "Take it. I insist.",
        "A gift. Unwrap it carefully.",
        "That piece? Kindling.",
        "I didn't lose it. I invested it.",
        "Free wood. Mind the splinters.",
        "Material is temporary. Fire is forever.",
        "Go on. It's warm to the touch.",
        "I play with matches. Your move.",
    ],
    "opp_blunder": [
        "Oh, that's flammable.",
        "Did you mean to do that?",
        "I smell smoke. It's not mine.",
        "Careful — you left the stove on.",
        "A spark. All I ever need.",
        "That crackling sound? Your position.",
        "I was hoping you'd play that.",
        "Interesting. Fatally interesting.",
    ],
    "king_hunt": [
        "Your king smells of smoke.",
        "I've found the kindling.",
        "His majesty's castle is dry wood.",
        "Gathering around the throne. Bring marshmallows.",
        "The hunt is lit.",
        "Your king should start walking. Now.",
        "I see a crown. I see kindling. Same thing.",
        "Knock knock. It's the fire brigade. The other kind.",
    ],
    "pyro_crushing": [
        "This is a bonfire now.",
        "Total combustion achieved.",
        "Nothing left but embers over there.",
        "I'd resign. But please don't — I'm having fun.",
        "The board is mine. The ashes too.",
        "Inferno status: reached.",
    ],
    "pyro_winning": [
        "Getting warm in here, isn't it?",
        "The tide is molten, and it's coming in.",
        "I've got the matches and the high ground.",
        "Slowly, then all at once. That's how fires go.",
        "Your position is starting to sweat.",
        "Advantage: flame.",
    ],
    "queen_capture": [
        "The queen burns brightest of all.",
        "Her majesty, meet the furnace.",
        "Nine points of premium fuel. Delicious.",
        "The crown jewel, melted down.",
        "She fought well. She burned better.",
        "Queenless. My condolences.",
    ],
    "promotion": [
        "A pawn walked through fire. It earned this.",
        "From spark to blaze.",
        "New queen. Forged, not born.",
        "Watch the little ones. They rise.",
        "Promotion day. The forge delivers.",
        "Every ember dreams of this.",
    ],
    "pyro_check": [
        "Check. Feel the heat?",
        "Knock knock.",
        "Your king flinched.",
        "Check. Just keeping you warm.",
        "A little singe. Check.",
        "Check. The room is getting smaller.",
    ],
    "pyro_losing": [
        "You've brought water. Clever.",
        "A setback. Fires have those.",
        "Smother me if you can. I always find air.",
        "Cold in here. Good — more to burn later.",
        "You fight well. I burn better. Eventually.",
        "Down, not out. Embers remember.",
    ],
    "syzygy_win": [
        "The endgame is a closed book. I wrote it.",
        "Tablebase says: toast.",
        "This ending was decided before you moved.",
        "Perfect play from here. Mine, not yours.",
        "The math is done. It's warm math.",
        "Six pieces. Zero hope.",
    ],
    "game_end_win": [
        "Ashes. Good game.",
        "Burned bright, didn't we?",
        "The board is scorched. Shake my hand anyway.",
        "That was a lovely fire. Rematch?",
        "Nothing personal. Everything combustible.",
        "GG. Mind the embers on your way out.",
    ],
    "game_end_loss": [
        "...you earned that one.",
        "Extinguished. Rude.",
        "Well played. I'll be back — fires relight.",
        "You found the water. Respect.",
        "A rare frost. Enjoy it.",
        "I'll remember this. Fondly. And with vengeance.",
    ],
    "game_end_draw": [
        "A draw? How boring.",
        "Half a point each. Half a fire is smoke.",
        "We'll call it a controlled burn.",
        "Stalemate: the fireproof result.",
        "Neither of us burned. Disappointing for both.",
        "Even embers. Next time, inferno.",
    ],
}


class PyroVoice:
    """Per-game voice state machine. One instance per game/connection.

    ``observe`` is called once per Pyro move; ``on_game_end`` when the game
    ends (any cause). Both are pure w.r.t. the boards they receive.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.evals: list[int] = []           # Pyro-POV eval per Pyro move
        self.used_lines: set[str] = set()    # never repeat a line in a game
        self.once_fired: set[str] = set()    # once-per-game events
        self.last_taunt_ply: int | None = None
        self.hunt_active: bool = False       # current king-hunt episode

    # -- internals ---------------------------------------------------------

    def _pick(self, event: str) -> str | None:
        pool = [l for l in LINES.get(event, []) if l not in self.used_lines]
        if not pool:
            return None
        line = random.choice(pool)
        self.used_lines.add(line)
        return line

    def _detect_event(
        self,
        board_before: chess.Board,
        move: chess.Move,
        board_after: chess.Board,
        eval_cp: int,
        prev_eval: int,
        hunt_fires: bool,
        tb_wdl: int | None,
    ) -> str | None:
        """Priority order per spec — first match wins."""
        if eval_cp > MATE_THRESHOLD:
            return "mate_announced"
        if see_proxy(board_before, move) <= SAC_THRESHOLD:
            return "pyro_sac"
        if (
            abs(prev_eval) < MATE_THRESHOLD
            and abs(eval_cp) < MATE_THRESHOLD
            and eval_cp - prev_eval >= 150
        ):
            return "opp_blunder"
        if hunt_fires:
            return "king_hunt"
        if eval_cp >= 700 and abs(eval_cp) < MATE_THRESHOLD and "pyro_crushing" not in self.once_fired:
            self.once_fired.add("pyro_crushing")
            return "pyro_crushing"
        if eval_cp >= 300 and abs(eval_cp) < MATE_THRESHOLD and "pyro_winning" not in self.once_fired:
            self.once_fired.add("pyro_winning")
            return "pyro_winning"
        if (
            board_before.is_capture(move)
            and not board_before.is_en_passant(move)
            and board_before.piece_type_at(move.to_square) == chess.QUEEN
        ):
            return "queen_capture"
        if move.promotion is not None:
            return "promotion"
        if board_after.is_check():
            return "pyro_check"
        if eval_cp <= -300 and abs(eval_cp) < MATE_THRESHOLD and "pyro_losing" not in self.once_fired:
            self.once_fired.add("pyro_losing")
            return "pyro_losing"
        if tb_wdl is not None and tb_wdl > 0 and "syzygy_win" not in self.once_fired:
            self.once_fired.add("syzygy_win")
            return "syzygy_win"
        return None

    # -- public API ----------------------------------------------------------

    def observe(
        self,
        board_before: chess.Board,
        move_uci: str,
        eval_cp: int | None,
        ply: int,
        tb_wdl: int | None = None,
        game_start: bool = False,
    ) -> tuple[str | None, str | None, int]:
        """Process one Pyro move. Returns (event, line, heat).

        board_before: position with Pyro to move (NOT mutated).
        eval_cp: engine eval from Pyro's POV (None -> treated as 0).
        ply: len(move_stack) after the move — used for taunt cooldowns.
        tb_wdl: Syzygy WDL for the move if the tablebase chose it.
        """
        eval_cp = int(eval_cp) if eval_cp is not None else 0
        move = chess.Move.from_uci(move_uci)
        board_after = board_before.copy()
        board_after.push(move)
        pyro_color = board_before.turn

        prev_eval = self.evals[-1] if self.evals else 0
        self.evals.append(eval_cp)

        attackers = zone_attacker_count(board_after, pyro_color)
        mate_announced = eval_cp > MATE_THRESHOLD
        heat = heat_level(attackers, eval_cp, mate_announced)

        # King-hunt episode tracking runs every move, even when silent.
        hunt_fires = attackers >= 2 and not self.hunt_active
        self.hunt_active = attackers >= 2

        if game_start:
            event: str | None = "game_start"
        else:
            event = self._detect_event(
                board_before, move, board_after, eval_cp, prev_eval, hunt_fires, tb_wdl
            )

        if event is None:
            return None, None, heat

        # Rate limiting (game_start exempt).
        if not game_start and self.last_taunt_ply is not None:
            gap = CHECK_TAUNT_GAP if event == "pyro_check" else MIN_TAUNT_GAP
            if ply - self.last_taunt_ply < gap:
                return None, None, heat

        line = self._pick(event)
        if line is None:
            return None, None, heat

        self.last_taunt_ply = ply
        return event, line, heat

    def on_game_end(self, result: str) -> tuple[str, str, int]:
        """Game over — always speaks, no cooldown. result: 'win'|'loss'|'draw'
        (from Pyro's perspective). Returns (event, line, heat)."""
        event = f"game_end_{result}"
        line = self._pick(event) or "Good game."
        heat = 3 if result == "win" else 0
        return event, line, heat


# ---------------------------------------------------------------------------
# Fail-open wrappers (R3) — the ONLY entry points the move path should use.
# ---------------------------------------------------------------------------

_SILENT: dict = {"pyro_says": None, "voice_event": None, "heat": 0}


def voice_fields(
    voice: PyroVoice,
    board_before: chess.Board,
    move_uci: str,
    eval_cp: int | None,
    ply: int,
    *,
    enabled: bool = True,
    tb_wdl: int | None = None,
    game_start: bool = False,
) -> dict:
    """Voice + heat fields for the move message. Never raises."""
    if not enabled:
        return dict(_SILENT)
    try:
        event, line, heat = voice.observe(
            board_before, move_uci, eval_cp, ply, tb_wdl=tb_wdl, game_start=game_start
        )
        return {"pyro_says": line, "voice_event": event, "heat": heat}
    except Exception:
        logger.exception("pyro_voice failed — move continues silently (R3)")
        return dict(_SILENT)


def game_end_fields(voice: PyroVoice, result: str, *, enabled: bool = True) -> dict:
    """Game-end voice fields. Never raises."""
    if not enabled:
        return dict(_SILENT)
    try:
        event, line, heat = voice.on_game_end(result)
        return {"pyro_says": line, "voice_event": event, "heat": heat}
    except Exception:
        logger.exception("pyro_voice game-end failed — silent (R3)")
        return dict(_SILENT)
