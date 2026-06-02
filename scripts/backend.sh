#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "${BACKEND_PORT:-8010}"
