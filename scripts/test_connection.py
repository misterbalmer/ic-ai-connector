#!/usr/bin/env python3
"""Test IC AI Connector — read-only checks (no trades)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE = f"http://{os.getenv('CONNECTOR_HOST', '127.0.0.1')}:{os.getenv('CONNECTOR_PORT', '8080')}"
TOKEN = os.getenv("CONNECTOR_TOKEN", "")


def hdrs() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    if not TOKEN:
        print("CONNECTOR_TOKEN missing in .env")
        return 1

    print(f"IC AI Connector test -> {BASE}\n")
    passed = 0
    total = 0

    with httpx.Client(timeout=30.0) as client:
        total += 1
        try:
            r = client.get(f"{BASE}/health")
            ok = r.status_code == 200 and r.json().get("status") == "healthy"
            if check("GET /health", ok, r.text[:120]):
                passed += 1
        except Exception as exc:
            check("GET /health", False, str(exc))

        total += 1
        try:
            r = client.get(f"{BASE}/status", headers=hdrs())
            ok = r.status_code == 200
            if ok:
                body = r.json()
                detail = f"account={body.get('account')} mode={body.get('trade_mode')}"
            else:
                detail = r.text[:120]
            if check("GET /status (auth)", ok, detail):
                passed += 1
        except Exception as exc:
            check("GET /status (auth)", False, str(exc))

        total += 1
        try:
            r = client.get(f"{BASE}/status")
            if check("GET /status (no auth -> 401)", r.status_code == 401):
                passed += 1
        except Exception as exc:
            check("GET /status (no auth)", False, str(exc))

        total += 1
        try:
            r = client.post(f"{BASE}/test_connection", headers=hdrs(), json={})
            ok = r.status_code == 200 and r.json().get("success") is True
            detail = ""
            if ok:
                bal = r.json().get("balance_usdt", {})
                detail = f"markets={r.json().get('markets_loaded')} USDT free={bal.get('free')}"
            else:
                detail = r.text[:200]
            if check("POST /test_connection", ok, detail):
                passed += 1
        except Exception as exc:
            check("POST /test_connection", False, str(exc))

        total += 1
        try:
            r = client.post(f"{BASE}/balance", headers=hdrs(), json={})
            if check("POST /balance", r.status_code == 200):
                passed += 1
        except Exception as exc:
            check("POST /balance", False, str(exc))

        total += 1
        try:
            r = client.post(f"{BASE}/positions", headers=hdrs(), json={})
            body = r.json() if r.status_code == 200 else {}
            if check("POST /positions", r.status_code == 200, f"count={body.get('count')}"):
                passed += 1
        except Exception as exc:
            check("POST /positions", False, str(exc))

        total += 1
        try:
            r = client.get(f"{BASE}/symbols", params={"q": "BTC"})
            ok = r.status_code == 200 and len(r.json().get("symbols", [])) > 0
            if check("GET /symbols?q=BTC", ok):
                passed += 1
        except Exception as exc:
            check("GET /symbols", False, str(exc))

    print(f"\nResult: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
