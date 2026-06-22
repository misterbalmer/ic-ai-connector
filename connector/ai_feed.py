"""One-way AI analysis feed for the dashboard (orchestrator posts each 15m cycle)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_decision_at(interval_seconds: int = 900) -> datetime:
    """Next wall-clock boundary aligned to interval (e.g. :00, :15, :30, :45)."""
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    next_epoch = ((epoch // interval_seconds) + 1) * interval_seconds
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def feed_head(path: Path) -> dict[str, Any]:
    """Lightweight check for new messages — no full feed payload."""
    items = _read_all(path)
    if not items:
        return {"latest_id": None, "count": 0}
    latest = items[-1]
    return {"latest_id": latest.get("id"), "count": len(items)}


def feed_meta(interval_seconds: int = 900, feed_path: Path | None = None) -> dict[str, Any]:
    last_at: str | None = None
    last_status: str | None = None
    if feed_path and feed_path.exists():
        messages = _read_all(feed_path)
        if messages:
            latest = messages[-1]
            last_at = latest.get("created_at")
            last_status = latest.get("action")
    nxt = next_decision_at(interval_seconds)
    now = datetime.now(timezone.utc)
    return {
        "interval_seconds": interval_seconds,
        "next_decision_at": nxt.isoformat(),
        "seconds_until_next": max(0, int((nxt - now).total_seconds())),
        "last_decision_at": last_at,
        "last_status": last_status,
    }


def _read_all(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def list_feed(path: Path, limit: int = 50) -> list[dict[str, Any]]:
    """Return messages oldest-first so the chat UI can append at the bottom."""
    items = _read_all(path)
    return items[-limit:]


def clear_feed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def append_feed(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    record = {
        "id": entry.get("id") or str(uuid.uuid4()),
        "created_at": entry.get("created_at") or _utc_now_iso(),
        "brief": entry["brief"],
        "summary": entry.get("summary"),
        "coin_briefs": entry.get("coin_briefs") or [],
        "action": entry.get("action", "hold"),
        "shortlist": entry.get("shortlist") or [],
        "watchlist": entry.get("watchlist") or [],
        "detail": entry.get("detail"),
        "proposal_id": entry.get("proposal_id"),
        "scanned_coins": entry.get("scanned_coins"),
        "metrics_count": entry.get("metrics_count"),
        "model": entry.get("model"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record
