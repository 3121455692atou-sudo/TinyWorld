#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"

stop_pid() {
  local pid="$1"
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
}

stop_pid_file() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  stop_pid "$pid"
  rm -f "$pid_file"
}

stop_port() {
  local port="$1"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser "$port"/tcp 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' || true)"
  fi

  for pid in $pids; do
    stop_pid "$pid"
  done
}

stop_pid_file "$ROOT_DIR/logs/backend.pid"
stop_pid_file "$ROOT_DIR/logs/frontend.pid"
stop_port "$BACKEND_PORT"
stop_port "$FRONTEND_PORT"

if command -v pkill >/dev/null 2>&1; then
  pkill -f "$ROOT_DIR/scripts/backend.sh" 2>/dev/null || true
  pkill -f "$ROOT_DIR/scripts/frontend.sh" 2>/dev/null || true
  pkill -f "$ROOT_DIR.*uv run uvicorn app.main:app" 2>/dev/null || true
  pkill -f "$ROOT_DIR/frontend/node_modules/.bin/vite" 2>/dev/null || true
fi
