#!/usr/bin/env bash
# Launch N Love2D client windows for manual multiplayer testing.
# Each window is a separate process — register different accounts in each.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
N="${1:-2}"

if ! command -v love >/dev/null 2>&1; then
  echo "Love2D not found. Install love, or use the bot sim instead:"
  echo "  ./tools/mp_sim.sh -n 3"
  exit 1
fi

if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "Start the server first:  cd server && ./run.sh"
  exit 1
fi

echo "Launching $N Love2D clients..."
echo "Register a *different* account in each window."
for i in $(seq 1 "$N"); do
  love "$ROOT/client" &
  sleep 0.4
done
echo "PIDs launched. Close windows when done."
wait
