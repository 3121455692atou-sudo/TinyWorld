#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-8010}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
APP_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/"

if [ ! -f config.yaml ] && [ -f config.example.yaml ]; then
  cp config.example.yaml config.yaml
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python}"
else
  echo "Python 3.11+ is required. Please install Python first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required. Please install Node.js LTS first."
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  UV_CMD=(uv)
else
  "$PYTHON_BIN" -m pip install -U uv
  UV_CMD=("$PYTHON_BIN" -m uv)
fi

echo "[TinyWorld] Installing Python dependencies..."
"${UV_CMD[@]}" sync

echo "[TinyWorld] Installing frontend dependencies..."
npm --prefix frontend install

echo "[TinyWorld] Building frontend..."
npm --prefix frontend run build

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

echo "[TinyWorld] Starting backend at ${APP_URL}"
(sleep 2; open_browser "$APP_URL") &
exec "${UV_CMD[@]}" run uvicorn app.main:app --app-dir backend --host "$BACKEND_HOST" --port "$BACKEND_PORT"
