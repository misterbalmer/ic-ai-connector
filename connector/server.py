"""IC AI Connector — FastAPI server."""

from __future__ import annotations

import logging
import webbrowser
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import ccxt
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from connector.audit import append_audit
from connector.config import Settings, load_settings
from connector.dashboard_api import init_dashboard_api, router as dashboard_router
from connector.exchange import ExchangeService, create_exchange
from connector.orchestrator import Orchestrator
from connector.network_check import validate_network_config
from connector.risk_guard import RiskGuard, RiskLimits
from connector.trade_queue import TradeQueue

logger = logging.getLogger(__name__)

settings: Settings
exchange_svc: ExchangeService
risk: RiskGuard
queue: TradeQueue


def setup_logging(log_file) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3),
            logging.StreamHandler(),
        ],
        force=True,
    )


# --- Pydantic models ---


class TradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., description="buy or sell")
    type: str = Field("market", description="market or limit")
    amount: float = Field(..., gt=0)
    price: Optional[float] = None
    leverage: Optional[int] = Field(None, ge=1, le=125)
    reduce_only: bool = False
    notional_usdt: Optional[float] = Field(
        None, description="Estimated notional for risk check; computed if omitted"
    )


class OpenTradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., description="buy for long, sell for short")
    amount: float = Field(..., gt=0)
    type: str = Field("market")
    price: Optional[float] = None
    leverage: Optional[int] = Field(None, ge=1, le=125)
    stop_loss: Optional[float] = Field(None, description="Stop loss trigger price")
    take_profit: Optional[float] = Field(None, description="Take profit trigger price")
    take_profit_type: Optional[str] = Field(
        "limit", description="limit (preferred) or market"
    )
    take_profit_limit_price: Optional[float] = Field(
        None, description="Limit price for TAKE_PROFIT reduce order"
    )
    take_profit_amount: Optional[float] = Field(
        None, description="Contracts to close at TP (default: full entry amount)"
    )
    notional_usdt: Optional[float] = None


class SLTPRequest(BaseModel):
    symbol: str
    trigger_price: float = Field(..., gt=0)
    side: str
    amount: Optional[float] = None
    close_position: bool = True
    order_type: str = Field("limit", description="limit or market (TP only)")
    limit_price: Optional[float] = None
    cancel_existing_stops: bool = False


class PartialCloseRequest(BaseModel):
    symbol: str
    percentage: float = Field(100.0, gt=0, le=100)


class CancelRequest(BaseModel):
    symbol: Optional[str] = None
    order_id: Optional[str] = None
    all_open: bool = False


class ProposeRequest(BaseModel):
    action: str = Field(
        ...,
        description=(
            "open | place_trade | partial_close | close_all | set_sl | set_tp | set_tp_limit"
        ),
    )
    payload: dict[str, Any]


class ConfirmRequest(BaseModel):
    proposal_id: str


class RejectRequest(BaseModel):
    proposal_id: str
    reason: Optional[str] = None


class ResetKillSwitchRequest(BaseModel):
    confirm: str


class CloseAllRequest(BaseModel):
    confirm: str = Field(..., description='Must be "CLOSE ALL POSITIONS"')


# --- Auth ---


async def verify_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Bearer YOUR_CONNECTOR_TOKEN",
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != settings.connector_token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


