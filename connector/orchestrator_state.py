"""Orchestrator state (last run metadata)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_run_at": None, "last_status": None, "last_error": None, "runs": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_run(
    path: Path,
    *,
    status: str,
    error: str | None = None,
    action: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    state = load_state(path)
    state["last_run_at"] = _utc_now()
    state["last_status"] = status
    state["last_action"] = action
    state["last_error"] = error
    state["last_model"] = model
    state["runs"] = int(state.get("runs") or 0) + 1
    save_state(path, state)
    return state
