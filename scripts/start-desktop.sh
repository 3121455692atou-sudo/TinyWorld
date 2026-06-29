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

FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}/"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}/api/health"

shell_quote() {
  printf "%q" "$1"
}

launch_terminal() {
  local command
  command="cd $(shell_quote "$ROOT_DIR") && AIWORLD_DESKTOP_TERMINAL=1 $(shell_quote "$ROOT_DIR/scripts/start-desktop.sh")"

  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin)
      if command -v osascript >/dev/null 2>&1; then
        local escaped_command
        escaped_command="${command//\\/\\\\}"
        escaped_command="${escaped_command//\"/\\\"}"
        osascript >/dev/null <<OSA
tell application "Terminal"
  activate
  do script "$escaped_command"
end tell
OSA
        return 0
      fi
      ;;
    Linux)
      if command -v gnome-terminal >/dev/null 2>&1; then
        gnome-terminal --title="TinyWorld Runtime" -- bash -lc "$command" >/dev/null 2>&1 && return 0
      fi
      if command -v konsole >/dev/null 2>&1; then
        konsole --new-tab -p tabtitle="TinyWorld Runtime" -e bash -lc "$command" >/dev/null 2>&1 && return 0
      fi
      if command -v x-terminal-emulator >/dev/null 2>&1; then
        x-terminal-emulator -T "TinyWorld Runtime" -e bash -lc "$command" >/dev/null 2>&1 &
        return 0
      fi
      if command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --title="TinyWorld Runtime" --command "bash -lc $(shell_quote "$command")" >/dev/null 2>&1 &
        return 0
      fi
      if command -v mate-terminal >/dev/null 2>&1; then
        mate-terminal --title="TinyWorld Runtime" -- bash -lc "$command" >/dev/null 2>&1 &
        return 0
      fi
      if command -v kitty >/dev/null 2>&1; then
        kitty --title "TinyWorld Runtime" bash -lc "$command" >/dev/null 2>&1 &
        return 0
      fi
      if command -v alacritty >/dev/null 2>&1; then
        alacritty --title "TinyWorld Runtime" -e bash -lc "$command" >/dev/null 2>&1 &
        return 0
      fi
      if command -v xterm >/dev/null 2>&1; then
        xterm -T "TinyWorld Runtime" -e bash -lc "$command" >/dev/null 2>&1 &
        return 0
      fi
      ;;
  esac

  return 1
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

print_banner() {
  cat <<EOF
[TinyWorld] Running
Project:  $ROOT_DIR
Frontend: $FRONTEND_URL
Backend:  $BACKEND_URL

Close this window to stop TinyWorld.
EOF
}

open_when_ready() {
  if command -v curl >/dev/null 2>&1; then
    for ((attempt = 0; attempt < 80; attempt += 1)); do
      if curl --noproxy "*" -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
        open_browser "$FRONTEND_URL"
        notify_started "$FRONTEND_URL"
        return 0
      fi
      if [ -n "${DEV_PID:-}" ] && ! kill -0 "$DEV_PID" 2>/dev/null; then
        return 0
      fi
      sleep 0.25
    done
  else
    sleep 3
  fi

  open_browser "$FRONTEND_URL"
  notify_started "$FRONTEND_URL"
}

if [ "${AIWORLD_DESKTOP_TERMINAL:-0}" != "1" ] && [ "${AIWORLD_NO_TERMINAL_POPUP:-0}" != "1" ]; then
  if launch_terminal; then
    exit 0
  fi
fi

"$ROOT_DIR/scripts/stop.sh" >/dev/null 2>&1 || true
print_banner

"$ROOT_DIR/scripts/dev.sh" &
DEV_PID=$!
open_when_ready &
OPEN_PID=$!

cleanup() {
  trap - EXIT INT TERM HUP
  if [ -n "${OPEN_PID:-}" ]; then
    kill "$OPEN_PID" 2>/dev/null || true
  fi
  if [ -n "${DEV_PID:-}" ]; then
    kill "$DEV_PID" 2>/dev/null || true
    wait "$DEV_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM HUP
wait "$DEV_PID"
