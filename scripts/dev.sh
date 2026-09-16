#!/usr/bin/env bash
# Dev helper: start/stop the backend and the mock LLM detached from this shell.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python"
PORT="${PORT:-8099}"
MOCK_PORT="${MOCK_PORT:-8123}"
RUN_DIR="/tmp/bhati-dev"
mkdir -p "$RUN_DIR"

stop_one() {
  local name="$1"
  local pidfile="$RUN_DIR/$name.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$pidfile"
}

start_backend() {
  stop_one backend
  cd "$BACKEND"
  setsid nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    > "$RUN_DIR/backend.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/backend.pid"
  echo "backend  → http://127.0.0.1:$PORT (log: $RUN_DIR/backend.log)"
}

start_mock() {
  stop_one mock
  cd "$BACKEND"
  setsid nohup "$PY" tests/mock_llm.py --port "$MOCK_PORT" \
    > "$RUN_DIR/mock.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/mock.pid"
  echo "mock LLM → http://127.0.0.1:$MOCK_PORT/v1"
}

case "${1:-start}" in
  start) start_backend; start_mock ;;
  backend) start_backend ;;
  mock) start_mock ;;
  stop) stop_one backend; stop_one mock; echo "stopped" ;;
  *) echo "usage: $0 [start|backend|mock|stop]" >&2; exit 1 ;;
esac
