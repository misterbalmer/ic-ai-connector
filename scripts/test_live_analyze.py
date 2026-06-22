#!/usr/bin/env python3
"""One live LLM analyze cycle (small universe) — verifies Gemini + feed."""

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
        print("CONNECTOR_TOKEN missing")
        return 1

    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    snap_path = ROOT / "last-konsole-snapshot.json"
    if not snap_path.exists():
        print("last-konsole-snapshot.json missing")
        return 1

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    model = os.getenv("TEST_AI_MODEL", "gemini-2.5-flash")
    httpx.post(
        f"{BASE}/api/ui/settings",
        headers=headers,
        json={"ai_model": model},
        timeout=30.0,
    )

    payload = {
        "dry_run": False,
        "snapshot_at": snap.get("snapshot_at"),
        "scanned_coins": min(5, snap.get("scanned_coins", 5)),
        "metrics_count": 9,
        "universe": (snap.get("universe") or [])[:5],
        "grid_seq": 99999,
    }
    print(f"Using model: {model}")

    print(f"POST {BASE}/api/ui/konsole/analyze (live LLM, 5 symbols)")
    r = httpx.post(
        f"{BASE}/api/ui/konsole/analyze", headers=headers, json=payload, timeout=120.0
    )
    print("Status:", r.status_code)
    try:
        body = r.json()
        print(json.dumps(body, indent=2, default=str)[:3000])
    except Exception:
        print(r.text[:500])
        return 1

    if r.status_code != 200:
        return 1

    feed = httpx.get(f"{BASE}/api/ui/ai-feed", headers=headers, timeout=30.0).json()
    msgs = feed.get("messages") or []
    print(f"\nFeed messages: {len(msgs)}")
    if msgs:
        print("Latest brief:", msgs[-1].get("brief", "")[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())