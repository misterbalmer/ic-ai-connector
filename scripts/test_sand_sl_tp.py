#!/usr/bin/env python3
"""Open SAND long with SL+TP, confirm, verify orders, optional close."""

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE = f"http://{os.getenv('CONNECTOR_HOST', '127.0.0.1')}:{os.getenv('CONNECTOR_PORT', '8080')}"
TOKEN = os.getenv("CONNECTOR_TOKEN", "")


def api(method: str, path: str, body=None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        if method == "GET":
            return client.get(f"{BASE}{path}", headers=headers)
        return client.post(f"{BASE}{path}", headers=headers, json=body or {})


def confirm_if_needed(resp) -> dict:
    body = resp.json()
    print(resp.status_code, body.get("message") or body.get("summary") or body)
    if resp.status_code != 200:
        sys.exit(1)
    if body.get("mode") == "confirm":
        pid = body["proposal"]["proposal_id"]
        cr = api("POST", "/trade/confirm", {"proposal_id": pid})
        print("confirm:", cr.status_code)
        result = cr.json()
        if cr.status_code != 200:
            print(result)
            sys.exit(1)
        return result.get("result", result)
    return body.get("result", body)


def main() -> int:
    # fetch price
    import httpx as hx

    price = float(hx.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": "SANDUSDT"}).json()["price"])
    amount = 130.0
    notional = round(amount * price, 2)
    sl = round(price * 0.95, 5)
    tp = round(price * 1.08, 5)

    print(f"\n=== OPEN SAND long ~{notional} USDT ===")
    print(f"price={price}  amount={amount}  SL={sl}  TP={tp}\n")

    result = confirm_if_needed(
        api(
            "POST",
            "/trade/open",
            {
                "symbol": "SANDUSDT",
                "side": "buy",
                "amount": amount,
                "type": "market",
                "leverage": 2,
                "stop_loss": sl,
                "take_profit": tp,
                "notional_usdt": notional,
            },
        )
    )
    print("\nEntry result keys:", list(result.keys()))
    if result.get("stop_loss"):
        print("SL order id:", result["stop_loss"].get("id") or result["stop_loss"].get("info", {}).get("orderId"))
    else:
        print("WARNING: no stop_loss in result")
    if result.get("take_profit"):
        print("TP order id:", result["take_profit"].get("id") or result["take_profit"].get("info", {}).get("orderId"))
    else:
        print("WARNING: no take_profit in result")

    time.sleep(1)
    with httpx.Client(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        orders = client.post(f"{BASE}/open_orders", headers=headers, params={"symbol": "SANDUSDT"}).json()
    print(f"\n=== Open orders for SAND ({orders.get('count', 0)}) ===")
    for o in orders.get("open_orders", []):
        info = o.get("info") or o
        print(
            f"  {info.get('type')} {info.get('side')} stop={info.get('stopPrice')} "
            f"status={info.get('status')} id={info.get('orderId') or o.get('id')}"
        )

    pos = api("POST", "/positions", {}).json()
    sand = [p for p in pos.get("active_positions", []) if "SAND" in str(p.get("symbol", ""))]
    print("\n=== Position ===")
    print(sand)

    if "--close" in sys.argv:
        print("\n=== Closing ===")
        confirm_if_needed(api("POST", "/partial_close", {"symbol": "SANDUSDT", "percentage": 100}))
        api("POST", "/cancel_orders", {"symbol": "SANDUSDT", "all_open": True})
        print("Closed + cancelled remaining orders")

    return 0


if __name__ == "__main__":
    sys.exit(main())
