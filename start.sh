#!/usr/bin/env bash
# Run the FastAPI server using the project's venv
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
