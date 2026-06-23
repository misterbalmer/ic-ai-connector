#!/usr/bin/env bash
# IC AI Connector — stop server (macOS / Linux)
set -euo pipefail
PORT="${CONNECTOR_PORT:-8080}"
pid="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -z "$pid" ]; then
  echo "No process listening on port $PORT."
  exit 0
fi
echo "Stopping connector PID $pid on port $PORT..."
kill "$pid" 2>/dev/null || kill -9 "$pid"
echo "Connector stopped."