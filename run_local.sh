#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ ! -x .venv/bin/python ]]; then
  echo "Creating Python environment..."
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env. The app will run locally now; add GCP values later to enable AI extraction."
fi
mkdir -p data/uploads data/sources
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8000}"
