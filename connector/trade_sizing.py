"""Position sizing: SL-based leverage, min notional, margin cap."""

from __future__ import annotations

from typing import Any

MAX_CAPITAL_PCT_PER_TRADE = 0.25
DEFAULT_MAX_MARGIN_LOSS_ON_STOP = 0.35
DEFAULT_MIN_NOTIONAL_USDT = 5.0
MIN_SL_DISTANCE_PCT = 0.001


class TradeSizingError(ValueError):
    """Trade cannot be sized within risk / exchange limits."""


def sl_distance_pct(entry: float, stop_loss: float, side: str) -> float:
    """Fractional price distance from entry to stop (always positive)."""
    if entry <= 0:
        raise TradeSizingError("Invalid entry price for sizing")
    side_l = side.lower()
    if side_l in ("buy", "long"):
        dist = (entry - stop_loss) / entry
    else:
        dist = (stop_loss - entry) / entry
    if dist <= 0:
        raise TradeSizingError(
            f"Stop loss on wrong side of entry for {side_l} "
            f"(entry={entry}, stop={stop_loss})"
        )
    return max(dist, MIN_SL_DISTANCE_PCT)


def leverage_from_stop(
    entry: float,
    stop_loss: float,
    side: str,
    *,
    max_margin_loss_on_stop: float = DEFAULT_MAX_MARGIN_LOSS_ON_STOP,
    max_leverage: int = 125,
) -> int:
    """
    Max leverage so a stop hit loses ~max_margin_loss_on_stop of margin.

    Example: 35% max loss, 3.5% SL distance → 0.35 / 0.035 = 10x.
    """
    sl_pct = sl_distance_pct(entry, stop_loss, side)
    raw = max_margin_loss_on_stop / sl_pct
    lev = int(raw + 1e-6)
    if lev < 1:
        lev = 1
    return min(lev, max(1, max_leverage))


def min_notional_for_symbol(exchange_svc: Any, symbol: str, fallback: float) -> float:
    try:
        from connector.exchange import normalize_symbol

        sym = normalize_symbol(symbol)
        market = exchange_svc.exchange.market(sym)
        cost_min = (market.get("limits") or {}).get("cost", {}).get("min")
        if cost_min is not None and float(cost_min) > 0:
            return float(cost_min)
    except Exception:
        pass
    return fallback


def normalize_trade_size(
    trade: dict[str, Any],
    *,
    balance: dict[str, Any],
    entry_price: float,
    exchange_svc: Any,
    max_leverage: int,
    max_margin_loss_on_stop: float = DEFAULT_MAX_MARGIN_LOSS_ON_STOP,
    min_notional_usdt: float = DEFAULT_MIN_NOTIONAL_USDT,
    max_capital_pct: float = MAX_CAPITAL_PCT_PER_TRADE,
) -> dict[str, Any]:
    """
    Compute leverage from SL, enforce min notional, clamp to margin budget.

    margin_budget = balance.total × max_capital_pct
    max_notional = margin_budget × leverage
    """
    from connector.exchange import normalize_symbol

    payload = dict(trade)
    symbol = str(payload.get("symbol") or "")
    side = str(payload.get("side") or "buy")
    stop_loss = payload.get("stop_loss")
    if stop_loss is None:
        raise TradeSizingError(f"{symbol}: stop_loss required for sizing")
    stop_loss = float(stop_loss)
    entry = float(entry_price)
    if entry <= 0:
        raise TradeSizingError(f"{symbol}: invalid entry price {entry}")

    leverage = leverage_from_stop(
        entry,
        stop_loss,
        side,
        max_margin_loss_on_stop=max_margin_loss_on_stop,
        max_leverage=max_leverage,
    )
    payload["leverage"] = leverage

    total = float(balance.get("total") or 0)
    if total <= 0:
        raise TradeSizingError(f"{symbol}: zero balance — cannot size trade")

    margin_budget = total * max_capital_pct
    max_notional = margin_budget * leverage
    min_notional = min_notional_for_symbol(exchange_svc, symbol, min_notional_usdt)

    if max_notional < min_notional:
        raise TradeSizingError(
            f"{symbol}: max notional ${max_notional:.2f} (25% margin × {leverage}x) "
            f"below exchange minimum ${min_notional:.2f} — increase balance or widen SL"
        )

    llm_amount = float(payload.get("amount") or 0)
    if llm_amount > 0:
        notional = llm_amount * entry
    else:
        notional = max_notional

    if notional < min_notional:
        notional = min_notional
    if notional > max_notional:
        notional = max_notional

    sym = normalize_symbol(symbol)
    amount = notional / entry
    amount = float(exchange_svc.exchange.amount_to_precision(sym, amount))
    final_notional = amount * entry

    if final_notional < min_notional * 0.99:
        raise TradeSizingError(
            f"{symbol}: sized notional ${final_notional:.2f} below minimum ${min_notional:.2f}"
        )

    payload["amount"] = amount
    payload["notional_usdt"] = round(final_notional, 4)
    payload["sl_distance_pct"] = round(sl_distance_pct(entry, stop_loss, side) * 100, 3)
    payload["margin_est_usdt"] = round(final_notional / leverage, 4)
    return payload
