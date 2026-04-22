#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip wheel
  .venv/bin/pip install --only-binary=:all: -r requirements.txt
fi

HOST="${BANK_MONITOR_HOST:-0.0.0.0}"
PORT="${BANK_MONITOR_PORT:-8765}"

exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
