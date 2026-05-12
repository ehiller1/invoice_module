#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== EIME — Embark Invoice Mapping Engine ==="
echo "Setting up Python environment..."
uv venv --python 3.11 .venv 2>/dev/null || true
source .venv/bin/activate
uv pip install -e . --quiet
echo "Starting server at http://localhost:8000"
if [ "${EIME_ENV}" = "production" ]; then
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
else
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
fi
