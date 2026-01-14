#!/usr/bin/env bash
set -e

echo "🚀 Starting LEO Activation API (DEV mode)"

# =============================
# Environment
# =============================
export APP_ENV=development
export PYTHONUNBUFFERED=1

# Optional overrides
export MAIN_APP_HOST=${MAIN_APP_HOST:-0.0.0.0}
export MAIN_APP_PORT=${MAIN_APP_PORT:-8000}

# =============================
# Run
# =============================
exec uvicorn main:app \
  --host "$MAIN_APP_HOST" \
  --port "$MAIN_APP_PORT" \
  --reload \
  --log-level debug
