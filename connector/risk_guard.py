"""Server-side risk limits — enforced in code, not by the AI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RiskLimits:
    max_notional_per_order: float
    max_open_positions: int
    max_daily_loss: float
    max_leverage: int
    min_notional_usdt: float = 5.0


class RiskGuard:
    def __init__(self, state_file: Path, limits: RiskLimits) -> None:
        self.state_file = state_file
        self.limits = limits

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"date": self._today(), "realized_pnl_today": 0.0, "kill_switch": False}
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        if state.get("date") != self._today():
            return {"date": self._today(), "realized_pnl_today": 0.0, "kill_switch": False}
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def is_kill_switch_active(self) -> bool:
        return bool(self.load_state().get("kill_switch"))

    def set_kill_switch(self, active: bool) -> dict[str, Any]:
        state = self.load_state()
        state["kill_switch"] = active
        self.save_state(state)
        return state

    def record_realized_pnl(self, delta_usdt: float) -> dict[str, Any]:
        state = self.load_state()
        state["realized_pnl_today"] = float(state.get("realized_pnl_today", 0)) + delta_usdt
        if state["realized_pnl_today"] <= -self.limits.max_daily_loss:
            state["kill_switch"] = True
        self.save_state(state)
        return state

    def check_order_allowed(
        self,
        *,
        notional_usdt: float,
        open_position_count: int,
        reduce_only: bool = False,
    ) -> tuple[bool, str | None]:
        if reduce_only:
            return True, None

        state = self.load_state()
        if state.get("kill_switch"):
            return False, (
                f"Kill switch active (daily loss limit {self.limits.max_daily_loss} USDT). "
                "Use POST /risk/reset_kill_switch with confirm phrase to override."
            )
        if notional_usdt > self.limits.max_notional_per_order:
            return False, (
                f"Order notional {notional_usdt:.2f} USDT exceeds max "
                f"{self.limits.max_notional_per_order} USDT per order."
            )
        if open_position_count >= self.limits.max_open_positions:
            return False, (
                f"Already at max open positions ({self.limits.max_open_positions})."
            )
        if notional_usdt < self.limits.min_notional_usdt:
            return False, (
                f"Order notional {notional_usdt:.2f} USDT below exchange minimum "
                f"{self.limits.min_notional_usdt:.2f} USDT."
            )
        return True, None

    def check_leverage_allowed(self, leverage: int) -> tuple[bool, str | None]:
        if leverage > self.limits.max_leverage:
            return False, (
                f"Leverage {leverage}x exceeds max allowed {self.limits.max_leverage}x."
            )
        return True, None

    def status(self) -> dict[str, Any]:
        state = self.load_state()
        return {
            "limits": {
                "max_notional_per_order": self.limits.max_notional_per_order,
                "max_open_positions": self.limits.max_open_positions,
                "max_daily_loss": self.limits.max_daily_loss,
                "max_leverage": self.limits.max_leverage,
                "min_notional_usdt": self.limits.min_notional_usdt,
            },
            "state": state,
        }
