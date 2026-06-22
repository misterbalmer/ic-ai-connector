#!/usr/bin/env python3
"""Unit tests for prompt compiler and JSON extraction (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connector.llm_client import _extract_json
from connector.orchestrator import build_feed_brief
from connector.prompt_compiler import compile_trader_prompt, load_trader_system_base


class FakeSettings:
    use_testnet = False
    trade_mode = "auto"


def test_load_trader_system():
    text = load_trader_system_base()
    assert "JSON" in text
    assert "coin_briefs" in text
    print("OK load_trader_system")


def test_build_feed_brief():
    snap = {"universe": [{"symbol": "AUSDT"}, {"symbol": "BUSDT"}]}
    brief, summary, lines = build_feed_brief(
        {
            "coin_briefs": [
                "AUSDT (P1): day_rvol 5 — watch.",
                "BUSDT (P3): day_rvol 2 — skip.",
            ],
        },
        snap,
    )
    assert summary is None
    assert len(lines) == 2
    assert brief.startswith("AUSDT (P1)")
    assert "BUSDT (P3)" in brief
    print("OK build_feed_brief")


def test_compile_prompt():
    prompt = compile_trader_prompt(
        settings=FakeSettings(),
        balance={"total": 12.5, "free": 12.0},
        positions=[],
        risk_status={"limits": {"max_leverage": 5}, "state": {"kill_switch": False}},
        konsole_snapshot={"universe": [{"symbol": "SANDUSDT"}]},
        ic_context={"trade_engine": {"symbols": {"SANDUSDT": {"sr": {"nearest_support": {"price": 0.055}}}}}},
    )
    assert "LIVE ACCOUNT" in prompt
    assert "KONSOLE SNAPSHOT" in prompt
    assert "IC CONTEXT" in prompt
    assert "trade_engine present" in prompt
    assert "sizing_policy" in prompt
    assert "leverage_rule" in prompt
    assert "TRADE_MODE=auto" in prompt
    print("OK compile_prompt")


def test_extract_json():
    raw = '{"brief": "hi", "action": "hold", "trades": []}'
    assert _extract_json(raw)["brief"] == "hi"
    wrapped = 'Here is output:\n```json\n{"brief": "x", "action": "no_action", "trades": []}\n```'
    assert _extract_json(wrapped)["action"] == "no_action"
    print("OK extract_json")


if __name__ == "__main__":
    test_load_trader_system()
    test_build_feed_brief()
    test_compile_prompt()
    test_extract_json()
    print("\nAll tests passed.")
