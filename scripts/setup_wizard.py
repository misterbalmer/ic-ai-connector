#!/usr/bin/env python3
"""First-run setup: create .env, generate token, collect API keys."""

from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / "env.example"

PLACEHOLDERS = (
    "your_binance_futures_api_key_here",
    "your_binance_futures_api_secret_here",
    "replace_with_at_least_32_character_random_string",
)


def _is_placeholder(value: str) -> bool:
    v = value.strip()
    return not v or v in PLACEHOLDERS or "your_" in v or "replace_with" in v


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _write_env(values: dict[str, str]) -> None:
    lines: list[str] = []
    if EXAMPLE_PATH.exists():
        for raw in EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("#") or not raw.strip():
                lines.append(raw)
                continue
            if "=" not in raw:
                lines.append(raw)
                continue
            key, _, _ = raw.partition("=")
            key = key.strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
            else:
                lines.append(raw)
    else:
        for key, val in values.items():
            lines.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _configured(env: dict[str, str]) -> bool:
    return not _is_placeholder(env.get("BINANCE_API_KEY", "")) and not _is_placeholder(
        env.get("BINANCE_API_SECRET", "")
    ) and not _is_placeholder(env.get("CONNECTOR_TOKEN", ""))


def main() -> int:
    env = _read_env(ENV_PATH)
    if _configured(env) and "--force" not in sys.argv:
        print(f"[OK] Already configured: {ENV_PATH}")
        print("     Run start.ps1 (Windows) or ./start.sh (Mac/Linux).")
        return 0

    print("IC AI Connector — setup")
    print("=" * 40)

    if not EXAMPLE_PATH.exists():
        print(f"[FAIL] Missing {EXAMPLE_PATH}")
        return 1

    base = _read_env(EXAMPLE_PATH)
    token = secrets.token_urlsafe(32)
    base["CONNECTOR_TOKEN"] = token

    interactive = sys.stdin.isatty() and "--non-interactive" not in sys.argv
    if interactive:
        print("\nBinance USD-M Futures API credentials (Futures enabled, IP whitelist if set).")
        api_key = input("API Key: ").strip()
        api_secret = getpass.getpass("API Secret: ").strip()
        if not api_key or not api_secret:
            print("[FAIL] API key and secret are required.")
            return 1
        ack = input("Type I_ACCEPT_LIVE_RISK to trade live: ").strip()
        if ack != "I_ACCEPT_LIVE_RISK":
            print("[FAIL] Live trading requires: I_ACCEPT_LIVE_RISK")
            return 1
        base["BINANCE_API_KEY"] = api_key
        base["BINANCE_API_SECRET"] = api_secret
        base["LIVE_TRADING_ACK"] = "I_ACCEPT_LIVE_RISK"
    else:
        print("[..] Non-interactive: created .env with generated token.")
        print("     Edit .env and add your Binance API keys before starting.")

    _write_env(base)
    print(f"\n[OK] Wrote {ENV_PATH}")
    print(f"[OK] CONNECTOR_TOKEN generated ({len(token)} chars)")
    print("\nNext:")
    print("  Windows:  .\\start.ps1")
    print("  Mac/Linux: ./start.sh")
    print("  IC pair:   scripts/setup-ic-egress (see README)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())