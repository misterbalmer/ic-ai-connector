#!/usr/bin/env python3
"""
Optional testnet smoke test: propose → confirm → reject flow.
Does NOT place real trades unless you pass --execute-open with tiny size on testnet.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="IC AI Connector smoke test")
    parser.add_argument(
        "--execute-open",
        action="store_true",
        help="Propose and confirm a tiny BTC test trade (testnet only)",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--amount", type=float, default=0.001)
    args = parser.parse_args()

    if not TOKEN:
        print("CONNECTOR_TOKEN missing")
        return 1

    with httpx.Client(timeout=60.0) as client:
        # Risk status
        r = client.get(f"{BASE}/risk/status", headers=hdrs())
        print("Risk:", r.json() if r.status_code == 200 else r.text)

        # Propose-only dry run (invalid symbol to test queue without executing)
        r = client.post(
            f"{BASE}/trade/propose",
            headers=hdrs(),
            json={
                "action": "place_trade",
                "payload": {
                    "symbol": "DRYRUNTEST",
                    "side": "buy",
                    "type": "market",
                    "amount": 0.001,
                    "notional_usdt": 1,
                },
            },
        )
        if r.status_code == 403:
            print("Propose blocked by risk (expected if limits hit):", r.json().get("detail"))
        elif r.status_code == 200:
            prop = r.json().get("proposal", {})
            pid = prop.get("proposal_id")
            print("Proposal created:", pid)
            if pid:
                rr = client.post(
                    f"{BASE}/trade/reject",
                    headers=hdrs(),
                    json={"proposal_id": pid, "reason": "smoke test"},
                )
                print("Rejected:", rr.status_code, rr.text[:200])

        if not args.execute_open:
            print("\nDry run only. Use --execute-open on testnet to test confirm flow.")
            return 0

        if os.getenv("USE_TESTNET", "true").lower() not in ("1", "true", "yes"):
            print("Refusing --execute-open when USE_TESTNET is not true")
            return 1

        # Get mark for SL/TP placeholders
        ticker_r = client.get(f"{BASE}/symbols", params={"q": args.symbol[:3]})
        print("Symbols ok:", ticker_r.status_code)

        r = client.post(
            f"{BASE}/trade/open",
            headers=hdrs(),
            json={
                "symbol": args.symbol,
                "side": "buy",
                "amount": args.amount,
                "type": "market",
                "leverage": 2,
                "stop_loss": 1.0,
                "take_profit": 999999.0,
                "notional_usdt": 50,
            },
        )
        print("Open propose:", r.status_code, r.text[:400])
        if r.status_code != 200:
            return 1

        body = r.json()
        if body.get("mode") == "auto":
            print("Auto mode — trade executed directly")
            return 0

        pid = body.get("proposal", {}).get("proposal_id")
        if not pid:
            print("No proposal_id")
            return 1

        cr = client.post(
            f"{BASE}/trade/confirm",
            headers=hdrs(),
            json={"proposal_id": pid},
        )
        print("Confirm:", cr.status_code, cr.text[:500])
        return 0 if cr.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
