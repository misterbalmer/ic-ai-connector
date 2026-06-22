#!/usr/bin/env python3
"""Close SANDUSDT position via IC AI Connector."""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE = f"http://{os.getenv('CONNECTOR_HOST', '127.0.0.1')}:{os.getenv('CONNECTOR_PORT', '8080')}"
TOKEN = os.getenv("CONNECTOR_TOKEN", "")


def main() -> int:
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    symbol = "SANDUSDT"

    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{BASE}/positions", headers=headers, json={})
        if r.status_code != 200:
            print("positions error:", r.text)
            return 1
        positions = r.json().get("active_positions", [])
        sand = [p for p in positions if "SAND" in str(p.get("symbol", "")).upper()]
        print("SAND positions:", sand if sand else "none")
        if not sand:
            print("No open SAND position.")
            return 0

        payload = {"symbol": symbol, "percentage": 100.0}
        r = client.post(f"{BASE}/partial_close", headers=headers, json=payload)
        print("propose:", r.status_code, r.text[:500])
        if r.status_code != 200:
            return 1
        body = r.json()
        if body.get("mode") == "auto":
            print("Closed.")
            return 0
        pid = body.get("proposal", {}).get("proposal_id")
        if not pid:
            return 1
        cr = client.post(f"{BASE}/trade/confirm", headers=headers, json={"proposal_id": pid})
        print("confirm:", cr.status_code, cr.text[:600])
        return 0 if cr.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
