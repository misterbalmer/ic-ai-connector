#!/usr/bin/env python3
"""Place SANDUSDT long via IC AI Connector (propose + confirm)."""

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

    # ~8 USDT notional at ~0.062
    price = 0.06190
    amount = 130.0  # ~8 USDT
    notional = round(amount * price, 2)
    sl = round(price * 0.95, 5)
    tp = round(price * 1.10, 5)

    payload = {
        "symbol": "SANDUSDT",
        "side": "buy",
        "amount": amount,
        "type": "market",
        "leverage": 2,
        "stop_loss": sl,
        "take_profit": tp,
        "notional_usdt": notional,
    }

    print(f"SAND long: {amount} SAND (~{notional} USDT) @ ~{price}")
    print(f"SL={sl}  TP={tp}")

    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{BASE}/trade/open", headers=headers, json=payload)
        print("propose:", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1
        body = r.json()
        print(body)

        if body.get("mode") == "auto":
            print("Executed (auto mode)")
            return 0

        pid = body.get("proposal", {}).get("proposal_id")
        if not pid:
            print("No proposal_id")
            return 1

        cr = client.post(f"{BASE}/trade/confirm", headers=headers, json={"proposal_id": pid})
        print("confirm:", cr.status_code)
        print(cr.text[:800])
        return 0 if cr.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
