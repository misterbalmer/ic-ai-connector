#!/usr/bin/env python3
"""Place TP limit on first open position (confirm + execute)."""

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


def main() -> int:
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as c:
        pos = c.post(f"{BASE}/positions", headers=headers).json().get("active_positions", [])
        if not pos:
            print("No open positions")
            return 0
        p = pos[0]
        raw = str(p.get("symbol", ""))
        sym = raw.split(":")[0].replace("/", "")
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        contracts = float(p.get("contracts") or 0)
        mark = float(p.get("markPrice") or p.get("entryPrice") or 0)
        side = str(p.get("side", "long")).lower()
        close = "sell" if side == "long" else "buy"
        tp = round(mark * 1.03, 6)
        qty = max(round(contracts * 0.05, 3), round(contracts * 0.01, 3))
        print(f"Position {sym} {side} qty={contracts} mark={mark} -> TP limit qty={qty} @ {tp}")
        body = {
            "symbol": sym,
            "side": close,
            "trigger_price": tp,
            "limit_price": tp,
            "amount": qty,
            "order_type": "limit",
            "close_position": False,
        }
        r = c.post(f"{BASE}/set_tp", headers=headers, json=body)
        data = r.json()
        print("propose:", r.status_code, data.get("summary") or data)
        if r.status_code != 200:
            return 1
        if data.get("mode") == "confirm":
            pid = data["proposal"]["proposal_id"]
            cr = c.post(f"{BASE}/trade/confirm", headers=headers, json={"proposal_id": pid})
            print("confirm:", cr.status_code, cr.text[:600])
            if cr.status_code != 200:
                return 1
        dash = c.get(f"{BASE}/api/ui/dashboard", headers=headers).json()
        algos = dash.get("algo_orders", [])
        print(f"Open algos: {len(algos)}")
        for a in algos:
            print(
                f"  {a.get('symbol')} {a.get('orderType')} "
                f"trigger={a.get('triggerPrice')} qty={a.get('quantity')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
