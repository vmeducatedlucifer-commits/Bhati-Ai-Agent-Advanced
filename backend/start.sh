#!/bin/sh
# Start the embedded model gateway (loopback-only, agent-only) next to the agent API.
# Render exposes exactly one public port -> the agent API below. The gateway binds
# 127.0.0.1 inside this container, so it is unreachable from the internet; the
# agent reaches it over loopback with GATEWAY_SHARED_SECRET as Bearer.
set -e

GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8081}"
APP_PORT="${PORT:-8000}"

if [ "$GATEWAY_HOST" != "127.0.0.1" ] && [ "$GATEWAY_HOST" != "localhost" ] && [ "$GATEWAY_HOST" != "::1" ]; then
  echo "REFUSING to bind the embedded gateway to non-loopback host: $GATEWAY_HOST" >&2
  exit 1
fi

# Render's `generateValue` only fills NEW services — on existing services this
# arrives empty. Generate an ephemeral 256-bit secret instead of crash-looping:
# both processes below inherit it, so agent<->gateway auth keeps working, and a
# restart simply rotates it (nothing outside this container ever knows it).
if [ -z "$GATEWAY_SHARED_SECRET" ]; then
  GATEWAY_SHARED_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  export GATEWAY_SHARED_SECRET
  echo "GATEWAY_SHARED_SECRET was empty — generated an ephemeral one for this boot." >&2
fi

python -m uvicorn app.gateway.server:app \
  --host "$GATEWAY_HOST" --port "$GATEWAY_PORT" --no-server-header &
GATEWAY_PID=$!
trap 'kill $GATEWAY_PID 2>/dev/null' TERM INT

exec python -m uvicorn app.main:app \
  --host 0.0.0.0 --port "$APP_PORT" --proxy-headers --no-server-header
