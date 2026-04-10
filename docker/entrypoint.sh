#!/usr/bin/env sh
set -eu

HOST="${APP_HOST:-0.0.0.0}"
PORT="${CONTAINER_APP_PORT:-8000}"
TRUSTED_PROXY_IPS="${TRUSTED_PROXY_IPS:-*}"
UVICORN_RELOAD="${UVICORN_RELOAD:-false}"

case "$UVICORN_RELOAD" in
  [Tt]rue|1)
    exec uvicorn src.main:app --host "$HOST" --port "$PORT" --reload --proxy-headers --forwarded-allow-ips="$TRUSTED_PROXY_IPS"
    ;;
  *)
    exec uvicorn src.main:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips="$TRUSTED_PROXY_IPS"
    ;;
esac
