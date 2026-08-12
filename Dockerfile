# DesignSync AI — single-service image.
#
# Stage 1 builds the React bundle; stage 2 runs FastAPI and serves that bundle
# from the same origin. One container, one port, one Railway service — and no
# CORS in production because the UI and API share an origin.

# ---------------------------------------------------------------------------
# Stage 1 — build the frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build

# Copy manifests first so dependency installation is cached independently of
# source changes.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# The compiled SPA. `app/main.py` mounts this only if the directory exists, so
# local development (Vite on :5173) is unaffected.
COPY --from=frontend /build/dist ./static

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# Vertex AI is the default provider. With no GOOGLE_CLOUD_PROJECT set it reports
# itself unconfigured and the app falls back to the deterministic mock, so a
# deployment with no credentials still serves a working demo.
ENV LLM_PROVIDER=vertex \
    DATABASE_URL=sqlite:////app/data/designsync.db \
    UPLOAD_DIR=/app/data/uploads \
    PORT=8000

EXPOSE 8000

# Shell form so Railway's injected $PORT expands.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
