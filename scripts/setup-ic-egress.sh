#!/usr/bin/env bash
# One-time IC Konsole -> AI Connector pairing (macOS / Linux)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env"
HOSTS_ENTRY="127.0.0.1 ic.snapshot"

if [ "$(uname -s)" = "Darwin" ]; then
  IC_DIR="$HOME/Library/Application Support/InstitutionalCharts"
else
  IC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/InstitutionalCharts"
fi
CONNECTOR_ENV="$IC_DIR/connector.env"

echo "IC Konsole egress setup"
echo ""

if [ ! -f "$ENV_FILE" ]; then
  echo "[FAIL] $ENV_FILE not found — run ./install.sh first"
  exit 1
fi

TOKEN_LINE="$(grep -m1 '^CONNECTOR_TOKEN=' "$ENV_FILE" || true)"
if [ -z "$TOKEN_LINE" ]; then
  echo "[FAIL] CONNECTOR_TOKEN not found in $ENV_FILE"
  exit 1
fi

mkdir -p "$IC_DIR"
printf '%s\n' "$TOKEN_LINE" >"$CONNECTOR_ENV"
echo "[OK] Wrote $CONNECTOR_ENV"

HOSTS_FILE="/etc/hosts"
if grep -qE '^[[:space:]]*127\.0\.0\.1[[:space:]]+ic\.snapshot[[:space:]]*$' "$HOSTS_FILE" 2>/dev/null; then
  echo "[OK] hosts already contains: $HOSTS_ENTRY"
else
  echo "[..] Adding hosts entry (sudo required): $HOSTS_ENTRY"
  if ! echo "$HOSTS_ENTRY" | sudo tee -a "$HOSTS_FILE" >/dev/null; then
    echo "[FAIL] Could not update $HOSTS_FILE"
    echo "       Run manually: sudo sh -c 'echo $HOSTS_ENTRY >> /etc/hosts'"
    exit 1
  fi
  echo "[OK] Added to hosts"
fi

if curl -sf --max-time 5 "http://ic.snapshot:8080/api/ui/meta" >/dev/null; then
  echo "[OK] Meta probe: http://ic.snapshot:8080/api/ui/meta"
else
  echo "[WARN] ic.snapshot:8080 not reachable — start ./start.sh first, then restart IC Konsole"
fi

echo ""
echo "Next: restart IC Konsole so the startup meta probe runs with connector up."