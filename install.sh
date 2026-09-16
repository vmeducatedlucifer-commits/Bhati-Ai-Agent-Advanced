#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

command -v python3 >/dev/null || { echo "Python 3.11+ is required." >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip >/dev/null
backend/.venv/bin/pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
npm --prefix frontend install --no-audit --no-fund

if [[ ! -f backend/.env ]]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env — add DEFAULT_LLM_API_KEY before starting."
fi

if command -v docker >/dev/null && [[ "${BHATI_SKIP_DOCKER:-0}" != "1" ]]; then
  echo "Dependencies installed. Start with: docker compose up --build"
else
  echo "Dependencies installed. Start with: make dev"
fi

echo "Web UI: http://localhost:5173 | API docs: http://localhost:8000/api/docs"
