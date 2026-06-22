#!/usr/bin/env python3
"""Cancel existing SL algo order and set new stop loss."""

import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_URL = "https://fapi.binance.com"
CONNECTOR = f"http://{os.getenv('CONNECTOR_HOST', '127.0.0.1')}:{os.getenv('CONNECTOR_PORT', '8080')}"
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TOKEN = os.getenv("CONNECTOR_TOKEN", "")
SYMBOL = "SANDUSDT"
NEW_SL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.06


def signed_request(method: str, path: str, params: dict | None = None) -> httpx.Response:
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    qs = urlencode(params)
    sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}{path}?{qs}&signature={sig}"
    headers = {"X-MBX-APIKEY": API_KEY}
    with httpx.Client(timeout=15.0) as client:
        if method == "GET":
            return client.get(url, headers=headers)
        if method == "DELETE":
            return client.delete(url, headers=headers)
        return client.post(url, headers=headers)


def cancel_stop_algos() -> int:
    r = signed_request("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYMBOL})
    r.raise_for_status()
    cancelled = 0
    for algo in r.json():
        if algo.get("orderType") == "STOP_MARKET":
            aid = algo["algoId"]
            print(f"Cancelling SL algo {aid} (was @ {algo.get('triggerPrice')})")
            dr = signed_request("DELETE", "/fapi/v1/algoOrder", {"algoId": str(aid)})
            print(" ", dr.status_code, dr.text[:120])
            cancelled += 1
    return cancelled


def main() -> int:
    cancel_stop_algos()

    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{CONNECTOR}/set_sl",
            headers=headers,
            json={
                "symbol": SYMBOL,
                "side": "sell",
                "trigger_price": NEW_SL,
                "close_position": True,
            },
        )
        body = r.json()
        if r.status_code != 200:
            print("Propose failed:", body)
            return 1
        pid = body.get("proposal", {}).get("proposal_id")
        cr = client.post(f"{CONNECTOR}/trade/confirm", headers=headers, json={"proposal_id": pid})
        print(f"New SL @ {NEW_SL}:", cr.status_code, cr.text[:400])

    r = signed_request("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYMBOL})
    for algo in r.json():
        print(f"  {algo['orderType']} trigger={algo['triggerPrice']} algoId={algo['algoId']}")
    return 0 if cr.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
