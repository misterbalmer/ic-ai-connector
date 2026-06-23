#!/usr/bin/env bash
# IC AI Connector — start server (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${CONNECTOR_PORT:-8080}"

if [ ! -d .venv ]; then
  echo "[..] First run — installing..."
  ./install.sh
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .env ]; then
  echo "[FAIL] Missing .env — run ./install.sh"
  exit 1
fi

pid="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$pid" ]; then
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if echo "$cmd" | grep -qE 'run\.py|ic-ai-connector'; then
    echo "Stopping existing connector on port $PORT (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 1
  else
    echo "[FAIL] Port $PORT in use by PID $pid (not IC AI Connector):"
    echo "  $cmd"
    exit 1
  fi
fi

echo "Starting IC AI Connector — dashboard at http://127.0.0.1:$PORT/"
exec python run.py