def _blocked(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def _validate_trade_risk(
    *,
    symbol: str,
    amount: float,
    price: float | None,
    leverage: int | None,
    reduce_only: bool,
    notional_usdt: float | None,
) -> float:
    if leverage:
        ok, reason = risk.check_leverage_allowed(leverage)
        if not ok:
            raise _blocked(reason or "Leverage not allowed")

    notional = notional_usdt
    if notional is None:
        notional = exchange_svc.estimate_notional(symbol, amount, price)

    ok, reason = risk.check_order_allowed(
        notional_usdt=notional,
        open_position_count=exchange_svc.count_open_positions(),
        reduce_only=reduce_only,
    )
    if not ok:
        raise _blocked(reason or "Order blocked by risk guard")
    return notional


def _summary_for_payload(action: str, payload: dict[str, Any]) -> str:
    if action == "open":
        lev = payload.get("leverage")
        lev_s = f" {lev}x" if lev else ""
        return (
            f"OPEN {payload.get('side','').upper()} {payload.get('amount')} "
            f"{payload.get('symbol')}{lev_s} | SL={payload.get('stop_loss')} TP={payload.get('take_profit')}"
        )
    if action == "place_trade":
        return (
            f"{payload.get('type','market').upper()} {payload.get('side','').upper()} "
            f"{payload.get('amount')} {payload.get('symbol')}"
        )
    if action == "partial_close":
        return f"PARTIAL CLOSE {payload.get('percentage')}% {payload.get('symbol')}"
    if action == "close_all":
        return "CLOSE ALL POSITIONS"
    if action in ("set_sl", "set_tp"):
        extra = " (replaces existing stops)" if payload.get("cancel_existing_stops") else ""
        return f"{action.upper()} {payload.get('symbol')} @ {payload.get('trigger_price')}{extra}"
    if action == "set_tp_limit":
        return (
            f"SET TP LIMIT {payload.get('symbol')} trigger={payload.get('trigger_price')} "
            f"limit={payload.get('limit_price')} qty={payload.get('amount')}"
        )
    return f"{action}: {payload}"


def _maybe_queue_or_execute(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = _summary_for_payload(action, payload)

    if settings.trade_mode == "confirm":
        proposal = queue.add(action, payload, summary)
        append_audit(
            settings.audit_file,
            "proposal_created",
            {"proposal_id": proposal["proposal_id"], "action": action, "summary": summary},
        )
        return {
            "mode": "confirm",
            "status": "pending",
            "proposal": proposal,
            "message": "Trade queued. POST /trade/confirm with proposal_id to execute.",
        }

    result = exchange_svc.execute_bundle({"action": action, **payload})
    append_audit(
        settings.audit_file,
        "trade_executed",
        {"action": action, "summary": summary, "result": result},
    )
    return {"mode": "auto", "status": "executed", "result": result}


def create_app() -> FastAPI:
    global settings, exchange_svc, risk, queue

    settings = load_settings()
    setup_logging(settings.log_file)
    validate_network_config(
        settings.use_testnet,
        settings.binance_api_key,
        settings.binance_api_secret,
    )

    exchange = create_exchange(settings)
    exchange_svc = ExchangeService(exchange)
    risk = RiskGuard(
        settings.risk_state_file,
        RiskLimits(
            max_notional_per_order=settings.max_notional_per_order,
            max_open_positions=settings.max_open_positions,
            max_daily_loss=settings.max_daily_loss,
            max_leverage=settings.max_leverage,
            min_notional_usdt=settings.min_notional_usdt,
        ),
    )
    queue = TradeQueue(settings.pending_file, settings.proposal_ttl_seconds)

    app = FastAPI(
        title="IC AI Connector",
        description=(
            "Local-only Binance USDT-M Futures connector for AI-assisted trading. "
            "Works with any AI that can call HTTP. Institutional Charts."
        ),
        version="1.0.0",
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = datetime.now()
        response = await call_next(request)
        duration = (datetime.now() - start).total_seconds()
        logger.info("%s %s | %s | %.2fs", request.method, request.url.path, response.status_code, duration)
        return response

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "product": "IC AI Connector",
            "account": "live" if not settings.use_testnet else "testnet",
            "trade_mode": settings.trade_mode,
            "exchange": "binance",
            "market_type": "usdt-m futures",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/status")
    async def status(_: str = Depends(verify_token)):
        return {
            "health": "ok",
            "account": "live" if not settings.use_testnet else "testnet",
            "trade_mode": settings.trade_mode,
            "risk": risk.status(),
            "pending_proposals": len(queue.list_pending()),
        }

    @app.post("/test_connection")
    async def test_connection(_: str = Depends(verify_token)):
        try:
            info = exchange_svc.test_connection()
            return {"success": True, **info}
        except Exception as exc:
            logger.error("test_connection failed: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/risk/status")
    async def risk_status(_: str = Depends(verify_token)):
        return risk.status()

    @app.post("/risk/reset_kill_switch")
    async def reset_kill_switch(req: ResetKillSwitchRequest, _: str = Depends(verify_token)):
        if req.confirm != "I confirm reset":
            raise HTTPException(status_code=400, detail="Confirmation must be exactly: I confirm reset")
        state = risk.set_kill_switch(False)
        append_audit(settings.audit_file, "kill_switch_reset", {"state": state})
        return {"success": True, "state": state}

    @app.post("/balance")
    async def get_balance(_: str = Depends(verify_token)):
        try:
            usdt = exchange_svc.fetch_balance_summary()
            return {"USDT": usdt}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/positions")
    async def get_positions(_: str = Depends(verify_token)):
        try:
            active = exchange_svc.fetch_active_positions()
            return {"active_positions": active, "count": len(active)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/open_orders")
    async def get_open_orders(symbol: Optional[str] = None, _: str = Depends(verify_token)):
        try:
            orders = exchange_svc.fetch_open_orders(symbol)
            return {"open_orders": orders, "count": len(orders)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/trade/pending")
    async def list_pending(_: str = Depends(verify_token)):
        return {"pending": queue.list_pending(), "count": len(queue.list_pending())}

    @app.post("/trade/propose")
    async def propose_trade(req: ProposeRequest, _: str = Depends(verify_token)):
        action = req.action
        payload = dict(req.payload)

        if action in ("open", "place_trade"):
            _validate_trade_risk(
                symbol=payload["symbol"],
                amount=float(payload["amount"]),
                price=payload.get("price"),
                leverage=payload.get("leverage"),
                reduce_only=bool(payload.get("reduce_only", False)),
                notional_usdt=payload.get("notional_usdt"),
            )
        elif action == "close_all" and risk.is_kill_switch_active():
            raise _blocked("Kill switch active.")

        return _maybe_queue_or_execute(action, payload)

    async def _confirm_trade(proposal_id: str) -> dict[str, Any]:
        proposal = queue.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found or expired")
        action = proposal["action"]
        payload = proposal["payload"]
        try:
            result = exchange_svc.execute_bundle({"action": action, **payload})
        except ccxt.ExchangeError as exc:
            queue.mark(proposal_id, "failed", {"error": str(exc)})
            append_audit(
                settings.audit_file,
                "proposal_failed",
                {"proposal_id": proposal_id, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            queue.mark(proposal_id, "failed", {"error": str(exc)})
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        queue.mark(proposal_id, "confirmed", {"result": result})
        append_audit(
            settings.audit_file,
            "proposal_confirmed",
            {"proposal_id": proposal_id, "action": action, "result": result},
        )
        return {"success": True, "proposal_id": proposal_id, "result": result}

    async def _reject_trade(proposal_id: str, reason: str | None = None) -> dict[str, Any]:
        proposal = queue.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found or expired")
        queue.mark(proposal_id, "rejected", {"reason": reason})
        append_audit(
            settings.audit_file,
            "proposal_rejected",
            {"proposal_id": proposal_id, "reason": reason},
        )
        return {"success": True, "proposal_id": proposal_id, "status": "rejected"}

    @app.post("/trade/confirm")
    async def confirm_trade(req: ConfirmRequest, _: str = Depends(verify_token)):
        return await _confirm_trade(req.proposal_id)

    @app.post("/trade/reject")
    async def reject_trade(req: RejectRequest, _: str = Depends(verify_token)):
        return await _reject_trade(req.proposal_id, req.reason)

    @app.post("/trade/open")
    async def trade_open(req: OpenTradeRequest, _: str = Depends(verify_token)):
        notional = _validate_trade_risk(
            symbol=req.symbol,
            amount=req.amount,
            price=req.price,
            leverage=req.leverage,
            reduce_only=False,
            notional_usdt=req.notional_usdt,
        )
        payload = req.model_dump()
        payload["notional_usdt"] = notional
        return _maybe_queue_or_execute("open", payload)

    @app.post("/place_trade")
    async def place_trade(req: TradeRequest, _: str = Depends(verify_token)):
        notional = _validate_trade_risk(
            symbol=req.symbol,
            amount=req.amount,
            price=req.price,
            leverage=req.leverage,
            reduce_only=req.reduce_only,
            notional_usdt=req.notional_usdt,
        )
        payload = req.model_dump()
        payload["notional_usdt"] = notional
        return _maybe_queue_or_execute("place_trade", payload)

    @app.post("/set_sl")
    async def set_stop_loss(req: SLTPRequest, _: str = Depends(verify_token)):
        if risk.is_kill_switch_active():
            raise _blocked("Kill switch active.")
        payload = {
            "symbol": req.symbol,
            "side": req.side,
            "trigger_price": req.trigger_price,
            "amount": req.amount,
            "close_position": req.close_position,
            "cancel_existing_stops": req.cancel_existing_stops,
        }
        return _maybe_queue_or_execute("set_sl", payload)

    @app.post("/set_tp")
    async def set_take_profit(req: SLTPRequest, _: str = Depends(verify_token)):
        if risk.is_kill_switch_active():
            raise _blocked("Kill switch active.")
        if req.order_type.lower() == "limit":
            if not req.amount or req.amount <= 0:
                raise HTTPException(status_code=400, detail="limit TP requires amount > 0")
            payload = {
                "symbol": req.symbol,
                "side": req.side,
                "trigger_price": req.trigger_price,
                "limit_price": req.limit_price or req.trigger_price,
                "amount": req.amount,
            }
            return _maybe_queue_or_execute("set_tp_limit", payload)
        payload = {
            "symbol": req.symbol,
            "side": req.side,
            "trigger_price": req.trigger_price,
            "amount": req.amount,
            "close_position": req.close_position,
        }
        return _maybe_queue_or_execute("set_tp", payload)

    @app.post("/partial_close")
    async def partial_close(req: PartialCloseRequest, _: str = Depends(verify_token)):
        payload = req.model_dump()
        return _maybe_queue_or_execute("partial_close", payload)

    @app.post("/close_all")
    async def close_all_positions(req: CloseAllRequest, _: str = Depends(verify_token)):
        if req.confirm != "CLOSE ALL POSITIONS":
            raise HTTPException(
                status_code=400,
                detail='Confirmation must be exactly: "CLOSE ALL POSITIONS"',
            )
        return _maybe_queue_or_execute("close_all", {})

    @app.post("/cancel_orders")
    async def cancel_orders(req: CancelRequest, _: str = Depends(verify_token)):
        try:
            result = exchange_svc.cancel_orders(
                symbol=req.symbol,
                order_id=req.order_id,
                all_open=req.all_open,
            )
            append_audit(settings.audit_file, "orders_cancelled", {"request": req.model_dump()})
            return {"success": True, "result": result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/symbols")
    async def list_symbols(q: Optional[str] = None):
        try:
            return {"symbols": exchange_svc.list_symbols(q)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    orchestrator = Orchestrator(
        settings=settings,
        exchange_svc=exchange_svc,
        risk=risk,
        maybe_queue_or_execute=_maybe_queue_or_execute,
    )

    init_dashboard_api(
        settings=settings,
        exchange_svc=exchange_svc,
        risk=risk,
        queue=queue,
        orchestrator=orchestrator,
        verify_token=verify_token,
        maybe_queue_or_execute=_maybe_queue_or_execute,
        confirm_trade_handler=_confirm_trade,
        reject_trade_handler=_reject_trade,
    )
    app.include_router(dashboard_router)

    @app.middleware("http")
    async def disable_static_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def dashboard():
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    return app


app = create_app()


def main() -> None:
    s = load_settings()
    url = f"http://{s.host}:{s.port}"
    print(f"IC AI Connector at {url}")
    acct = "live" if not s.use_testnet else "testnet"
    print(f"  account={acct}  trade_mode={s.trade_mode}")
    print(f"  Dashboard: {url}/")
    webbrowser.open(url)
    uvicorn.run(
        "connector.server:app",
        host=s.host,
        port=s.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
