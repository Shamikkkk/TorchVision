# ============================================================
# Pyro Chess Engine — Production Dockerfile
#
# Multi-stage build:
#   Stage 1: Build the Rust engine (pyro binary)
#   Stage 2: Python backend + Rust binary
# ============================================================

# --- Stage 1: Build Rust engine ---
FROM rust:1.78-slim AS rust-builder

WORKDIR /build/engine
COPY engine/Cargo.toml engine/Cargo.lock* ./
COPY engine/src/ ./src/

# Build release binary (no NNUE weights needed at build time)
RUN cargo build --release

# --- Stage 2: Python backend ---
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy Rust binary from builder stage
COPY --from=rust-builder /build/engine/target/release/pyro /app/engine/pyro
RUN chmod +x /app/engine/pyro

# Copy NNUE weights if they exist
COPY engine/pyro.nnue* /app/engine/

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend/app/ /app/app/
COPY backend/data/syzygy/ /app/data/syzygy/

# Copy opening book PGN files
COPY backend/data/*.pgn /app/data/

# Environment variables
ENV PYRO_ENGINE_PATH=/app/engine/pyro
ENV PYRO_ENGINE_ARGS="--no-nnue"
ENV LOG_LEVEL=INFO
ENV HOST=0.0.0.0
ENV PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
