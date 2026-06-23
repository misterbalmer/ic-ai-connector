#!/usr/bin/env python3
"""Unit tests for position manager (no network)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connector.position_manager import (
    FORTY_PCT_PROFIT_THRESHOLD,
    _sym_key,
    execute_position_action,
    position_pnl_pct,
)


class FakeExchange:
    def __init__(self, positions: dict[str, dict]):
        self.positions = positions
        self.cancelled: list[str] = []

    def fetch_position_for_symbol(self, symbol: str):
        return self.positions.get(symbol) or self.positions.get(_sym_key(symbol))

    def cancel_exit_algos(self, symbol: str, sl: bool = True, tp: bool = True):
        self.cancelled.append(symbol)


def test_position_pnl_pct():
    assert position_pnl_pct({"percentage": 55.0}) == 55.0
    pos = {"side": "long", "entryPrice": 100, "markPrice": 110, "leverage": 3}
    assert position_pnl_pct(pos) == 30.0
    print("OK position_pnl_pct")


def test_sym_key_normalizes_ccxt_symbol():
    assert _sym_key("W/USDT:USDT") == "WUSDT"
    assert _sym_key("wusdt") == "WUSDT"
    print("OK sym_key")


def test_partial_rejected_below_40():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "position-state.json"
        ex = FakeExchange(
            {
                "WUSDT": {
                    "symbol": "W/USDT:USDT",
                    "side": "long",
                    "entryPrice": 0.01047,
                    "markPrice": 0.01054,
                    "leverage": 20,
                    "percentage": 5.0,
                }
            }
        )
        result = execute_position_action(
            {"action": "partial_close", "symbol": "WUSDT", "percentage": 50},
            exchange_svc=ex,
            maybe_execute=lambda _a, _p: {"status": "executed"},
            state_path=state_path,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "pnl_below_40"
        print("OK partial_rejected_below_40")


def test_partial_allowed_at_40_then_breakeven():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "position-state.json"
        executed: list[tuple[str, dict]] = []

        def maybe_execute(action: str, payload: dict):
            executed.append((action, payload))
            return {"status": "executed", "action": action}

        pos = {
            "symbol": "W/USDT:USDT",
            "side": "long",
            "entryPrice": 0.01047,
            "percentage": 42.0,
        }
        ex = FakeExchange({"WUSDT": pos, "W/USDT:USDT": pos})

        partial = execute_position_action(
            {"action": "partial_close", "symbol": "WUSDT", "percentage": 50},
            exchange_svc=ex,
            maybe_execute=maybe_execute,
            state_path=state_path,
        )
        assert partial["status"] == "executed"
        assert executed[0][0] == "partial_close"

        breakeven = execute_position_action(
            {"action": "breakeven_sl", "symbol": "WUSDT"},
            exchange_svc=ex,
            maybe_execute=maybe_execute,
            state_path=state_path,
        )
        assert breakeven["status"] == "executed"
        assert executed[1][0] == "set_sl"
        assert executed[1][1]["trigger_price"] == 0.01047

        repeat = execute_position_action(
            {"action": "partial_close", "symbol": "WUSDT", "percentage": 50},
            exchange_svc=ex,
            maybe_execute=maybe_execute,
            state_path=state_path,
        )
        assert repeat["status"] == "rejected"
        assert repeat["reason"] == "partial_already_taken"
        print("OK partial_then_breakeven")


def test_breakeven_rejected_without_partial_first():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "position-state.json"
        pos = {
            "symbol": "QNTUSDT",
            "side": "long",
            "entryPrice": 70.0,
            "percentage": 45.0,
        }
        ex = FakeExchange({"QNTUSDT": pos})
        result = execute_position_action(
            {"action": "breakeven_sl", "symbol": "QNTUSDT"},
            exchange_svc=ex,
            maybe_execute=lambda _a, _p: {"status": "executed"},
            state_path=state_path,
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "partial_required_first"
        print("OK breakeven_requires_partial_first")


def test_set_sl_non_breakeven_not_gated():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "position-state.json"
        pos = {
            "symbol": "SANDUSDT",
            "side": "long",
            "entryPrice": 0.06,
            "percentage": 5.0,
        }
        ex = FakeExchange({"SANDUSDT": pos})
        result = execute_position_action(
            {
                "action": "set_sl",
                "symbol": "SANDUSDT",
                "side": "sell",
                "trigger_price": 0.055,
            },
            exchange_svc=ex,
            maybe_execute=lambda _a, _p: {"status": "executed"},
            state_path=state_path,
        )
        assert result["status"] == "executed"
        print("OK set_sl_risk_adjustment_ungated")


if __name__ == "__main__":
    test_position_pnl_pct()
    test_sym_key_normalizes_ccxt_symbol()
    test_partial_rejected_below_40()
    test_partial_allowed_at_40_then_breakeven()
    test_breakeven_rejected_without_partial_first()
    test_set_sl_non_breakeven_not_gated()
    print(f"\nAll tests passed (threshold={FORTY_PCT_PROFIT_THRESHOLD}%).")