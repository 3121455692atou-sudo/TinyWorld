#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pkill -f "$ROOT_DIR/.venv/bin/uvicorn app.main:app" 2>/dev/null || true
pkill -f "$ROOT_DIR.*uv run uvicorn app.main:app" 2>/dev/null || true
pkill -f "$ROOT_DIR/frontend/node_modules/.bin/vite" 2>/dev/null || true

