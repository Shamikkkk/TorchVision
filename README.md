# ♟ TorchVision

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-1.70+-000000?logo=rust&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)

A chess application with a hand-built Tal-style engine, Rust NNUE training pipeline, and game analysis. Play against a classical alpha-beta engine with grandmaster opening knowledge and perfect endgame tablebases.

![Screenshot](docs/screenshot.png)

---

## Features

- **Chess.com-style dark UI** — familiar board colours, smooth animations, and sound effects
- **Classical Tal-style engine** — depth-4 search with alpha-beta, NMP, LMR, aspiration windows, killer moves, history heuristic, quiescence search
- **Tal-style evaluation** — aggression bonuses, king attack, pawn storm, rook files, bishop pair, pawn structure
- **GM opening book** — 97k grandmaster games (Tal, Kasparov, Fischer, Carlsen + 28 others)
- **Syzygy tablebases** — perfect endgame play for ≤6 pieces
- **5-minute chess clock** — live countdown with WebSocket ticks
- **Evaluation bar** — real centipawn scores from the engine, updated after every move
- **Move list in SAN notation** — scrollable, formatted like an OTB scoresheet
- **Sound effects** — distinct sounds for moves, captures, checks, and game-end events
- **Game analyzer** — post-game Stockfish analysis with move classification (brilliant, best, good, book, inaccuracy, mistake, blunder)
- **NNUE training pipeline** — Rust engine generates self-play data, Bullet trainer, 768→256→1 architecture with CReLU

---

## Tech Stack

| Layer       | Technology                                              |
|-------------|---------------------------------------------------------|
| Frontend    | React 18 · TypeScript · Vite · Tailwind CSS             |
| Board UI    | react-chessboard · chess.js                             |
| Backend     | FastAPI · Uvicorn · python-chess                        |
| Engine      | Tal-style minimax (Python) + Rust engine (Phase B)      |
| Rust Engine | Bitboards · Alpha-beta · NMP · LMR · NNUE accumulator  |
| Training    | PyTorch · Bullet (Rust) · 10M self-play positions       |
| Fallback    | Stockfish 18 (optional, last-resort only)               |

---

## Getting Started

### Prerequisites

- **Node.js 18+** — `winget install OpenJS.NodeJS.LTS`
- **Python 3.11+** — `winget install Python.Python.3.11`
- **Rust 1.70+** (optional, for NNUE) — `winget install Rustlang.Rust.MSVC`
- **Stockfish** (optional) — only used if the classical engine fails

### Backend setup

```bash
cd backend
python -m venv venv
source venv/Scripts/activate          # Git Bash on Windows
# venv\Scripts\Activate.ps1           # PowerShell

pip install -r requirements.txt
# PyTorch CPU (avoids the 2 GB CUDA download):
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Copy and edit the env file
cp .env.example .env                  # set STOCKFISH_PATH if you have it

uvicorn app.main:app --port 8000 --host 0.0.0.0
```

Backend is now running at `http://localhost:8000`. Healthcheck: `GET /healthz`.

### Frontend setup

```bash
cd frontend
npm install
cp .env.local.example .env.local      # VITE_API_URL / VITE_WS_URL
npm run dev
```

Frontend is now running at `http://localhost:5173`.

### Rust engine (optional, for NNUE)

```bash
cd engine
cargo build --release
# Binary: engine/target/release/pyro.exe
# Weights: engine/pyro.nnue (auto-loaded at startup)
```

---

## Training

### Option A — Lichess supervised (PyTorch)

Run from `backend/` with the virtualenv active.

```bash
# 1. Stream Lichess games directly to CSV (no PGN on disk)
python -m model_training.stream_parse \
  --year 2024 --month 1 \
  --out data/positions.csv \
  --limit 500000

# 2. Train ChessNet (~1–2 hrs on CPU; saves to backend/models/torch_chess.pt)
python -m model_training.train --csv data/positions.csv
```

### Option B — NNUE self-play (Rust engine)

```bash
# 1. Build the Rust engine
cd engine && cargo build --release && cd ..

# 2. Initialize NNUE weights with material knowledge
cd backend && source venv/Scripts/activate
python -m scripts.init_nnue_weights

# 3. Generate self-play data (5000 nodes/move, binary format)
python -m scripts.generate_selfplay_rust --games 100000

# 4. Train with Bullet trainer (coming soon)
```

---

## Architecture

### Python engine (current, stable)

```
Eval:   tal_style_eval (material + PST + Tal aggression bonuses)
Search: minimax depth 4 + NMP + LMR + AW + killers + history + qsearch
Book:   97k GM games (Tal, Kasparov, Fischer, Carlsen + 28 others)
Endgame: Syzygy tablebases (≤6 pieces, perfect play)
```

Estimated ELO: ~1200-1400

### Rust engine (Phase B, in development)

```
Eval:   768→256→1 NNUE · CReLU · incremental accumulator
Search: alpha-beta + NMP + LMR + PeSTO + killers + qsearch
Data:   self-play 100k games · 10M positions · binary format
Train:  Bullet trainer (Rust)
```

Target ELO: 1800+

### Engine mode priority

`PyroEngine` in `backend/app/engine/model.py` selects mode at startup:

1. **Syzygy tablebase** — ≤6 pieces, no castling rights → perfect play
2. **Opening book** — grandmaster PGN positions, first 15 moves
3. **Minimax depth 4** — alpha-beta + NMP + LMR + AW + `tal_style_eval`
4. **Stockfish** — external binary, last resort only

### WebSocket game loop

The WebSocket connection is the single source of truth for live game state — FEN, turn, clocks, game-over signals. REST is used only for stateless one-shot engine suggestions (`POST /api/suggest → {move, eval}`).

---

## Roadmap

- [x] Classical minimax engine (depth 4 + NMP + LMR + AW)
- [x] Chess.com-style UI (dark theme, eval bar, clocks, sound)
- [x] Tal-style evaluation (aggression, PST, pawn structure)
- [x] GM opening book (97k games, 31 grandmasters)
- [x] Syzygy tablebases (perfect endgame, ≤6 pieces)
- [x] Game analyzer (Stockfish analysis, move classification)
- [x] Rust engine (bitboards, legal movegen, perft verified)
- [x] NNUE accumulator (768→256→1, CReLU, incremental)
- [ ] Bullet NNUE training (self-play data generating now)
- [ ] Rust engine UCI integration with Python backend
- [ ] Tal bonuses in Rust engine
- [ ] Opening explorer (ECO codes)

---

## License

[MIT](LICENSE)
