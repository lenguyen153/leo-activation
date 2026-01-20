#!/usr/bin/env bash
set -e

echo "🚀 Starting LEO Activation API (DEV mode)"

# =============================
# Virtualenv
# =============================
VENV_PATH="./venv"
PYTHON="$VENV_PATH/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "❌ Virtualenv not found at $VENV_PATH"
  echo "👉 Run: python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# =============================
# Environment
# =============================
export APP_ENV=development
export PYTHONUNBUFFERED=1

# Optional overrides
export MAIN_APP_HOST=${MAIN_APP_HOST:-0.0.0.0}
export MAIN_APP_PORT=${MAIN_APP_PORT:-8000}

# =============================
# Run (explicit interpreter)
# =============================
exec "$PYTHON" -m uvicorn main:app \
  --host "$MAIN_APP_HOST" \
  --port "$MAIN_APP_PORT" \
  --reload \
  --log-level debug
