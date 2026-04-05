#!/usr/bin/env bash
# Run the processing pipeline standalone.
# Pass --force-proportional to skip Whisper and use proportional timestamps.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
exec .venv/bin/python3 -m app.processing.pipeline "$@"
