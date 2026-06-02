#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
fi

uv sync
npm --prefix frontend install

cleanup() {
  if [ -n "${BACKEND_PID:-}" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [ -n "${FRONTEND_PID:-}" ]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "${BACKEND_PORT:-8010}" &
BACKEND_PID=$!

npm --prefix frontend run dev -- --port "${FRONTEND_PORT:-5174}" &
FRONTEND_PID=$!

wait
