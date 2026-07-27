#!/usr/bin/env bash
# Start the GrowthMap authoring editor from already-installed, already-built artifacts.
# This launcher deliberately does not install dependencies, kill processes, or run a content import command.
# Backend startup may apply its documented lightweight schema compatibility steps to DATABASE_URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/src/backend"
FRONTEND="$ROOT/src/frontend"
PYTHON_BIN="${GROWTHMAP_PYTHON:-$BACKEND/venv/bin/python}"
BACK_HOST="${GROWTHMAP_BACK_HOST:-127.0.0.1}"
BACK_PORT="${GROWTHMAP_BACK_PORT:-8100}"
FRONT_HOST="${GROWTHMAP_FRONT_HOST:-127.0.0.1}"
FRONT_PORT="${GROWTHMAP_FRONT_PORT:-3100}"
LOG_DIR="${GROWTHMAP_LOG_DIR:-$ROOT/.runtime-logs}"
DATABASE_URL_VALUE="${DATABASE_URL:-}"

usage() {
  cat <<'EOF'
Usage: ./scripts/start_growthmap.sh [--foreground]

Prerequisites (performed separately):
  cd src/backend && python3 -m venv venv && venv/bin/pip install -r requirements.lock
  cd src/frontend && npm ci && npm run build

Environment:
  GROWTHMAP_PYTHON       Python interpreter (default: src/backend/venv/bin/python)
  GROWTHMAP_BACK_HOST    Backend bind host (default: 127.0.0.1)
  GROWTHMAP_BACK_PORT    Backend port (default: 8100)
  GROWTHMAP_FRONT_HOST   Frontend bind host (default: 127.0.0.1)
  GROWTHMAP_FRONT_PORT   Frontend port (default: 3100)
  GROWTHMAP_LOG_DIR      Log directory (default: .runtime-logs)
  DATABASE_URL           Required explicit SQLite/DB URL. The launcher never chooses a data file.
EOF
}

is_loopback_host() {
  case "$1" in
    localhost|127.0.0.1) return 0 ;;
    *) return 1 ;;
  esac
}

if ! is_loopback_host "$BACK_HOST" || ! is_loopback_host "$FRONT_HOST"; then
  echo "refusing to start: public/non-loopback binds are unsupported before authenticated desktop packaging" >&2
  exit 1
fi

FOREGROUND=false
case "${1:-}" in
  "") ;;
  --foreground) FOREGROUND=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

require_file() {
  [[ -e "$1" ]] || { echo "missing required file: $1" >&2; exit 1; }
}
require_executable() {
  [[ -x "$1" ]] || { echo "missing executable: $1" >&2; exit 1; }
}
port_free() {
  local host="$1" port="$2"
  if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :$port" | grep -q LISTEN; then
    echo "refusing to start: port $port is already in use" >&2
    exit 1
  fi
}

require_executable "$PYTHON_BIN"
require_file "$FRONTEND/.next/BUILD_ID"
require_file "$FRONTEND/package.json"
require_executable "$FRONTEND/node_modules/.bin/next"
command -v npx >/dev/null 2>&1 || { echo "npx is required" >&2; exit 1; }
port_free "$BACK_HOST" "$BACK_PORT"
port_free "$FRONT_HOST" "$FRONT_PORT"
mkdir -p "$LOG_DIR"

if [[ -z "$DATABASE_URL_VALUE" ]]; then
  echo "DATABASE_URL is required; refusing to choose or create a default data file." >&2
  exit 1
fi

echo "Starting GrowthMap authoring editor"
echo "  frontend: http://${FRONT_HOST}:${FRONT_PORT}"
echo "  backend:  http://${BACK_HOST}:${BACK_PORT}/api"
echo "  logs:     $LOG_DIR"

start_backend() {
  cd "$BACKEND"
  if [[ -n "$DATABASE_URL_VALUE" ]]; then
    exec env DATABASE_URL="$DATABASE_URL_VALUE" "$PYTHON_BIN" -m uvicorn main:app --host "$BACK_HOST" --port "$BACK_PORT"
  fi
  exec "$PYTHON_BIN" -m uvicorn main:app --host "$BACK_HOST" --port "$BACK_PORT"
}
start_frontend() {
  cd "$FRONTEND"
  exec npx next start -H "$FRONT_HOST" -p "$FRONT_PORT"
}

if "$FOREGROUND"; then
  start_backend >"$LOG_DIR/backend.log" 2>&1 &
  backend_pid=$!
  trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM
  start_frontend
else
  start_backend >"$LOG_DIR/backend.log" 2>&1 &
  backend_pid=$!
  start_frontend >"$LOG_DIR/frontend.log" 2>&1 &
  frontend_pid=$!
  printf '%s\n' "$backend_pid" >"$LOG_DIR/backend.pid"
  printf '%s\n' "$frontend_pid" >"$LOG_DIR/frontend.pid"
  echo "started backend pid=$backend_pid, frontend pid=$frontend_pid"
fi
