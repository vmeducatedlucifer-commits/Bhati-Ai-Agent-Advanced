# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- frontend --
FROM node:22-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ----------------------------------------------------------------- backend --
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    WORKSPACE_ROOT=/data/workspaces

# git and ripgrep are what the agent reaches for most; node powers stdio MCP servers.
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep procps unzip \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
# Playwright's Python package does not include browser binaries. Install the
# pinned Chromium runtime in the image so Render and Docker deployments do not
# depend on the agent shell tool or a first-request download.
RUN playwright install --with-deps chromium

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

RUN mkdir -p /data/workspaces

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8000}/api/v1/health || exit 1

WORKDIR /app/backend
RUN chmod +x start.sh
CMD ["./start.sh"]
