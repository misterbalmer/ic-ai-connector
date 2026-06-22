#!/usr/bin/env python3
"""Dry-run orchestrator cycle (no LLM credits). Posts to AI Desk feed."""

from __future__ import annotations

import json
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
    if not TOKEN:
        print("CONNECTOR_TOKEN missing in .env")
        return 1

    snapshot = {
        "snapshot_at": "2026-06-20T12:00:00Z",
        "scanned_coins": 3,
        "metrics_count": 9,
        "universe": [
            {"symbol": "SANDUSDT", "bias": "long", "fairway": 1},
            {"symbol": "BTCUSDT", "bias": "neutral", "fairway": 0},
            {"symbol": "ETHUSDT", "bias": "short", "fairway": -1},
        ],
    }

    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {"dry_run": True, **snapshot}

    print(f"POST {BASE}/api/ui/konsole/analyze (dry_run=true)")
    r = httpx.post(f"{BASE}/api/ui/konsole/analyze", headers=headers, json=payload, timeout=60.0)
    print("Status:", r.status_code)
    try:
        body = r.json()
        print(json.dumps(body, indent=2, default=str))
    except Exception:
        print(r.text)
        return 1

    if r.status_code != 200:
        return 1

    feed = httpx.get(f"{BASE}/api/ui/ai-feed", headers=headers, timeout=30.0)
    messages = feed.json().get("messages") or []
    print(f"\nAI feed messages: {len(messages)}")
    if messages:
        print("Latest brief:", messages[0].get("brief"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
