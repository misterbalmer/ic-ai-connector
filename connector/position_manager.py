"""Position management: 50% partial + breakeven, LLM position_actions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

FIFTY_PCT_PROFIT_THRESHOLD = 50.0
PARTIAL_CLOSE_PCT = 50.0


def _sym_key(symbol: str) -> str:
    return symbol.upper().replace(" ", "")


def load_position_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"symbols": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if "symbols" not in data:
        data["symbols"] = {}
    return data


def save_position_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def position_pnl_pct(position: dict[str, Any]) -> float:
    pct = position.get("percentage")
    if pct is not None:
        try:
            return float(pct)
        except (TypeError, ValueError):
            pass
    entry = float(position.get("entryPrice") or 0)
    mark = float(position.get("markPrice") or 0)
    if entry <= 0 or mark <= 0:
        return 0.0
    side = str(position.get("side", "")).lower()
    raw = ((mark - entry) / entry) * 100.0 if side == "long" else ((entry - mark) / entry) * 100.0
    lev = float(position.get("leverage") or 1)
    return raw * lev


def _close_side(position: dict[str, Any]) -> str:
    side = str(position.get("side", "")).lower()
    return "sell" if side == "long" else "buy"


def apply_fifty_percent_rule(
    *,
    exchange_svc: Any,
    positions: list[dict[str, Any]],
    state_path: Path,
    maybe_execute: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """At >=50% profit: partial close 50% and move SL to breakeven (once per symbol)."""
    state = load_position_state(state_path)
    symbols_state: dict[str, Any] = state.setdefault("symbols", {})
    results: list[dict[str, Any]] = []

    for pos in positions:
        symbol = str(pos.get("symbol") or "")
        if not symbol:
            continue
        key = _sym_key(symbol)
        sym_state = symbols_state.setdefault(key, {})
        if sym_state.get("partial_50_taken"):
            continue

        pnl = position_pnl_pct(pos)
        if pnl < FIFTY_PCT_PROFIT_THRESHOLD:
            continue

        logger.info("50%% rule triggered for %s (pnl=%.1f%%)", symbol, pnl)
        partial = maybe_execute(
            "partial_close",
            {"symbol": symbol, "percentage": PARTIAL_CLOSE_PCT},
        )
        entry = float(pos.get("entryPrice") or 0)
        breakeven = maybe_execute(
            "set_sl",
            {
                "symbol": symbol,
                "side": _close_side(pos),
                "trigger_price": entry,
                "close_position": True,
                "cancel_existing_stops": True,
            },
        )
        if partial.get("status") != "executed" or breakeven.get("status") != "executed":
            results.append(
                {
                    "symbol": symbol,
                    "rule": "fifty_percent_partial_breakeven",
                    "pnl_pct": pnl,
                    "partial_close": partial,
                    "breakeven": breakeven,
                    "skipped_state": True,
                }
            )
            continue
        sym_state["partial_50_taken"] = True
        sym_state["breakeven_sl_set"] = True
        sym_state["pnl_at_trigger"] = round(pnl, 2)
        results.append(
            {
                "symbol": symbol,
                "rule": "fifty_percent_partial_breakeven",
                "pnl_pct": pnl,
                "partial_close": partial,
                "breakeven": breakeven,
            }
        )

    if results:
        save_position_state(state_path, state)
    return results


def execute_position_action(
    action: dict[str, Any],
    *,
    exchange_svc: Any,
    maybe_execute: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Run one LLM position_actions item."""
    kind = str(action.get("action") or "").lower().replace("-", "_")
    symbol = action.get("symbol")
    if not symbol:
        raise ValueError("position_action missing symbol")

    if kind == "partial_close":
        return maybe_execute(
            "partial_close",
            {"symbol": symbol, "percentage": float(action.get("percentage", 50))},
        )

    if kind in ("set_sl", "move_sl", "breakeven_sl"):
        pos = exchange_svc.fetch_position_for_symbol(str(symbol))
        trigger = action.get("trigger_price")
        if kind == "breakeven_sl" and pos:
            trigger = float(pos.get("entryPrice") or trigger or 0)
        if not trigger:
            raise ValueError("set_sl requires trigger_price or open position")
        close_side = action.get("side") or (_close_side(pos) if pos else None)
        if not close_side:
            raise ValueError("set_sl requires side when no open position")
        if action.get("cancel_existing_stops", True):
            exchange_svc.cancel_exit_algos(str(symbol), sl=True, tp=False)
        return maybe_execute(
            "set_sl",
            {
                "symbol": symbol,
                "side": close_side,
                "trigger_price": float(trigger),
                "amount": action.get("amount"),
                "close_position": action.get("close_position", True),
            },
        )

    if kind in ("set_tp", "set_tp_limit", "take_profit_limit"):
        pos = exchange_svc.fetch_position_for_symbol(str(symbol))
        close_side = action.get("side") or (_close_side(pos) if pos else None)
        if not close_side:
            raise ValueError("set_tp requires side when no open position")
        trigger = float(action["trigger_price"])
        limit_price = action.get("limit_price") or trigger
        amount = action.get("amount")
        if amount is None and pos:
            amount = float(pos.get("contracts") or 0)
        use_limit = kind != "set_tp" or str(action.get("order_type", "limit")).lower() == "limit"
        if use_limit:
            if not amount or float(amount) <= 0:
                raise ValueError("set_tp_limit requires amount or open position")
            return maybe_execute(
                "set_tp_limit",
                {
                    "symbol": symbol,
                    "side": close_side,
                    "trigger_price": trigger,
                    "limit_price": float(limit_price),
                    "amount": float(amount),
                },
            )
        return maybe_execute(
            "set_tp",
            {
                "symbol": symbol,
                "side": close_side,
                "trigger_price": trigger,
                "amount": amount,
                "close_position": action.get("close_position", True),
            },
        )

    raise ValueError(f"Unknown position_action: {kind}")
