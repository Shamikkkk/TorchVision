# 🔥 Pyro Chess

![Rust](https://img.shields.io/badge/Rust-1.94-000000?logo=rust&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)

A hand-built Tal-style chess engine with personality. Pyro plays 
aggressive, sacrificial chess — hunting your king, not grinding 
endgames. ~1835 Elo with PVS, SEE, singular extensions, SMP, and 
a 31-grandmaster opening book biased toward tactical players.

**Burns brightest when you're losing.**

---

## Features

### Engine
- **Rust alpha-beta search** — PVS, NMP (depth-dependent), LMR, 
  LMP, IID, aspiration windows, killer moves, countermove heuristic,
  history heuristic, quiescence search
- **Static Exchange Evaluation (SEE)** — proper capture ordering 
  and losing-capture pruning in quiescence
- **Singular extensions** — forced tactical sequences searched deeper
- **PeSTO + Tal evaluation** — tapered PST with 2.5x aggression 
  bonuses for king attacks, pawn storms, piece activity
- **Lazy SMP** — 4-thread parallel search with shared transposition table
- **31-GM opening book** — tactical players double-weighted 
  (Tal, Shirov, Morphy, Kasparov, Bronstein, etc.)
- **Syzygy tablebases** — perfect endgame play for ≤6 pieces
- **10 UCI-tunable parameters** — SPSA-optimized

### Personality
- 🔥 **Pyro persona** — flame avatar, taunting messages, dramatic 
  game-over screens
- **Mood system** — Sleeping / Playful / Awake / Hunting / Feral 
  (scales thinking time from 0.1s to full clock)
- **Trash talk** — context-aware taunts after brilliant moves,
  blunders, approaching mate, and game over
- **Obsidian Ember UI** — dark theme with orange fire accents, 
  Instrument Serif typography, animated flame effects
- **Dynamic effects** — board attack glow when Pyro is winning,
  check-square pulse, mate-threat screen vignette

### Analysis
- **Game analyzer** — Stockfish-powered post-game review with move 
  classification (brilliant, best, good, book, inaccuracy, mistake, 
  blunder)
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
# Binary auto-loaded by backend on startup
```

---

## Architecture

```
Frontend (React 18 + Vite + Tailwind)
    ↕ WebSocket (live game: FEN, clocks, taunts)
    ↕ REST (engine suggestions, analysis)
Backend (FastAPI + python-chess)
    ↕ UCI subprocess
Rust Engine (Pyro — bitboards, alpha-beta, PeSTO+Tal)
```

### Engine move priority
1. **Syzygy tablebase** — ≤6 pieces → perfect endgame
2. **Opening book** — 31 GMs, first 15 moves, freq ≥ 3
3. **Rust engine** — PVS + SEE + singular ext + SMP
4. **Python fallback** — if Rust binary missing
5. **Stockfish** — last resort only

---

## Strength

~1835 Elo at 10s+0.1s (measured April 2026, 200-game gauntlets 
vs Stockfish UCI_LimitStrength). 67% vs SF-1700 (LOS 100%), 
42.5% vs SF-1900. Zero disconnects across 600+ gauntlet games.

Non-linear performance curve: plays up against strong opponents,
down against weak ones — the Tal-style aggression working as 
intended. The personality IS the playing style.

**Next: NNUE integration (Phase D) targeting 3000+ Elo.**

---

## Roadmap

- [x] Classical minimax engine (depth 4 + NMP + LMR + AW)
- [x] Tal-style evaluation (2.5x aggression, king attack, pawn storms)
- [x] Rust engine (bitboards, PVS, SEE, singular extensions, SMP)
- [x] GM opening book (31 grandmasters, tactical double-weighted)
- [x] Syzygy tablebases (perfect endgame, ≤6 pieces)
- [x] Game analyzer (Stockfish analysis, move classification)
- [x] Pyro persona (taunts, mood system, cinematic game-over)
- [x] Obsidian Ember UI (design tokens, lobby, dynamic effects)
- [x] SPSA parameter optimization (10 params, 200 iterations)
- [x] Countermove heuristic, LMP, IID, depth-dependent NMP
- [ ] Deployment (Netlify + Railway, Dockerized)
- [ ] NNUE v2 (Phase D1: 100M positions, Bullet trainer)
- [ ] King buckets + scaled NNUE (Phase D2: 500M+ positions)
- [ ] 3000+ Elo (Phase D3: 1B+ positions, large network)

---

## License

[MIT](LICENSE)
