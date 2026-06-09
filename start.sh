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

check_for_updates() {
  if [ "${AIWORLD_SKIP_UPDATE_CHECK:-0}" = "1" ]; then
    return 0
  fi
  if ! command -v git >/dev/null 2>&1; then
    return 0
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi
  if ! git remote get-url origin >/dev/null 2>&1; then
    return 0
  fi

  local branch
  branch="$(git branch --show-current 2>/dev/null || true)"
  if [ -z "$branch" ]; then
    return 0
  fi

  echo "[TinyWorld] Checking GitHub for updates..."
  local fetch_status=0
  if command -v timeout >/dev/null 2>&1; then
    GIT_TERMINAL_PROMPT=0 timeout "${AIWORLD_UPDATE_TIMEOUT_SECONDS:-10}" \
      git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=8 fetch --quiet origin || fetch_status=$?
  else
    GIT_TERMINAL_PROMPT=0 \
      git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=8 fetch --quiet origin || fetch_status=$?
  fi
  if [ "$fetch_status" -ne 0 ]; then
    echo "[TinyWorld] Update check failed or timed out; continuing startup."
    return 0
  fi

  local remote_ref="origin/$branch"
  if ! git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
    return 0
  fi

  local local_head remote_head merge_base
  local_head="$(git rev-parse HEAD 2>/dev/null || true)"
  remote_head="$(git rev-parse "$remote_ref" 2>/dev/null || true)"
  if [ -z "$local_head" ] || [ -z "$remote_head" ] || [ "$local_head" = "$remote_head" ]; then
    return 0
  fi

  merge_base="$(git merge-base HEAD "$remote_ref" 2>/dev/null || true)"
  if [ "$merge_base" = "$remote_head" ]; then
    return 0
  fi
  if [ "$merge_base" != "$local_head" ]; then
    echo "[TinyWorld] GitHub has changes, but local history differs; skipping automatic update."
    return 0
  fi

  if [ -t 0 ]; then
    printf "[TinyWorld] GitHub has updates. Update before startup? [y/N] "
    local answer
    read -r answer || answer=""
    case "$answer" in
      y|Y|yes|YES|Yes)
        if GIT_TERMINAL_PROMPT=0 git pull --ff-only; then
          echo "[TinyWorld] Update complete; continuing startup."
        else
          echo "[TinyWorld] Update failed; continuing startup without updating."
        fi
        ;;
      *)
        echo "[TinyWorld] Update skipped; continuing startup."
        ;;
    esac
  else
    echo "[TinyWorld] GitHub has updates, but this terminal is not interactive; continuing startup."
  fi
}

check_for_updates

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
