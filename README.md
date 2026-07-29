# 🔥 Pyro Chess

![Rust](https://img.shields.io/badge/Rust-1.94-000000?logo=rust&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)

A hand-built chess engine with a personality. Pyro plays aggressive,
sacrificial chess — hunting your king, not grinding endgames. Its brain is
a self-trained **SCReLU-512 NNUE** network that learned to evaluate positions
from 42.8 million Stockfish-graded games, and it got measurably stronger
*without* losing its fire: the neural net sacrifices as often as the
hand-crafted evaluation it replaced.

**Burns brightest when you're losing.**

Play it live on Lichess: [**@PyroBotTorch**](https://lichess.org/@/PyroBotTorch)
(online when the bridge is running).

---

## Features

### Engine

- **Rust alpha-beta search** — PVS, null-move pruning, quiescence search,
  aspiration windows, killer moves, countermove/history heuristics, singular
  extensions, check extensions, and light late-move reductions
- **SCReLU-512 NNUE evaluation** — a `(768→512)×2→1` neural network trained on
  a 42.8M-position self-play corpus, each position graded by Stockfish 18.
  Integer-quantized inference (QA=255 / QB=64), verified byte-exact against the
  trainer's output on 10,000 positions
- **PeSTO + Tal fallback** — the original hand-crafted tapered evaluation with
  2.5× aggression bonuses, retained and selectable via `--no-nnue` (one-flag
  revert to the classic engine)
- **Static Exchange Evaluation (SEE)** — capture ordering and losing-capture
  pruning in quiescence
- **Lazy SMP** — 4-thread parallel search with a shared, lockless
  transposition table
- **31-GM opening book** — tactical players double-weighted (Tal, Shirov,
  Morphy, Kasparov, Bronstein, …)
- **Syzygy tablebases** — perfect endgame play for ≤6 pieces
- **SPSA-tuned search parameters**

### Personality

- 🔥 **Pyro persona** — flame avatar, taunting messages, dramatic game-over
  screens
- **Mood system** — Sleeping / Playful / Awake / Hunting / Feral (scales
  thinking time from 0.1s to full clock)
- **Trash talk** — context-aware taunts after brilliant moves, blunders,
  approaching mate, and game over
- **Obsidian Ember UI** — dark theme with orange fire accents, Instrument Serif
  typography, animated flame effects
- **Dynamic effects** — board attack glow when Pyro is winning, check-square
  pulse, mate-threat screen vignette

### Lichess bot

- **PyroBotTorch** — the deployed NNUE engine bridged to Lichess via the
  official `lichess-bot` client, playing real humans and bots
- **In-game persona** — flame greetings and sign-offs in game chat
  ("The board is warm…" / "Good game. Thanks for stepping into the fire.")
- **GM book + Syzygy** live on the bot, threads and time controls configurable

### Analysis

- **Game analyzer** — Stockfish-powered post-game review with move
  classification (brilliant, best, good, book, inaccuracy, mistake, blunder)
- **Eval bar** — real-time centipawn evaluation
- **Opening detection** — names the opening as you play

---

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate    # Git Bash / macOS / Linux
pip install -r requirements.txt
uvicorn app.main:app --port 8000 --host 0.0.0.0
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173
```

### Rust Engine

```bash
cd engine
cargo build --release
# Binary auto-loaded by backend on startup (NNUE by default;
# set PYRO_NO_NNUE=1 to run the classic PeSTO+Tal evaluation)
```

### Lichess bot (optional)

```bash
# Requires a separate lichess-bot checkout and a BOT-scoped token.
cd C:\lichess-bot
venv\Scripts\python.exe lichess-bot.py --logfile pyrobot.log
# PyroBotTorch is online while this runs and the machine is awake.
```

---

## Architecture

```
Frontend (React 18 + Vite + Tailwind)
    ↕ WebSocket (live game: FEN, clocks, taunts)
    ↕ REST (engine suggestions, analysis)
Backend (FastAPI + python-chess)
    ↕ UCI subprocess
Rust Engine (Pyro — bitboards, alpha-beta, SCReLU-512 NNUE)

lichess-bot bridge ↔ Lichess Bot API  (@PyroBotTorch)
    ↕ UCI subprocess → same Rust engine
```

### Engine move priority

1. **Syzygy tablebase** — ≤6 pieces → perfect endgame
2. **Opening book** — 31 GMs, tactical double-weighted
3. **Rust engine** — PVS + NNUE eval + SEE + singular ext + SMP
4. **Python fallback** — if the Rust binary is missing

---

## Strength

The engine's playing strength is measured against Stockfish's throttled
`UCI_LimitStrength` mode (an internal, self-consistent yardstick — **not** a
public rating).

- **Classic PeSTO+Tal engine:** ~1820 (Threads=4, book + Syzygy on)
- **Deployed SCReLU-512 NNUE champion:** the neural net decisively beats the
  hand-crafted evaluation — **36–0–9 (+381 Elo)** in a direct SPRT at Threads=1,
  ~84% vs Stockfish-1700 (≈ **1988** on the ladder), and **+177 Elo (LOS 100%)**
  over PeSTO in the full production config

Crucially, the stronger brain **kept the style**: on a 101-game style gauntlet
the NNUE net held every pre-registered floor (aggression, sacrifices/game, and
king-zone sacrifice rate all within noise of the hand-crafted baseline — with
king-zone sacs *per game* slightly **higher**). A net only ships if it wins the
SPRT *and* keeps the fire.

> **The personality IS the playing style.** Pyro's edge isn't raw Elo — it's
> being the strong engine that's fun to lose to.

Pyro's true **public** rating is still converging: as PyroBotTorch plays rated
games on Lichess, that number becomes real. Early casual games have gone
undefeated against ~1100–1650 human opponents.

---

## How the NNUE brain was built

The evaluation network is the product of a multi-week training campaign:

- **Corpus:** 42.8M positions from self-play, each re-graded by Stockfish 18 at
  depth 12. (The root-cause lesson: an early corpus turned out to be ~30 games
  replayed thousands of times — *data*, not architecture, was the ceiling.)
- **Training ladder (frozen gate, matched-seed pairs):** on real data,
  move-ranking correlation with Stockfish nearly **tripled** (ρ +0.213 → +0.624);
  a 512-wide SCReLU net beat the 256-wide one (overturning an earlier
  starved-data result); WDL blending was retested on clean data and permanently
  closed.
- **Inference:** integer arithmetic verified byte-exact vs the trainer on
  10,000 positions, with a fail-closed versioned net header.
- **Validation:** pre-registered SPRT + a binding style gate, then a production
  re-test at Threads=4 with book and Syzygy, before deployment.

---

## Roadmap

- [x] Classical minimax engine (NMP, LMR, aspiration windows)
- [x] Tal-style evaluation (2.5× aggression, king attack, pawn storms)
- [x] Rust engine (bitboards, PVS, SEE, singular extensions, Lazy SMP)
- [x] GM opening book (31 grandmasters, tactical double-weighted)
- [x] Syzygy tablebases (perfect endgame, ≤6 pieces)
- [x] Game analyzer, Pyro persona, Obsidian Ember UI, SPSA tuning
- [x] **NNUE corpus + training pipeline** (42.8M positions, Bullet trainer, GPU)
- [x] **SCReLU-512 NNUE champion** — trained, validated, style-gated, **deployed**
- [x] **PyroBotTorch on Lichess** — live via the official bot bridge
- [ ] **Strength campaign** — incremental/SIMD NNUE inference, log-formula LMR,
      RFP, continuation history, SEE pruning, magic bitboards (see
      `STRENGTH_AUDIT.md`); target ~2400–2600 internal, each change SPRT- and
      style-gated
- [ ] **Larger corpus + architecture** — material/piece-count output buckets
      now; king buckets + horizontal mirroring after a much larger corpus
- [ ] **24/7 hosting** — always-on bot independent of the local machine

---

## Authorship and provenance

**Pyro Chess is an original project created and maintained by
[Shamik Basu](https://github.com/Shamikkkk).**

This repository — [Shamikkkk/TorchVision](https://github.com/Shamikkkk/TorchVision)
— is the canonical upstream source for Pyro's code and development history.
Forks and redistributions may preserve and extend that history, but they do not
transfer or replace the original authorship.

## License

Copyright © 2026 Shamik Basu.

Released under the [MIT License](https://opensource.org/license/mit). As required
by that license, copies or substantial portions of the software must retain the
applicable copyright and permission notices.
