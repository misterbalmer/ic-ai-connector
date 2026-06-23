#!/usr/bin/env python3
"""Preflight checks before running the connector."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_PATH = ROOT / ".env"
VENV_WIN = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_UNIX = ROOT / ".venv" / "bin" / "python"

PLACEHOLDERS = (
    "your_binance_futures_api_key_here",
    "your_binance_futures_api_secret_here",
    "replace_with_at_least_32_character_random_string",
)


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    print("IC AI Connector — doctor\n")
    errors = 0

    if sys.version_info < (3, 11):
        fail(f"Python 3.11+ required (found {sys.version.split()[0]})")
        errors += 1
    else:
        ok(f"Python {sys.version.split()[0]}")

    if VENV_WIN.exists() or VENV_UNIX.exists():
        ok("Virtual environment (.venv)")
    else:
        fail("Virtual environment missing — run install.ps1 or ./install.sh")
        errors += 1

    if not ENV_PATH.exists():
        fail(".env missing — run install.ps1 or ./install.sh")
        errors += 1
    else:
        ok(".env present")
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        for key in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "CONNECTOR_TOKEN", "LIVE_TRADING_ACK"):
            val = os.getenv(key, "")
            if not val or val in PLACEHOLDERS:
                fail(f"{key} not configured")
                errors += 1
            else:
                ok(key)

    try:
        import ccxt  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        ok("Python dependencies import")
    except ImportError as exc:
        fail(f"Dependencies missing: {exc}")
        errors += 1

    if "--binance" in sys.argv and errors == 0:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        from connector.network_check import detect_key_network

        detected = detect_key_network(
            os.environ["BINANCE_API_KEY"],
            os.environ["BINANCE_API_SECRET"],
        )
        if detected == "mainnet":
            ok("Binance Futures mainnet API key")
        elif detected == "testnet":
            fail("API key is testnet — set USE_TESTNET=true or use mainnet keys")
            errors += 1
        else:
            fail("Binance API key could not authenticate")
            errors += 1

    print()
    if errors:
        print(f"Doctor: {errors} issue(s). Fix above, then retry.")
        return 1
    print("Doctor: all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())