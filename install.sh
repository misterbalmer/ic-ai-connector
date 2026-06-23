#!/usr/bin/env bash
# IC AI Connector — one-time install (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")"

find_python() {
  for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python)" || {
  echo "[FAIL] Python 3.11+ not found."
  echo "       macOS: brew install python@3.12"
  echo "       Linux: sudo apt install python3.12-venv"
  exit 1
}

VER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
MAJOR="${VER%%.*}"
MINOR="${VER#*.}"
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
  echo "[FAIL] Python 3.11+ required (found $VER)"
  exit 1
fi
echo "[OK] Python $VER ($PYTHON)"

if [ ! -d .venv ]; then
  echo "[..] Creating virtual environment..."
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
echo "[OK] Dependencies installed"

python scripts/setup_wizard.py
python scripts/doctor.py --binance