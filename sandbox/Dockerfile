# The image each chat's sandbox container runs.
#
#   docker build -f sandbox/Dockerfile -t bhati-ai-agent-sandbox:latest sandbox
#
# Point SANDBOX_IMAGE at it (that is the default). If the image is missing, the
# backend falls back to SANDBOX_FALLBACK_IMAGE (python:3.12-slim) and installs the
# essentials on first boot, which is slower.

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/root \
    TERM=xterm-256color \
    PATH="/root/.local/bin:${PATH}"

RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git gnupg jq less \
        openssh-client procps psmisc ripgrep sqlite3 unzip vim wget xz-utils \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g pnpm@9 yarn@1 \
    && rm -rf /var/lib/apt/lists/*

# Batteries the agent reaches for on most tasks.
RUN pip install --no-cache-dir \
        requests httpx beautifulsoup4 lxml \
        pandas numpy matplotlib \
        fastapi uvicorn pytest ruff \
        playwright==1.62.0 \
    && playwright install --with-deps chromium

WORKDIR /workspace

CMD ["sleep", "infinity"]
