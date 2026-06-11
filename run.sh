#!/usr/bin/env bash
# Sharp Slate — one-command launcher.
# Creates a local virtualenv, installs deps, then starts the server.
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if [ ! -d ".venv" ]; then
  echo "→ creating virtualenv (.venv)"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f ".env" ]; then
  echo "→ no .env found; copying .env.example (the app runs fine with the blanks)"
  cp .env.example .env
fi

PORT="${PORT:-8000}"
echo ""
echo "  Sharp Slate is starting on http://localhost:${PORT}"
echo "  Press Ctrl+C to stop."
echo ""

exec uvicorn backend.main:app --reload --port "${PORT}"
