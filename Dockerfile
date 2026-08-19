# syntax=docker/dockerfile:1.6
#
# Dess CRM — multi-stage container image for Cloud Run.
#
# Stage 1 (frontend-build): compile the React/Vite frontend. Only npm
# tools and source live here; nothing from this stage ships in the
# final image except the built `dist/` directory.
#
# Stage 2 (runtime): python slim + installed dependencies + backend
# code + the `dist/` copied from stage 1. Cloud Run expects the
# container to listen on $PORT (default 8080) and terminate gracefully
# on SIGTERM — uvicorn handles both.
#
# Startup order:
#   1. `alembic upgrade head`  (applies any pending migrations)
#   2. `uvicorn app.main:app --host 0.0.0.0 --port 8080`
#
# Migrations run IN-CONTAINER at startup so a Cloud Run deploy is a
# single rollout. Day 6 Pitfall 4 notes that any migration touching
# existing rows at scale should be reviewed before deploy; Phase 1
# migrations are all additive + fast.

# ---------- Stage 1: frontend build ----------
FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------- Stage 2: backend runtime ----------
FROM python:3.11-slim AS runtime

# Non-interactive apt; no recommended packages; quiet stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps — libpq isn't needed (psycopg[binary] ships its own),
# but ca-certificates is required for outbound HTTPS to Anthropic /
# Google, and tini handles PID-1 signal forwarding on Cloud Run.
# Phase 3 Slice 2 adds ffmpeg for server-side audio transcoding —
# browsers produce different formats (Safari M4A, Chrome WebM/Opus,
# Firefox Ogg/Opus) and Chirp 2 silently fails on M4A. ffmpeg
# normalizes everything to WAV (LINEAR16 mono 16kHz) before the
# provider call. Image size impact: ~110 MB.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tini ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Copy everything needed to install the package. pyproject.toml's
# [tool.setuptools] packages = ["app"] means pip needs to SEE app/
# at install time — so app/ comes before pip install, not after.
# Cache loss: every app-code change re-runs pip install (~30s on CI,
# faster locally). Worth it for Phase 1 simplicity; a requirements.txt
# split is an easy optimization if build speed becomes a concern.
COPY pyproject.toml README.md alembic.ini ./
COPY app/ ./app/
COPY alembic/ ./alembic/
RUN pip install --upgrade pip \
 && pip install .

# Copy the built frontend from stage 1 into the location app.main
# will mount as static (wired in Slice 4).
COPY --from=frontend-build /frontend/dist/ ./frontend-dist/

EXPOSE 8080

# tini as PID 1 so uvicorn gets SIGTERM cleanly on Cloud Run scale-in.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8080"]
