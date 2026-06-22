"""Compile trader system prompt + live context (trading-dashboard pattern)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def load_trader_system_base() -> str:
    path = AGENTS_DIR / "trader_system.txt"
    if not path.exists():
        raise FileNotFoundError(f"Missing agent prompt: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("trader_system.txt is empty")
    return text


def build_account_block(
    *,
    settings: Any,
    balance: dict[str, Any],
    positions: list[dict[str, Any]],
    risk_status: dict[str, Any],
) -> str:
    total = float(balance.get("total") or 0)
    max_margin = round(total * 0.25, 2) if total > 0 else 0
    payload = {
        "account": "live" if not settings.use_testnet else "testnet",
        "trade_mode": settings.trade_mode,
        "balance_usdt": balance,
        "open_positions": positions,
        "risk_limits": risk_status.get("limits"),
        "risk_state": risk_status.get("state"),
        "sizing_policy": {
            "max_margin_pct_per_trade": 0.25,
            "max_margin_usdt_per_trade": max_margin,
            "max_margin_loss_on_stop_pct": getattr(settings, "max_margin_loss_on_stop", 0.35),
            "min_notional_usdt": getattr(settings, "min_notional_usdt", 5.0),
            "max_leverage_cap": getattr(settings, "max_leverage", 20),
            "leverage_rule": "floor(max_margin_loss_on_stop / sl_distance) capped at max_leverage_cap",
            "leverage_example": "3.5% SL → 10x (35% max loss on margin if stop hits)",
            "amount_rule": "Provide stop_loss + side; server computes leverage and amount (min $5 notional)",
            "min_risk_reward": 1.0,
        },
    }
    return "=== LIVE ACCOUNT ===\n" + json.dumps(payload, indent=2, default=str)


def build_konsole_block(snapshot: dict[str, Any]) -> str:
    return "=== KONSOLE SNAPSHOT ===\n" + json.dumps(snapshot, indent=2, default=str)


def build_ic_context_block(ic_context: dict[str, Any] | None) -> str:
    if not ic_context:
        return (
            "=== IC CONTEXT ===\n"
            "(none — trade_engine S/R + 1H EMA200 not yet attached; "
            "use universe[] only; prefer watch/no_action over inventing levels)"
        )
    te = ic_context.get("trade_engine")
    header = "=== IC CONTEXT ===\n"
    if isinstance(te, dict) and te.get("symbols"):
        n = len(te["symbols"])
        header += f"(trade_engine present — {n} symbol(s) with S/R + 1H EMA200)\n"
    return header + json.dumps(ic_context, indent=2, default=str)


def compile_trader_prompt(
    *,
    settings: Any,
    balance: dict[str, Any],
    positions: list[dict[str, Any]],
    risk_status: dict[str, Any],
    konsole_snapshot: dict[str, Any],
    ic_context: dict[str, Any] | None = None,
) -> str:
    """Full system prompt: static agent file + live account + snapshot context."""
    base = load_trader_system_base()
    trade_note = f"\n\n=== RUNTIME ===\nTRADE_MODE={settings.trade_mode}\n"
    return (
        base
        + trade_note
        + "\n\n"
        + build_account_block(
            settings=settings,
            balance=balance,
            positions=positions,
            risk_status=risk_status,
        )
        + "\n\n"
        + build_konsole_block(konsole_snapshot)
        + "\n\n"
        + build_ic_context_block(ic_context)
    )


def user_message_for_cycle(snapshot_at: str | None = None) -> str:
    ts = snapshot_at or "now"
    return (
        f"Konsole decision cycle at {ts}. "
        "Analyze KONSOLE SNAPSHOT (top-20 universe[]: P1→P2→P3→Watch, day_rvol within tier) and IC CONTEXT trade_engine S/R if present. "
        "Run gates: participation → extension (check ma_stack_4h.bars_since_stack_aligned before energy_z) → S/R → acceptance → OI/structure. "
        "Return coin_briefs only (no preamble, no summary): exactly one line per universe[] row in snapshot order (all 20 — include every P2, P3, Watch, untiered; never skip). "
        "Line format: SYMBOL (tier): day_rvol, energy_trend, energy_phase, energy_z, structure_4h, structure_1w — verdict. "
        "watchlist max 3 for detailed defers only. Return JSON only."
    )
