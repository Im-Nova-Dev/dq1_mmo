#!/usr/bin/env bash
# Launch multiplayer bot simulator against local server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/server"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Ensure server is up
if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "Starting server in background..."
  python main.py >/tmp/dq1_mmo_server.log 2>&1 &
  SERVER_PID=$!
  echo "$SERVER_PID" > /tmp/dq1_mmo_server.pid
  for _ in $(seq 1 40); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "Server failed to start — see /tmp/dq1_mmo_server.log"
    exit 1
  fi
  echo "Server PID $SERVER_PID"
  STARTED_SERVER=1
else
  STARTED_SERVER=0
  echo "Using existing server on :8000"
fi

cleanup() {
  if [[ "${STARTED_SERVER:-0}" == "1" && -f /tmp/dq1_mmo_server.pid ]]; then
    kill "$(cat /tmp/dq1_mmo_server.pid)" 2>/dev/null || true
    rm -f /tmp/dq1_mmo_server.pid
  fi
}
trap cleanup EXIT

python "$ROOT/tools/mp_sim.py" "$@"
