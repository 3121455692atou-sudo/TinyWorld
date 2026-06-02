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
export BACKEND_PORT FRONTEND_PORT
mkdir -p "$ROOT_DIR/logs"

"$ROOT_DIR/scripts/stop.sh" >/dev/null 2>&1 || true

start_background() {
  local name="$1"
  local script="$2"
  (
    cd "$ROOT_DIR"
    nohup "$script" > "$ROOT_DIR/logs/${name}.log" 2>&1 &
    echo $! > "$ROOT_DIR/logs/${name}.pid"
  )
}

open_browser() {
  local url="$1"
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin)
      open "$url" >/dev/null 2>&1 || true
      ;;
    Linux)
      if command -v termux-open >/dev/null 2>&1; then
        termux-open "$url" >/dev/null 2>&1 || true
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 || true
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*)
      cmd.exe /c start "" "$url" >/dev/null 2>&1 || true
      ;;
  esac
}

notify_started() {
  local url="$1"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "TinyWorld" "Started: ${url}" >/dev/null 2>&1 || true
  elif command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"Started: ${url}\" with title \"TinyWorld\"" >/dev/null 2>&1 || true
  fi
}

start_background backend "$ROOT_DIR/scripts/backend.sh"
start_background frontend "$ROOT_DIR/scripts/frontend.sh"

for ((attempt = 0; attempt < 40; attempt += 1)); do
  if curl --noproxy '*' -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}/"
open_browser "$FRONTEND_URL"
notify_started "$FRONTEND_URL"
