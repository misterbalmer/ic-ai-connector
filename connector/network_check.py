"""Detect mainnet vs testnet API key mismatch."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

MAINNET_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


def _signed_get(base: str, path: str, api_key: str, api_secret: str) -> tuple[int, str]:
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{qs}&signature={sig}"
    with httpx.Client(timeout=15.0) as client:
        r = client.get(url, headers={"X-MBX-APIKEY": api_key})
        return r.status_code, r.text[:200]


def detect_key_network(api_key: str, api_secret: str) -> str | None:
    """Return 'mainnet', 'testnet', or None if key works on neither."""
    main_code, _ = _signed_get(MAINNET_BASE, "/fapi/v3/account", api_key, api_secret)
    if main_code == 200:
        return "mainnet"
    test_code, _ = _signed_get(TESTNET_BASE, "/fapi/v3/account", api_key, api_secret)
    if test_code == 200:
        return "testnet"
    return None


def validate_network_config(use_testnet: bool, api_key: str, api_secret: str) -> None:
    detected = detect_key_network(api_key, api_secret)
    if detected is None:
        raise ValueError(
            "Binance API key could not authenticate on mainnet or testnet futures. "
            "Check key, IP whitelist, and Futures permissions."
        )
    expected = "testnet" if use_testnet else "mainnet"
    if detected != expected:
        raise ValueError(
            f"USE_TESTNET={use_testnet} but your API key is for {detected}. "
            f"Set USE_TESTNET={'true' if detected == 'testnet' else 'false'} "
            f"and update .env accordingly."
            + (
                " For mainnet also set LIVE_TRADING_ACK=I_ACCEPT_LIVE_RISK."
                if detected == "mainnet"
                else ""
            )
        )
    logger.info("API key verified for %s futures", detected)
