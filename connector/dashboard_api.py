"""Dashboard API routes for the Phase 1 web UI."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from connector.orchestrator import Orchestrator
from connector.ai_feed import append_feed, clear_feed, feed_head, feed_meta, list_feed
from connector.llm_client import resolve_ai_model
from connector.ui_settings import load_ui_settings, mask_secret, save_ui_settings

router = APIRouter(prefix="/api/ui", tags=["dashboard"])
logger = logging.getLogger(__name__)


class UnlockRequest(BaseModel):
    token: str


class UiSettingsUpdate(BaseModel):
    ai_provider: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None


class MoveSlRequest(BaseModel):
    symbol: str
    trigger_price: float = Field(..., gt=0)


class PartialCloseUiRequest(BaseModel):
    symbol: str
    percentage: float = Field(..., gt=0, le=100)


class ConfirmUiRequest(BaseModel):
    proposal_id: str


class RejectUiRequest(BaseModel):
    proposal_id: str
    reason: Optional[str] = None


class AiFeedPost(BaseModel):
    brief: str = Field(..., min_length=1, max_length=4000)
    action: str = Field("hold", description="hold | trade | watch | adjust | no_action")
    shortlist: Optional[list[str]] = None
    detail: Optional[str] = Field(None, max_length=20000)
    proposal_id: Optional[str] = None
    scanned_coins: Optional[int] = None
    metrics_count: Optional[int] = None
    model: Optional[str] = None


class KonsoleAnalyzeRequest(BaseModel):
    """Konsole 15m snapshot — triggers one LLM decision cycle."""
    snapshot_at: Optional[str] = None
    universe: Optional[list[dict[str, Any]]] = None
    coins: Optional[list[dict[str, Any]]] = None
    scanned_coins: Optional[int] = None
    metrics_count: int = 9
    grid_seq: Optional[int] = None
    ts_ms: Optional[int] = None
    macro_btc: Optional[dict[str, Any]] = None
    macro_eth: Optional[dict[str, Any]] = None
    ic_context: Optional[dict[str, Any]] = None
    dry_run: bool = False


_deps: dict[str, Any] = {}


def init_dashboard_api(**kwargs) -> None:
    _deps.clear()
    _deps.update(kwargs)


async def require_ui_auth(authorization: Optional[str] = Header(None)) -> str:
    return await _deps["verify_token"](authorization)


@router.get("/meta")
async def ui_meta():
    settings = _deps["settings"]
    return {
        "product": "IC AI Connector",
        "account": "live" if not settings.use_testnet else "testnet",
        "trade_mode": settings.trade_mode,
        "version": "1.0.0",
    }


@router.post("/unlock")
async def ui_unlock(req: UnlockRequest):
    settings = _deps["settings"]
    if req.token != settings.connector_token:
        raise HTTPException(status_code=401, detail="Invalid access code")
    return {"ok": True, "message": "Unlocked — use this token in Authorization header"}


@router.get("/dashboard")
async def ui_dashboard(_: str = Depends(require_ui_auth)):
    exchange_svc = _deps["exchange_svc"]
    risk = _deps["risk"]
    queue = _deps["queue"]
    settings = _deps["settings"]
    interval = settings.decision_interval_seconds
    feed_path = settings.ai_feed_file

    try:
        balance = exchange_svc.fetch_balance_summary()
        positions = exchange_svc.fetch_active_positions()
        algos = exchange_svc.fetch_algo_orders()
    except Exception as exc:
        logger.error("dashboard exchange sync failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Exchange sync failed: {exc}") from exc

    pending = queue.list_pending()
    total_upnl = sum(float(p.get("unrealizedPnl") or 0) for p in positions)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account": "live" if not settings.use_testnet else "testnet",
        "trade_mode": settings.trade_mode,
        "balance": balance,
        "total_unrealized_pnl": round(total_upnl, 4),
        "positions": positions,
        "algo_orders": [
            {
                "algoId": a.get("algoId"),
                "symbol": a.get("symbol"),
                "orderType": a.get("orderType"),
                "side": a.get("side"),
                "triggerPrice": a.get("triggerPrice"),
                "algoStatus": a.get("algoStatus"),
            }
            for a in algos
        ],
        "pending": pending,
        "risk": risk.status(),
        "feed_head": feed_head(feed_path),
        "feed_meta": feed_meta(interval, feed_path),
    }


@router.get("/settings")
async def ui_get_settings(_: str = Depends(require_ui_auth)):
    settings = _deps["settings"]
    ui = load_ui_settings()
    return {
        "binance_configured": bool(settings.binance_api_key),
        "binance_key_mask": mask_secret(settings.binance_api_key),
        "trade_mode": settings.trade_mode,
        "limits": {
            "max_notional_per_order": settings.max_notional_per_order,
            "max_open_positions": settings.max_open_positions,
            "max_daily_loss": settings.max_daily_loss,
            "max_leverage": settings.max_leverage,
        },
        "ai_provider": ui.get("ai_provider", "google"),
        "ai_model": resolve_ai_model(ui.get("ai_provider", "google"), ui.get("ai_model")),
        "ai_api_key_mask": mask_secret(ui.get("ai_api_key", "")),
        "ai_configured": bool(ui.get("ai_api_key")),
        "orchestrator": _deps["orchestrator"].status(),
    }


@router.post("/settings")
async def ui_save_settings(req: UiSettingsUpdate, _: str = Depends(require_ui_auth)):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if "ai_api_key" in patch and patch["ai_api_key"].strip() == "":
        patch.pop("ai_api_key")
    saved = save_ui_settings(patch)
    return {"ok": True, "ai_configured": bool(saved.get("ai_api_key"))}


@router.post("/confirm")
async def ui_confirm(req: ConfirmUiRequest, _: str = Depends(require_ui_auth)):
    return await _deps["confirm_trade_handler"](req.proposal_id)


@router.post("/reject")
async def ui_reject(req: RejectUiRequest, _: str = Depends(require_ui_auth)):
    return await _deps["reject_trade_handler"](req.proposal_id, req.reason)


@router.post("/partial-close")
async def ui_partial_close(req: PartialCloseUiRequest, _: str = Depends(require_ui_auth)):
    maybe_queue = _deps["maybe_queue_or_execute"]
    return maybe_queue(
        "partial_close",
        {"symbol": req.symbol, "percentage": req.percentage},
    )


@router.post("/move-sl")
async def ui_move_sl(req: MoveSlRequest, _: str = Depends(require_ui_auth)):
    exchange_svc = _deps["exchange_svc"]
    maybe_queue = _deps["maybe_queue_or_execute"]

    pos = exchange_svc.fetch_position_for_symbol(req.symbol)
    if not pos:
        raise HTTPException(status_code=404, detail="No open position for symbol")
    side = str(pos.get("side", "")).lower()
    close_side = "sell" if side == "long" else "buy"

    return maybe_queue(
        "set_sl",
        {
            "symbol": req.symbol,
            "side": close_side,
            "trigger_price": req.trigger_price,
            "close_position": True,
            "cancel_existing_stops": True,
        },
    )


@router.get("/ai-feed")
async def ui_ai_feed(_: str = Depends(require_ui_auth)):
    settings = _deps["settings"]
    interval = settings.decision_interval_seconds
    path = settings.ai_feed_file
    return {
        "messages": list_feed(path),
        "meta": feed_meta(interval, path),
    }


@router.post("/ai-feed")
async def ui_ai_feed_post(req: AiFeedPost, _: str = Depends(require_ui_auth)):
    settings = _deps["settings"]
    record = append_feed(settings.ai_feed_file, req.model_dump())
    return {"ok": True, "message": record}


@router.delete("/ai-feed")
async def ui_ai_feed_clear(_: str = Depends(require_ui_auth)):
    settings = _deps["settings"]
    clear_feed(settings.ai_feed_file)
    return {"ok": True, "messages": []}


@router.get("/orchestrator/status")
async def ui_orchestrator_status(_: str = Depends(require_ui_auth)):
    return _deps["orchestrator"].status()


@router.post("/konsole/analyze")
async def ui_konsole_analyze(req: KonsoleAnalyzeRequest, _: str = Depends(require_ui_auth)):
    """Run one decision cycle: compile prompt + LLM + feed (+ trades if auto)."""
    snapshot = req.model_dump(exclude={"dry_run", "ic_context"})
    snapshot = {k: v for k, v in snapshot.items() if v is not None}
    try:
        return await _deps["orchestrator"].run_cycle(
            konsole_snapshot=snapshot,
            ic_context=req.ic_context,
            dry_run=req.dry_run,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
