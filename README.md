# ♟ TorchVision

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)

A chess UI with a hand-built minimax engine and neural network training pipeline. Play against a classical alpha-beta engine today; swap in a trained neural network tomorrow — no code changes required.

![Screenshot](docs/screenshot.png)

---

## Features

- **Chess.com-style dark UI** — familiar board colours, smooth animations, and sound effects
- **Classical minimax engine** — depth-4 search with alpha-beta pruning, runs entirely in-process
- **Piece-square table evaluation** — hand-crafted PST tables for all six piece types
- **5-minute chess clock** — live countdown with WebSocket ticks
- **Evaluation bar** — real centipawn scores from the engine, updated after every move
- **Move list in SAN notation** — scrollable, formatted like an OTB scoresheet
- **Sound effects** — distinct sounds for moves, captures, checks, and game-end events
- **Neural network training pipeline** — label positions with the classical engine, train on Lichess data, drop in the weights file to upgrade automatically

---

## Tech Stack

| Layer      | Technology                                    |
|------------|-----------------------------------------------|
| Frontend   | React 18 · TypeScript · Vite · Tailwind CSS   |
| Board UI   | react-chessboard · chess.js                   |
| Backend    | FastAPI · Uvicorn · python-chess              |
| Engine     | Custom minimax (search.py + evaluate.py)      |
| Training   | PyTorch · ChessNet (~1.3 M params)            |
| Fallback   | Stockfish 18 (optional, last-resort only)     |

---

## Getting Started

### Prerequisites

- **Node.js 18+** — `winget install OpenJS.NodeJS.LTS`
- **Python 3.11+** — `winget install Python.Python.3.11`
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

---

## Training the Neural Network

Run these steps from `backend/` with the virtualenv active.

```bash
# 1. Download a Lichess games database (~15 GB, streams and decompresses on the fly)
python -m model_training.download --year 2024 --month 1 --out data/

# 2. Label 500k opening positions with the classical engine (depth 2, ~30 min)
python -m model_training.parse \
  --pgn data/lichess_db_standard_rated_2024-01.pgn \
  --out data/positions.csv

# 3. Train ChessNet (~1–2 hrs on CPU; saves to backend/models/torch_chess.pt)
python -m model_training.train --csv data/positions.csv

# Quick smoke test with only 1000 positions:
python -m model_training.parse --pgn data/lichess.pgn \
  --out data/positions.csv --limit 1000
```

Once `backend/models/torch_chess.pt` exists, **restarting uvicorn automatically switches to neural mode** — no code changes needed.

---

## Architecture

### Engine mode priority

`TorchEngine` in `backend/app/engine/model.py` selects mode at startup:

1. **neural** — if `backend/models/torch_chess.pt` exists
2. **classical** — minimax depth 4 with PST evaluation *(current default)*
3. **stockfish** — external binary, last resort only

### Minimax + alpha-beta pruning

```
search.best_move(fen, depth, eval_fn)
  └─ minimax(board, depth, α, β, maximising)
       └─ eval_fn(board) → centipawns
```

`eval_fn` is a first-class parameter: Phase 2 passes the hand-crafted PST evaluator; Phase 3 will pass the loaded neural network. The search code never changes between phases.

### Evaluation function (Phase 2)

```
score = Σ material_value(piece) + pst_bonus(piece, square)
```

Each piece type has a 64-entry table that rewards good squares (centre control for pawns/knights, open files for rooks, etc.) and penalises bad ones.

### WebSocket game loop

The WebSocket connection is the single source of truth for live game state — FEN, turn, clocks, game-over signals. REST is used only for stateless one-shot engine suggestions (`POST /api/suggest → {move, eval}`).

### Neural network (Phase 3)

`ChessNet` is a ~1.3 M parameter model:

```
input  : 768-dim bit-board tensor (12 piece planes × 64 squares)
stem   : Conv2d 3×3, BatchNorm, ReLU
body   : 4 × ResBlock (Conv → BN → ReLU → Conv → BN + skip)
head   : GlobalAvgPool → Linear 256 → ReLU → Linear 1
output : centipawn evaluation (scalar)
```

---

## Roadmap

- [x] Classical minimax engine (depth 4, alpha-beta, PST eval)
- [x] Chess.com-style UI (dark theme, eval bar, move list, clocks, sound)
- [ ] Neural network evaluation (ChessNet trained on Lichess data)
- [ ] Game analyzer (post-game move-by-move engine evaluation)
- [ ] Opening explorer (ECO codes, transposition detection)

---

## License

[MIT](LICENSE)
