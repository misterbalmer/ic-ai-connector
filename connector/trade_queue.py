"""Pending trade proposals for confirm-before-execute mode."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class TradeQueue:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def _purge_expired(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        kept: list[dict[str, Any]] = []
        for item in items:
            if item.get("status") != "pending":
                kept.append(item)
                continue
            created = _parse_ts(item["created_at"])
            age = (now - created).total_seconds()
            if age <= self.ttl_seconds:
                kept.append(item)
            else:
                expired = dict(item)
                expired["status"] = "expired"
                expired["expired_at"] = _utc_now_iso()
                kept.append(expired)
        return kept

    def list_pending(self) -> list[dict[str, Any]]:
        items = self._purge_expired(self._load())
        self._save(items)
        return [i for i in items if i.get("status") == "pending"]

    def add(self, action: str, payload: dict[str, Any], summary: str) -> dict[str, Any]:
        items = self._purge_expired(self._load())
        proposal_id = str(uuid.uuid4())
        proposal = {
            "proposal_id": proposal_id,
            "action": action,
            "payload": payload,
            "summary": summary,
            "status": "pending",
            "created_at": _utc_now_iso(),
            "expires_in_seconds": self.ttl_seconds,
        }
        items.append(proposal)
        self._save(items)
        return proposal

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        items = self._purge_expired(self._load())
        self._save(items)
        for item in items:
            if item.get("proposal_id") == proposal_id and item.get("status") == "pending":
                return item
        return None

    def mark(self, proposal_id: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        items = self._purge_expired(self._load())
        for item in items:
            if item.get("proposal_id") == proposal_id:
                item["status"] = status
                item[f"{status}_at"] = _utc_now_iso()
                if extra:
                    item.update(extra)
                self._save(items)
                return item
        return None
