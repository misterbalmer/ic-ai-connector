#!/usr/bin/env python3
"""Unit tests for position manager (no network)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connector.position_manager import (
    FIFTY_PCT_PROFIT_THRESHOLD,
    apply_fifty_percent_rule,
    position_pnl_pct,
)


def test_position_pnl_pct():
    assert position_pnl_pct({"percentage": 55.0}) == 55.0
    pos = {"side": "long", "entryPrice": 100, "markPrice": 110, "leverage": 3}
    assert position_pnl_pct(pos) == 30.0
    print("OK position_pnl_pct")


def test_fifty_percent_rule_triggers_once():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "position-state.json"
        executed: list[tuple[str, dict]] = []

        def maybe_execute(action: str, payload: dict):
            executed.append((action, payload))
            return {"status": "executed", "action": action}

        positions = [{"symbol": "SAND/USDT:USDT", "side": "long", "entryPrice": 0.1, "percentage": 52}]
        results = apply_fifty_percent_rule(
            exchange_svc=object(),
            positions=positions,
            state_path=state_path,
            maybe_execute=maybe_execute,
        )
        assert len(results) == 1
        assert executed[0][0] == "partial_close"
        assert executed[0][1]["percentage"] == 50
        assert executed[1][0] == "set_sl"

        results2 = apply_fifty_percent_rule(
            exchange_svc=object(),
            positions=positions,
            state_path=state_path,
            maybe_execute=maybe_execute,
        )
        assert len(results2) == 0
        assert len(executed) == 2
        print("OK fifty_percent_rule")


if __name__ == "__main__":
    test_position_pnl_pct()
    test_fifty_percent_rule_triggers_once()
    print(f"\nAll tests passed (threshold={FIFTY_PCT_PROFIT_THRESHOLD}%).")
