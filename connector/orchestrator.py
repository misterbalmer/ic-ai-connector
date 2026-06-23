"""15m Konsole → LLM → feed + trade orchestrator (server-side, trading-dashboard pattern)."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from connector.ai_feed import append_feed
from connector.llm_client import LlmError, call_llm, default_model_for_provider, resolve_ai_model
from connector.position_manager import execute_position_action
from connector.orchestrator_state import load_state, record_run
from connector.prompt_compiler import compile_trader_prompt, user_message_for_cycle
from connector.trade_sizing import TradeSizingError, normalize_trade_size
from connector.ui_settings import load_ui_settings

logger = logging.getLogger(__name__)


def build_feed_brief(
    parsed: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> tuple[str, str | None, list[str]]:
    """Normalize LLM output into a multi-line desk brief."""
    summary = str(parsed.get("summary") or "").strip()
    raw_lines = parsed.get("coin_briefs")
    lines: list[str] = []
    if isinstance(raw_lines, list):
        lines = [str(x).strip() for x in raw_lines if str(x).strip()]

    universe = (snapshot or {}).get("universe") or []
    expected = len(universe) if isinstance(universe, list) else 0
    if lines and expected and len(lines) != expected:
        logger.warning(
            "coin_briefs count mismatch: got %s expected %s (universe[])",
            len(lines),
            expected,
        )

    if lines:
        return "\n".join(lines), None, lines

    # Legacy prose brief only when coin_briefs absent — strip leading preamble if model ignored rules.
    brief = str(parsed.get("brief") or parsed.get("summary") or "Analysis complete.").strip()
    if summary and brief.startswith(summary):
        brief = brief[len(summary) :].strip()
    return brief, None, []


def _price_for_symbol(symbol: str, trade: dict[str, Any], snapshot: dict[str, Any]) -> float | None:
    for row in snapshot.get("universe") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol", "")).upper() == str(symbol).upper():
            price = row.get("last_price")
            if price is not None:
                return float(price)
    entry = trade.get("entry_price") or trade.get("price")
    return float(entry) if entry is not None else None


def normalize_orchestrator_trade(
    trade: dict[str, Any],
    *,
    balance: dict[str, Any],
    konsole_snapshot: dict[str, Any],
    exchange_svc: Any,
    settings: Any,
) -> dict[str, Any]:
    """SL-based leverage, min notional, 25% margin cap."""
    symbol = str(trade.get("symbol") or "")
    price = _price_for_symbol(symbol, trade, konsole_snapshot)
    if price is None:
        try:
            price = float(exchange_svc.estimate_notional(symbol, 1.0))
        except Exception as exc:
            raise TradeSizingError(f"{symbol}: cannot resolve price ({exc})") from exc
    if not price or price <= 0:
        raise TradeSizingError(f"{symbol}: invalid price for sizing")

    return normalize_trade_size(
        trade,
        balance=balance,
        entry_price=price,
        exchange_svc=exchange_svc,
        max_leverage=int(settings.max_leverage),
        max_margin_loss_on_stop=float(settings.max_margin_loss_on_stop),
        min_notional_usdt=float(settings.min_notional_usdt),
    )


def dry_run_response(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Deterministic response for tests without LLM credits."""
    universe = snapshot.get("universe") or snapshot.get("coins") or []
    n = len(universe) if isinstance(universe, list) else 0
    return {
        "brief": f"Dry run: scanned {n} symbols. No live trade — orchestrator test only.",
        "action": "no_action",
        "shortlist": [],
        "detail": "Set dry_run=false and configure AI API key in Settings for live LLM.",
        "trades": [],
        "position_actions": [],
    }


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Any,
        exchange_svc: Any,
        risk: Any,
        maybe_queue_or_execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.exchange_svc = exchange_svc
        self.risk = risk
        self.maybe_queue_or_execute = maybe_queue_or_execute

    def status(self) -> dict[str, Any]:
        ui = load_ui_settings()
        state = load_state(self.settings.orchestrator_state_file)
        return {
            "ai_configured": bool(ui.get("ai_api_key")),
            "ai_provider": ui.get("ai_provider", "google"),
            "ai_model": ui.get("ai_model") or default_model_for_provider(
                ui.get("ai_provider", "google")
            ),
            "trade_mode": self.settings.trade_mode,
            "decision_interval_seconds": self.settings.decision_interval_seconds,
            "agent_prompt": "agents/trader_system.md",
            "last_run_at": state.get("last_run_at"),
            "last_status": state.get("last_status"),
            "last_action": state.get("last_action"),
            "last_error": state.get("last_error"),
            "runs_total": state.get("runs", 0),
        }

    async def run_cycle(
        self,
        *,
        konsole_snapshot: dict[str, Any],
        ic_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        snapshot_at = konsole_snapshot.get("snapshot_at")
        if not dry_run:
            snap_path = self.settings.root_dir / "last-konsole-snapshot.json"
            snap_path.write_text(
                json.dumps(konsole_snapshot, indent=2, default=str),
                encoding="utf-8",
            )
        ui = load_ui_settings()
        try:
            balance = self.exchange_svc.fetch_balance_summary()
        except Exception as exc:
            logger.warning("balance fetch failed: %s", exc)
            balance = {"total": 0, "free": 0, "used": 0}
        try:
            positions = self.exchange_svc.fetch_active_positions()
        except Exception as exc:
            logger.warning("positions fetch failed: %s", exc)
            positions = []
        risk_status = self.risk.status()
        position_state_path = self.settings.root_dir / "position-state.json"

        if not dry_run:
            try:
                self.exchange_svc.cleanup_orphan_exit_algos(positions)
            except Exception as exc:
                logger.warning("orphan exit cleanup failed: %s", exc)

        system = compile_trader_prompt(
            settings=self.settings,
            balance=balance,
            positions=positions,
            risk_status=risk_status,
            konsole_snapshot=konsole_snapshot,
            ic_context=ic_context,
        )
        user_msg = user_message_for_cycle(
            str(snapshot_at) if snapshot_at else None
        )

        scanned = konsole_snapshot.get("scanned_coins")
        if scanned is None:
            universe = konsole_snapshot.get("universe") or konsole_snapshot.get("coins") or []
            scanned = len(universe) if isinstance(universe, list) else None
        metrics_count = konsole_snapshot.get("metrics_count", 9)
        provider = ui.get("ai_provider", "google")
        model = resolve_ai_model(provider, ui.get("ai_model"))

        try:
            if dry_run or not ui.get("ai_api_key"):
                parsed = dry_run_response(konsole_snapshot)
                raw = str(parsed)
                if not dry_run and not ui.get("ai_api_key"):
                    parsed["brief"] = (
                        "No AI API key configured. Add key in Settings → Orchestrator."
                    )
                    parsed["action"] = "no_action"
            else:
                parsed, raw = await call_llm(
                    provider=provider,
                    api_key=ui["ai_api_key"],
                    model=model,
                    system=system,
                    user_message=user_msg,
                )

            action = str(parsed.get("action", "hold")).lower()
            trades = parsed.get("trades") or []
            if not isinstance(trades, list):
                trades = []

            desk_brief, summary, coin_briefs = build_feed_brief(
                parsed, konsole_snapshot
            )
            feed_record = append_feed(
                self.settings.ai_feed_file,
                {
                    "brief": desk_brief,
                    "summary": summary,
                    "coin_briefs": coin_briefs,
                    "action": action,
                    "shortlist": parsed.get("shortlist") or [],
                    "watchlist": parsed.get("watchlist") or [],
                    "detail": parsed.get("detail"),
                    "scanned_coins": scanned,
                    "metrics_count": metrics_count,
                    "model": model,
                },
            )

            trade_results: list[dict[str, Any]] = []
            proposal_ids: list[str] = []
            mgmt_results: list[dict[str, Any]] = []

            position_actions = parsed.get("position_actions") or []
            if isinstance(position_actions, list):
                for act in position_actions:
                    if not isinstance(act, dict):
                        continue
                    try:
                        mgmt_results.append(
                            execute_position_action(
                                act,
                                exchange_svc=self.exchange_svc,
                                maybe_execute=self.maybe_queue_or_execute,
                                state_path=position_state_path,
                            )
                        )
                    except Exception as exc:
                        logger.warning("position_action failed: %s", exc)
                        mgmt_results.append({"error": str(exc), "action": act})

            for t in trades:
                if not isinstance(t, dict):
                    continue
                try:
                    t = normalize_orchestrator_trade(
                        t,
                        balance=balance,
                        konsole_snapshot=konsole_snapshot,
                        exchange_svc=self.exchange_svc,
                        settings=self.settings,
                    )
                except TradeSizingError as exc:
                    logger.warning("Trade sizing rejected: %s", exc)
                    trade_results.append(
                        {
                            "status": "rejected",
                            "error": str(exc),
                            "symbol": t.get("symbol"),
                        }
                    )
                    continue

                payload = {
                    "symbol": t["symbol"],
                    "side": t["side"],
                    "amount": float(t["amount"]),
                    "stop_loss": t.get("stop_loss"),
                    "take_profit": t.get("take_profit"),
                    "take_profit_type": t.get("take_profit_type", "limit"),
                    "take_profit_limit_price": t.get("take_profit_limit_price"),
                    "take_profit_amount": t.get("take_profit_amount"),
                    "leverage": t.get("leverage"),
                    "notional_usdt": t.get("notional_usdt"),
                    "type": "market",
                }
                try:
                    result = self.maybe_queue_or_execute("open", payload)
                except Exception as exc:
                    logger.warning("Trade execution failed for %s: %s", t.get("symbol"), exc)
                    trade_results.append(
                        {
                            "status": "failed",
                            "error": str(exc),
                            "symbol": t.get("symbol"),
                        }
                    )
                    continue
                trade_results.append(result)
                prop = result.get("proposal") or {}
                if prop.get("proposal_id"):
                    proposal_ids.append(prop["proposal_id"])

            state = record_run(
                self.settings.orchestrator_state_file,
                status="ok",
                action=action,
                model=model,
            )

            return {
                "ok": True,
                "dry_run": dry_run or not ui.get("ai_api_key"),
                "analysis": parsed,
                "feed_message": feed_record,
                "trade_results": trade_results,
                "management_results": mgmt_results,
                "proposal_ids": proposal_ids,
                "orchestrator": state,
            }

        except (LlmError, Exception) as exc:
            logger.exception("Orchestrator cycle failed: %s", exc)
            err_text = str(exc)
            append_feed(
                self.settings.ai_feed_file,
                {
                    "brief": f"Analysis failed: {err_text[:500]}",
                    "action": "no_action",
                    "detail": err_text[:20000],
                    "scanned_coins": scanned,
                    "metrics_count": metrics_count,
                    "model": model,
                },
            )
            record_run(
                self.settings.orchestrator_state_file,
                status="error",
                error=err_text,
            )
            raise
