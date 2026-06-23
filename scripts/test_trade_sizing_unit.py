#!/usr/bin/env python3
"""Unit tests for SL-based leverage and min notional sizing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connector.trade_sizing import (
    TradeSizingError,
    leverage_from_stop,
    normalize_trade_size,
    sl_distance_pct,
)


class FakeExchange:
    def market(self, sym):
        return {
            "limits": {
                "cost": {"min": 5.0},
                "amount": {"min": 1.0, "step": 1.0},
            },
            "precision": {"amount": 0},
        }

    def amount_to_precision(self, sym, amount):
        return str(int(float(amount)))


class FakeExchangeSvc:
    exchange = FakeExchange()


def test_sl_distance_long():
    assert abs(sl_distance_pct(1.07, 1.053, "buy") - 0.015887) < 0.001


def test_leverage_3_5_pct_sl():
    lev = leverage_from_stop(1.0, 0.965, "buy", max_leverage=125)
    assert lev == 10


def test_leverage_7_pct_sl():
    lev = leverage_from_stop(1.0, 0.93, "buy", max_leverage=125)
    assert lev == 5


def test_leverage_capped():
    lev = leverage_from_stop(1.0, 0.965, "buy", max_leverage=5)
    assert lev == 5


def test_normalize_bumps_to_min_notional():
    trade = {
        "symbol": "AXSUSDT",
        "side": "buy",
        "amount": 3.0,
        "stop_loss": 1.033,
    }
    out = normalize_trade_size(
        trade,
        balance={"total": 100.0},
        entry_price=1.07,
        exchange_svc=FakeExchangeSvc(),
        max_leverage=20,
    )
    assert out["leverage"] >= 1
    assert out["notional_usdt"] >= 5.0
    assert out["amount"] * 1.07 >= 5.0


def test_normalize_rejects_tiny_balance():
    trade = {
        "symbol": "AXSUSDT",
        "side": "buy",
        "amount": 3.0,
        "stop_loss": 0.65,
    }
    try:
        normalize_trade_size(
            trade,
            balance={"total": 15.0},
            entry_price=1.0,
            exchange_svc=FakeExchangeSvc(),
            max_leverage=20,
        )
        raise AssertionError("expected TradeSizingError")
    except TradeSizingError as exc:
        assert "minimum" in str(exc).lower() or "below" in str(exc).lower()


def test_precision_rounding_bumps_to_min_notional():
    """Integer qty step can round $5 target down to $4.95 — must bump to next step."""
    trade = {
        "symbol": "WUSDT",
        "side": "buy",
        "amount": 33.0,
        "stop_loss": 0.14,
    }
    out = normalize_trade_size(
        trade,
        balance={"total": 100.0},
        entry_price=0.15,
        exchange_svc=FakeExchangeSvc(),
        max_leverage=20,
    )
    assert out["amount"] * 0.15 >= 5.0
    assert out["notional_usdt"] >= 5.0


def test_missing_stop_rejected():
    try:
        normalize_trade_size(
            {"symbol": "X", "side": "buy", "amount": 1},
            balance={"total": 100},
            entry_price=1.0,
            exchange_svc=FakeExchangeSvc(),
            max_leverage=10,
        )
        raise AssertionError("expected TradeSizingError")
    except TradeSizingError:
        pass


if __name__ == "__main__":
    test_sl_distance_long()
    test_leverage_3_5_pct_sl()
    test_leverage_7_pct_sl()
    test_leverage_capped()
    test_normalize_bumps_to_min_notional()
    test_normalize_rejects_tiny_balance()
    test_precision_rounding_bumps_to_min_notional()
    test_missing_stop_rejected()
    print("All trade sizing tests passed.")
