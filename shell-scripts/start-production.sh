#!/usr/bin/env bash
set -e

echo "🚀 Starting LEO Activation API (PRODUCTION mode)"

# =============================
# Environment
# =============================
export APP_ENV=production
export PYTHONUNBUFFERED=1

export MAIN_APP_HOST=${MAIN_APP_HOST:-0.0.0.0}
export MAIN_APP_PORT=${MAIN_APP_PORT:-8000}

# Sensible default: (2 × CPU) + 1
# WORKERS=${WORKERS:-$(($(nproc) * 2 + 1))}
WORKERS=4

# =============================
# Run
# =============================
exec uvicorn main:app \
  --host "$MAIN_APP_HOST" \
  --port "$MAIN_APP_PORT" \
  --workers "$WORKERS" \
  --log-level info \
  --proxy-headers \
  --forwarded-allow-ips="*"
