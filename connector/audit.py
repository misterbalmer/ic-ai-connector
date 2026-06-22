"""Append-only audit log for trades and proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_audit(path: Path, event: str, payload: dict[str, Any]) -> None:
    record = {"ts": _utc_now(), "event": event, **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
