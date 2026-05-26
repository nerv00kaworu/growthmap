#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/nerv0/.openclaw/workspace/growthmap"
BACKEND="$ROOT/src/backend"
FRONTEND="$ROOT/src/frontend"
LOG_DIR="${GROWTHMAP_LOG_DIR:-/tmp}"
BACK_LOG="$LOG_DIR/growthmap_8100_public.log"
FRONT_LOG="$LOG_DIR/growthmap_3100_public.log"
BACK_PORT="${GROWTHMAP_BACK_PORT:-8100}"
FRONT_PORT="${GROWTHMAP_FRONT_PORT:-3100}"
HOST="0.0.0.0"

echo "== GrowthMap start =="
echo "root: $ROOT"

kill_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  else
    local pids
    pids=$(ss -ltnp "( sport = :$port )" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u || true)
    if [[ -n "${pids:-}" ]]; then
      kill $pids >/dev/null 2>&1 || true
    fi
  fi
}

wait_http() {
  local name="$1"
  local url="$2"
  local tries="${3:-30}"
  for i in $(seq 1 "$tries"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)
    if [[ "$code" == "200" ]]; then
      echo "ok: $name -> $code"
      return 0
    fi
    sleep 1
  done
  echo "FAIL: $name did not become healthy: $url" >&2
  return 1
}

# Build frontend only if requested or .next missing.
if [[ "${GROWTHMAP_BUILD:-auto}" == "1" || ! -d "$FRONTEND/.next" ]]; then
  echo "building frontend..."
  (cd "$FRONTEND" && npm run build)
fi

echo "stopping old listeners..."
kill_port "$FRONT_PORT"
kill_port "$BACK_PORT"

# Backend venv bootstrap if missing.
if [[ ! -d "$BACKEND/venv" ]]; then
  echo "creating backend venv..."
  python3 -m venv "$BACKEND/venv"
fi

echo "starting backend :$BACK_PORT..."
(
  cd "$BACKEND"
  . venv/bin/activate
  nohup uvicorn main:app --host "$HOST" --port "$BACK_PORT" > "$BACK_LOG" 2>&1 &
)

echo "starting frontend :$FRONT_PORT..."
(
  cd "$FRONTEND"
  nohup npx next start -H "$HOST" -p "$FRONT_PORT" > "$FRONT_LOG" 2>&1 &
)

sleep 2
wait_http "backend local" "http://127.0.0.1:${BACK_PORT}/api/projects"
wait_http "frontend local" "http://127.0.0.1:${FRONT_PORT}/"
wait_http "frontend api proxy" "http://127.0.0.1:${FRONT_PORT}/api/projects"

WSL_IP=$(hostname -I | awk '{print $1}')
TS_IP=""
if command -v tailscale >/dev/null 2>&1; then
  TS_IP=$(tailscale ip -4 2>/dev/null | head -n1 || true)
fi

cat <<EOF

== GrowthMap ready ==
Local:      http://127.0.0.1:${FRONT_PORT}/
WSL/LAN:    http://${WSL_IP}:${FRONT_PORT}/
Backend:    http://127.0.0.1:${BACK_PORT}/api/projects
Logs:
  backend:  $BACK_LOG
  frontend: $FRONT_LOG
EOF

if [[ -n "$TS_IP" ]]; then
  echo "Tailscale:  http://${TS_IP}:${FRONT_PORT}/"
else
  echo "Tailscale:  unavailable from WSL; use Windows host Tailscale IP with portproxy if configured."
fi

echo
ss -ltnp "( sport = :$FRONT_PORT or sport = :$BACK_PORT )" || true
