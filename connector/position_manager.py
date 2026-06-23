"""Position management: LLM position_actions with server 40% profit gate."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

FORTY_PCT_PROFIT_THRESHOLD = 40.0
PARTIAL_CLOSE_PCT = 50.0
# Trigger within this % of entry counts as breakeven (profit-mgmt SL@entry).
ENTRY_TOLERANCE_PCT = 0.25


def _sym_key(symbol: str) -> str:
    """Normalize W/USDT:USDT, WUSDT, wusdt → WUSDT for position-state keys."""
    raw = symbol.upper().replace(" ", "")
    base = raw.split("/")[0].split(":")[0]
    if base.endswith("USDT"):
        return base
    return f"{base}USDT" if base else raw


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


def _is_entry_trigger(position: dict[str, Any], trigger: float) -> bool:
    entry = float(position.get("entryPrice") or 0)
    if entry <= 0 or trigger <= 0:
        return False
    return abs(trigger - entry) / entry * 100.0 <= ENTRY_TOLERANCE_PCT


def _reject(reason: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": "rejected", "reason": reason, **extra}
    logger.warning(
        "position_action rejected: %s symbol=%s pnl_pct=%s",
        reason,
        extra.get("symbol"),
        extra.get("pnl_pct"),
    )
    return payload


def _sym_state_bucket(state: dict[str, Any], symbol: str) -> dict[str, Any]:
    symbols_state: dict[str, Any] = state.setdefault("symbols", {})
    return symbols_state.setdefault(_sym_key(symbol), {})


def execute_position_action(
    action: dict[str, Any],
    *,
    exchange_svc: Any,
    maybe_execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    state_path: Path,
) -> dict[str, Any]:
    """Run one LLM position_actions item; 40% gate on partial + breakeven path."""
    kind = str(action.get("action") or "").lower().replace("-", "_")
    symbol = action.get("symbol")
    if not symbol:
        raise ValueError("position_action missing symbol")
    sym = str(symbol)

    if kind == "partial_close":
        pos = exchange_svc.fetch_position_for_symbol(sym)
        if not pos:
            return _reject("no_open_position", symbol=sym, action=kind)
        state = load_position_state(state_path)
        sym_state = _sym_state_bucket(state, sym)
        pnl = position_pnl_pct(pos)
        if sym_state.get("partial_50_taken"):
            return _reject(
                "partial_already_taken",
                symbol=sym,
                action=kind,
                pnl_pct=round(pnl, 2),
            )
        if pnl < FORTY_PCT_PROFIT_THRESHOLD:
            return _reject(
                "pnl_below_40",
                symbol=sym,
                action=kind,
                pnl_pct=round(pnl, 2),
                required_pct=FORTY_PCT_PROFIT_THRESHOLD,
            )
        result = maybe_execute(
            "partial_close",
            {"symbol": sym, "percentage": float(action.get("percentage", PARTIAL_CLOSE_PCT))},
        )
        if result.get("status") == "executed":
            sym_state["partial_50_taken"] = True
            sym_state["pnl_at_partial"] = round(pnl, 2)
            save_position_state(state_path, state)
            logger.info(
                "40%% partial allowed for %s (pnl=%.1f%%)",
                sym,
                pnl,
            )
        return {**result, "pnl_pct": round(pnl, 2), "gate": "forty_pct_partial"}

    if kind in ("set_sl", "move_sl", "breakeven_sl"):
        pos = exchange_svc.fetch_position_for_symbol(sym)
        trigger = action.get("trigger_price")
        if kind == "breakeven_sl" and pos:
            trigger = float(pos.get("entryPrice") or trigger or 0)
        if not trigger:
            raise ValueError("set_sl requires trigger_price or open position")
        trigger_f = float(trigger)
        is_breakeven = kind == "breakeven_sl" or (pos is not None and _is_entry_trigger(pos, trigger_f))

        if is_breakeven:
            if not pos:
                return _reject("no_open_position", symbol=sym, action=kind)
            state = load_position_state(state_path)
            sym_state = _sym_state_bucket(state, sym)
            pnl = position_pnl_pct(pos)
            if sym_state.get("breakeven_sl_set"):
                return _reject(
                    "breakeven_already_set",
                    symbol=sym,
                    action=kind,
                    pnl_pct=round(pnl, 2),
                )
            if not sym_state.get("partial_50_taken"):
                return _reject(
                    "partial_required_first",
                    symbol=sym,
                    action=kind,
                    pnl_pct=round(pnl, 2),
                    required_pct=FORTY_PCT_PROFIT_THRESHOLD,
                )

        close_side = action.get("side") or (_close_side(pos) if pos else None)
        if not close_side:
            raise ValueError("set_sl requires side when no open position")
        if action.get("cancel_existing_stops", True):
            exchange_svc.cancel_exit_algos(sym, sl=True, tp=False)
        result = maybe_execute(
            "set_sl",
            {
                "symbol": sym,
                "side": close_side,
                "trigger_price": trigger_f,
                "amount": action.get("amount"),
                "close_position": action.get("close_position", True),
            },
        )
        if is_breakeven and result.get("status") == "executed":
            state = load_position_state(state_path)
            sym_state = _sym_state_bucket(state, sym)
            sym_state["breakeven_sl_set"] = True
            if "pnl_at_partial" not in sym_state:
                sym_state["pnl_at_partial"] = round(position_pnl_pct(pos), 2)
            save_position_state(state_path, state)
            logger.info("breakeven SL set for %s @ %s", sym, trigger_f)
            return {**result, "gate": "forty_pct_breakeven"}
        return result

    if kind in ("set_tp", "set_tp_limit", "take_profit_limit"):
        pos = exchange_svc.fetch_position_for_symbol(sym)
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
                    "symbol": sym,
                    "side": close_side,
                    "trigger_price": trigger,
                    "limit_price": float(limit_price),
                    "amount": float(amount),
                },
            )
        return maybe_execute(
            "set_tp",
            {
                "symbol": sym,
                "side": close_side,
                "trigger_price": trigger,
                "amount": amount,
                "close_position": action.get("close_position", True),
            },
        )

    raise ValueError(f"Unknown position_action: {kind}")