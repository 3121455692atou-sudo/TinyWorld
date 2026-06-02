#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
mkdir -p "$ROOT_DIR/logs"

"$ROOT_DIR/scripts/stop.sh" >/dev/null 2>&1 || true

setsid bash -c "cd '$ROOT_DIR' && exec '$ROOT_DIR/scripts/backend.sh'" > "$ROOT_DIR/logs/backend.log" 2>&1 &
echo $! > "$ROOT_DIR/logs/backend.pid"

setsid bash -c "cd '$ROOT_DIR' && exec '$ROOT_DIR/scripts/frontend.sh'" > "$ROOT_DIR/logs/frontend.log" 2>&1 &
echo $! > "$ROOT_DIR/logs/frontend.pid"

for _ in $(seq 1 40); do
  if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1 &
fi

if command -v notify-send >/dev/null 2>&1; then
  notify-send "微世界" "已启动: http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1 || true
fi
