#!/usr/bin/env sh
set -eu

HOST="${APP_HOST:-0.0.0.0}"
PORT="${CONTAINER_APP_PORT:-8000}"
TRUSTED_PROXY_IPS="${TRUSTED_PROXY_IPS:-*}"
UVICORN_RELOAD="${UVICORN_RELOAD:-false}"

case "$UVICORN_RELOAD" in
  [Tt]rue|1)
    exec env APP_HOST="$HOST" APP_PORT="$PORT" UVICORN_RELOAD="true" PROXY_HEADERS="true" FORWARDED_ALLOW_IPS="$TRUSTED_PROXY_IPS" python -m src.run_app
    ;;
  *)
    exec env APP_HOST="$HOST" APP_PORT="$PORT" UVICORN_RELOAD="false" PROXY_HEADERS="true" FORWARDED_ALLOW_IPS="$TRUSTED_PROXY_IPS" python -m src.run_app
    ;;
esac
