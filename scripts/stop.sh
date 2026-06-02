#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

stop_pid_file() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for ((attempt = 0; attempt < 20; attempt += 1)); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pid_file"
}

stop_pid_file "$ROOT_DIR/logs/backend.pid"
stop_pid_file "$ROOT_DIR/logs/frontend.pid"

if command -v pkill >/dev/null 2>&1; then
  pkill -f "$ROOT_DIR/scripts/backend.sh" 2>/dev/null || true
  pkill -f "$ROOT_DIR/scripts/frontend.sh" 2>/dev/null || true
  pkill -f "$ROOT_DIR.*uv run uvicorn app.main:app" 2>/dev/null || true
  pkill -f "$ROOT_DIR/frontend/node_modules/.bin/vite" 2>/dev/null || true
fi
