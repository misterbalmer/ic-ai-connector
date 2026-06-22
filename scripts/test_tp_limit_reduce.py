#!/usr/bin/env python3
"""Test TAKE_PROFIT limit reduce via connector API (uses confirm queue)."""

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
SYMBOL = "SANDUSDT"


def api(method: str, path: str, body=None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        if method == "GET":
            return client.get(f"{BASE}{path}", headers=headers)
        return client.post(f"{BASE}{path}", headers=headers, json=body or {})


def confirm_if_needed(resp) -> dict:
    body = resp.json()
    print(resp.status_code, body.get("summary") or body.get("message") or body)
    if resp.status_code != 200:
        sys.exit(1)
    if body.get("mode") == "confirm":
        pid = body["proposal"]["proposal_id"]
        cr = api("POST", "/trade/confirm", {"proposal_id": pid})
        print("confirm:", cr.status_code)
        if cr.status_code != 200:
            print(cr.text)
            sys.exit(1)
        return cr.json().get("result", cr.json())
    return body.get("result", body)


def main() -> int:
    meta = api("GET", "/api/ui/meta")
    if meta.status_code != 200:
        print("Connector down:", meta.status_code)
        return 1
    print("Connector OK")

    pos = api("POST", "/positions", {}).json().get("active_positions", [])
    sand = [p for p in pos if "SAND" in str(p.get("symbol", "")).upper()]
    if not sand:
        print("No SAND position — skipping live TP limit test (open one first or use test_sand_sl_tp.py)")
        return 0

    p = sand[0]
    contracts = float(p.get("contracts") or 0)
    mark = float(p.get("markPrice") or p.get("entryPrice") or 0)
    if contracts <= 0 or mark <= 0:
        print("Invalid SAND position data")
        return 1

    tp_trigger = round(mark * 1.02, 5)
    tp_limit = tp_trigger
    qty = max(round(contracts * 0.1, 2), 1.0)

    print(f"\n=== SET TP LIMIT reduce {qty} @ trigger={tp_trigger} ===")
    result = confirm_if_needed(
        api(
            "POST",
            "/set_tp",
            {
                "symbol": SYMBOL,
                "side": "sell",
                "trigger_price": tp_trigger,
                "limit_price": tp_limit,
                "amount": qty,
                "order_type": "limit",
                "close_position": False,
            },
        )
    )
    order = result.get("order") or {}
    algo_id = order.get("algoId") or order.get("info", {}).get("algoId")
    print("TP limit algo:", algo_id or order)

    algos = api("GET", "/api/ui/dashboard").json().get("algo_orders", [])
    sand_algos = [a for a in algos if "SAND" in str(a.get("symbol", "")).upper()]
    print(f"\nOpen algos for SAND: {len(sand_algos)}")
    for a in sand_algos:
        print(
            f"  {a.get('orderType')} trigger={a.get('triggerPrice')} "
            f"qty={a.get('quantity')} id={a.get('algoId')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
