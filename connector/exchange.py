"""Binance USDT-M Futures via ccxt."""

from __future__ import annotations

import logging
from typing import Any

import ccxt

from connector.config import Settings

logger = logging.getLogger(__name__)


def normalize_symbol(user_symbol: str) -> str:
    s = user_symbol.upper().strip()
    if "/" in s:
        return s
    for quote in ("USDT", "BUSD", "USDC", "FDUSD"):
        if s.endswith(quote):
            base = s[:- len(quote)]
            return f"{base}/{quote}:{quote}"
    if len(s) > 4:
        return f"{s[:-4]}/{s[-4:]}:{s[-4:]}"
    return s


def binance_raw_symbol(user_symbol: str) -> str:
    s = user_symbol.upper().strip()
    if "/" in s:
        return s.split("/")[0] + s.split("/")[1].split(":")[0]
    return s.replace("/", "").split(":")[0]


def create_exchange(settings: Settings) -> ccxt.binance:
    exchange = ccxt.binance(
        {
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_api_secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {
                "defaultType": "future",
                # USDT-M only — skip spot/inverse (dapi) so startup does not hang on dapi.
                "fetchMarkets": {"types": ["linear"]},
                "fetchMargins": False,
                "fetchCurrencies": False,
            },
            "verbose": False,
        }
    )
    if settings.use_testnet:
        test = exchange.urls.get("test") or {}
        api = dict(exchange.urls.get("api") or {})
        for key, url in test.items():
            if key.startswith("fapi"):
                api[key] = url
        exchange.urls["api"] = api
        logger.info("Using Binance Futures TESTNET (fapi URLs)")
    else:
        logger.info("Using Binance Futures MAINNET")
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            exchange.load_markets()
            logger.info("Loaded %s USDT-M markets", len(exchange.markets or {}))
            return exchange
        except (ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            last_err = exc
            logger.warning("load_markets failed (attempt %s/3): %s", attempt, exc)
    assert last_err is not None
    raise last_err


class ExchangeService:
    def __init__(self, exchange: ccxt.binance) -> None:
        self.exchange = exchange

    def test_connection(self) -> dict[str, Any]:
        balance = self.fetch_balance_summary()
        return {
            "markets_loaded": len(self.exchange.markets or {}),
            "balance_usdt": balance,
        }

    def fetch_balance_summary(self) -> dict[str, Any]:
        balance = self.exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        return {
            "total": usdt.get("total") or balance.get("total", {}).get("USDT"),
            "free": usdt.get("free") or balance.get("free", {}).get("USDT"),
            "used": usdt.get("used") or balance.get("used", {}).get("USDT"),
        }

    def fetch_active_positions(self) -> list[dict[str, Any]]:
        try:
            return self._fetch_positions_ccxt()
        except Exception as exc:
            logger.warning("fetch_positions via ccxt failed (%s), trying account API", exc)
            try:
                return self._fetch_positions_from_account()
            except Exception as inner:
                logger.error("fetch_positions from account failed: %s", inner)
                raise

    def _fetch_positions_ccxt(self) -> list[dict[str, Any]]:
        positions = self.exchange.fetch_positions()
        active: list[dict[str, Any]] = []
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts == 0:
                continue
            active.append(
                {
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "contracts": contracts,
                    "entryPrice": p.get("entryPrice"),
                    "markPrice": p.get("markPrice"),
                    "unrealizedPnl": p.get("unrealizedPnl"),
                    "leverage": p.get("leverage"),
                    "percentage": p.get("percentage"),
                    "liquidationPrice": p.get("liquidationPrice"),
                    "initialMargin": p.get("initialMargin"),
                    "notional": p.get("notional"),
                }
            )
        return active

    def _fetch_positions_from_account(self) -> list[dict[str, Any]]:
        """Fallback: parse positions from GET /fapi/v3/account (works on some testnet keys)."""
        account = self.exchange.fapiPrivateV3GetAccount()
        active: list[dict[str, Any]] = []
        for p in account.get("positions") or []:
            amt = float(p.get("positionAmt") or 0)
            if amt == 0:
                continue
            sym_raw = p.get("symbol", "")
            sym = normalize_symbol(sym_raw) if sym_raw else sym_raw
            side = "long" if amt > 0 else "short"
            active.append(
                {
                    "symbol": sym,
                    "side": side,
                    "contracts": abs(amt),
                    "entryPrice": float(p.get("entryPrice") or 0),
                    "markPrice": None,
                    "unrealizedPnl": float(p.get("unrealizedProfit") or 0),
                    "leverage": int(float(p.get("leverage") or 1)),
                    "percentage": None,
                }
            )
        return active

    def count_open_positions(self) -> int:
        return len(self.fetch_active_positions())

    def fetch_open_orders(self, symbol: str | None = None) -> list[Any]:
        if symbol:
            return self.exchange.fetch_open_orders(normalize_symbol(symbol))
        return self.exchange.fetch_open_orders()

    def estimate_notional(self, symbol: str, amount: float, price: float | None = None) -> float:
        sym = normalize_symbol(symbol)
        if price is not None:
            return amount * price
        ticker = self.exchange.fetch_ticker(sym)
        mark = ticker.get("last") or ticker.get("close") or 0
        return amount * float(mark)

    def set_leverage(self, symbol: str, leverage: int) -> None:
        sym = normalize_symbol(symbol)
        self.exchange.set_leverage(leverage, sym)

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float | None = None,
        reduce_only: bool = False,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sym = normalize_symbol(symbol)
        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True
        if extra_params:
            params.update(extra_params)
        order = self.exchange.create_order(
            symbol=sym,
            type=order_type.lower(),
            side=side.lower(),
            amount=amount,
            price=price,
            params=params,
        )
        return order

    def place_stop_loss(
        self,
        *,
        symbol: str,
        side: str,
        trigger_price: float,
        amount: float | None = None,
        close_position: bool = True,
    ) -> dict[str, Any]:
        raw_sym = binance_raw_symbol(symbol)
        sym = normalize_symbol(symbol)
        trigger = float(self.exchange.price_to_precision(sym, trigger_price))
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": raw_sym,
            "side": side.upper(),
            "type": "STOP_MARKET",
            "triggerPrice": trigger,
            "reduceOnly": True,
        }
        if close_position and amount is None:
            params["closePosition"] = True
        else:
            qty = amount or 0
            params["quantity"] = self.exchange.amount_to_precision(sym, qty)
        try:
            return self.exchange.fapiPrivatePostAlgoOrder(params)
        except Exception as exc:
            logger.warning("Algo SL failed (%s), falling back to stop_market order", exc)
            fallback_params: dict[str, Any] = {"stopPrice": trigger_price}
            if close_position and amount is None:
                fallback_params["closePosition"] = True
            else:
                fallback_params["reduceOnly"] = True
            return self.exchange.create_order(
                symbol=sym,
                type="stop_market",
                side=side.lower(),
                amount=amount or 0,
                params=fallback_params,
            )

    def place_take_profit(
        self,
        *,
        symbol: str,
        side: str,
        trigger_price: float,
        amount: float | None = None,
        close_position: bool = True,
    ) -> dict[str, Any]:
        raw_sym = binance_raw_symbol(symbol)
        sym = normalize_symbol(symbol)
        trigger = float(self.exchange.price_to_precision(sym, trigger_price))
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": raw_sym,
            "side": side.upper(),
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": trigger,
            "reduceOnly": True,
        }
        if close_position and amount is None:
            params["closePosition"] = True
        else:
            params["quantity"] = self.exchange.amount_to_precision(sym, amount or 0)
        try:
            return self.exchange.fapiPrivatePostAlgoOrder(params)
        except Exception as exc:
            logger.warning("Algo TP market failed (%s), falling back", exc)
            fallback_params: dict[str, Any] = {"stopPrice": trigger_price}
            if close_position and amount is None:
                fallback_params["closePosition"] = True
            else:
                fallback_params["reduceOnly"] = True
            return self.exchange.create_order(
                symbol=sym,
                type="take_profit_market",
                side=side.lower(),
                amount=amount or 0,
                params=fallback_params,
            )

    def place_take_profit_limit(
        self,
        *,
        symbol: str,
        side: str,
        trigger_price: float,
        limit_price: float,
        amount: float,
    ) -> dict[str, Any]:
        """TAKE_PROFIT limit reduce — catches wicks better than market TP."""
        raw_sym = binance_raw_symbol(symbol)
        sym = normalize_symbol(symbol)
        trigger = float(self.exchange.price_to_precision(sym, trigger_price))
        limit_px = float(self.exchange.price_to_precision(sym, limit_price))
        qty = float(self.exchange.amount_to_precision(sym, amount))
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": raw_sym,
            "side": side.upper(),
            "type": "TAKE_PROFIT",
            "quantity": qty,
            "price": limit_px,
            "triggerPrice": trigger,
            "reduceOnly": True,
            "timeInForce": "GTC",
        }
        return self.exchange.fapiPrivatePostAlgoOrder(params)

    def move_stop_to_breakeven(
        self,
        *,
        symbol: str,
        close_side: str,
        entry_price: float,
    ) -> dict[str, Any]:
        self.cancel_exit_algos(symbol, sl=True, tp=False)
        return self.place_stop_loss(
            symbol=symbol,
            side=close_side,
            trigger_price=entry_price,
            close_position=True,
        )

    def fetch_position_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        sym = normalize_symbol(symbol)
        for p in self.fetch_active_positions():
            if p.get("symbol") == sym or normalize_symbol(str(p.get("symbol", ""))) == sym:
                return p
        return None

    def partial_close(self, symbol: str, percentage: float) -> dict[str, Any]:
        sym = normalize_symbol(symbol)
        pos = self.fetch_position_for_symbol(sym)
        if not pos:
            raise ValueError(f"No position found for {sym}")
        contracts = float(pos.get("contracts") or 0)
        if contracts == 0:
            raise ValueError("No open position to close")
        side = str(pos.get("side", "")).lower()
        close_side = "sell" if side == "long" else "buy"
        amount_to_close = abs(contracts) * (percentage / 100.0)
        if amount_to_close <= 0:
            raise ValueError("Calculated close amount is zero")
        order = self.place_order(
            symbol=sym,
            side=close_side,
            order_type="market",
            amount=round(amount_to_close, 8),
            reduce_only=True,
        )
        return {
            "closed_percentage": percentage,
            "amount_closed": amount_to_close,
            "order": order,
        }

    def close_all(self) -> list[dict[str, Any]]:
        closed: list[dict[str, Any]] = []
        for p in self.fetch_active_positions():
            sym = p["symbol"]
            side = str(p.get("side", "")).lower()
            close_side = "sell" if side == "long" else "buy"
            try:
                order = self.place_order(
                    symbol=sym,
                    side=close_side,
                    order_type="market",
                    amount=abs(float(p["contracts"])),
                    reduce_only=True,
                )
                closed.append({"symbol": sym, "order_id": order.get("id"), "side": close_side})
            except Exception as exc:
                closed.append({"symbol": sym, "error": str(exc)})
        return closed

    def cancel_orders(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        all_open: bool = False,
    ) -> Any:
        if all_open:
            if symbol:
                return self.exchange.cancel_all_orders(normalize_symbol(symbol))
            return self.exchange.cancel_all_orders()
        if order_id and symbol:
            return self.exchange.cancel_order(order_id, normalize_symbol(symbol))
        raise ValueError("Provide all_open=true or both symbol and order_id")

    def fetch_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = binance_raw_symbol(symbol)
        raw = self.exchange.fapiPrivateGetOpenAlgoOrders(params)
        if isinstance(raw, list):
            return raw
        return raw.get("orders", []) if isinstance(raw, dict) else []

    def cancel_algo_order(self, algo_id: str | int) -> dict[str, Any]:
        return self.exchange.fapiPrivateDeleteAlgoOrder({"algoId": str(algo_id)})

    def cancel_exit_algos(
        self,
        symbol: str | None = None,
        *,
        sl: bool = True,
        tp: bool = True,
    ) -> list[str]:
        cancelled: list[str] = []
        sl_types = {"STOP", "STOP_MARKET"}
        tp_types = {"TAKE_PROFIT", "TAKE_PROFIT_MARKET"}
        for algo in self.fetch_algo_orders(symbol):
            otype = str(algo.get("orderType") or "")
            if sl and otype in sl_types:
                pass
            elif tp and otype in tp_types:
                pass
            else:
                continue
            aid = algo.get("algoId")
            if aid is not None:
                self.cancel_algo_order(aid)
                cancelled.append(str(aid))
        return cancelled

    def cancel_stop_algos(self, symbol: str | None = None) -> list[str]:
        return self.cancel_exit_algos(symbol, sl=True, tp=False)

    def list_symbols(self, q: str | None = None, limit: int = 50) -> list[str]:
        futures = [
            m
            for m in self.exchange.markets.values()
            if m.get("future") or m.get("linear")
        ]
        if q:
            qu = q.upper()
            futures = [m for m in futures if qu in m["symbol"].upper()]
        return [m["symbol"] for m in futures[:limit]]

    def execute_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute entry + optional SL + TP."""
        action = payload.get("action", "open")
        if action == "place_trade":
            return self._execute_place_trade(payload)
        if action == "open":
            return self._execute_open(payload)
        if action == "partial_close":
            return self._execute_partial_close(payload)
        if action == "close_all":
            return {"closed_positions": self.close_all()}
        if action == "set_sl":
            if payload.get("cancel_existing_stops"):
                self.cancel_stop_algos(payload["symbol"])
            return {
                "order": self.place_stop_loss(
                    symbol=payload["symbol"],
                    side=payload["side"],
                    trigger_price=float(payload["trigger_price"]),
                    amount=payload.get("amount"),
                    close_position=payload.get("close_position", True),
                )
            }
        if action == "set_tp":
            return {
                "order": self.place_take_profit(
                    symbol=payload["symbol"],
                    side=payload["side"],
                    trigger_price=float(payload["trigger_price"]),
                    amount=payload.get("amount"),
                    close_position=payload.get("close_position", True),
                )
            }
        if action == "set_tp_limit":
            return {
                "order": self.place_take_profit_limit(
                    symbol=payload["symbol"],
                    side=payload["side"],
                    trigger_price=float(payload["trigger_price"]),
                    limit_price=float(payload["limit_price"]),
                    amount=float(payload["amount"]),
                )
            }
        raise ValueError(f"Unknown action: {action}")

    def _execute_place_trade(self, payload: dict[str, Any]) -> dict[str, Any]:
        leverage = payload.get("leverage")
        if leverage:
            self.set_leverage(payload["symbol"], int(leverage))
        order = self.place_order(
            symbol=payload["symbol"],
            side=payload["side"],
            order_type=payload.get("type", "market"),
            amount=float(payload["amount"]),
            price=payload.get("price"),
            reduce_only=bool(payload.get("reduce_only", False)),
        )
        return {"order": order}

    def _execute_open(self, payload: dict[str, Any]) -> dict[str, Any]:
        leverage = payload.get("leverage")
        if leverage:
            self.set_leverage(payload["symbol"], int(leverage))
        entry = self.place_order(
            symbol=payload["symbol"],
            side=payload["side"],
            order_type=payload.get("type", "market"),
            amount=float(payload["amount"]),
            price=payload.get("price"),
            reduce_only=False,
        )
        result: dict[str, Any] = {"entry": entry}
        close_side = "sell" if payload["side"].lower() == "buy" else "buy"
        if payload.get("stop_loss"):
            result["stop_loss"] = self.place_stop_loss(
                symbol=payload["symbol"],
                side=close_side,
                trigger_price=float(payload["stop_loss"]),
            )
        tp = payload.get("take_profit")
        if tp is not None:
            tp_type = str(payload.get("take_profit_type") or "limit").lower()
            if tp_type == "limit":
                limit_px = payload.get("take_profit_limit_price") or tp
                tp_amount = payload.get("take_profit_amount") or float(payload["amount"])
                result["take_profit"] = self.place_take_profit_limit(
                    symbol=payload["symbol"],
                    side=close_side,
                    trigger_price=float(tp),
                    limit_price=float(limit_px),
                    amount=float(tp_amount),
                )
            else:
                result["take_profit"] = self.place_take_profit(
                    symbol=payload["symbol"],
                    side=close_side,
                    trigger_price=float(tp),
                    amount=payload.get("take_profit_amount"),
                    close_position=payload.get("take_profit_close_position", True),
                )
        return result

    def _execute_partial_close(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.partial_close(payload["symbol"], float(payload["percentage"]))
