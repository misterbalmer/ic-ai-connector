"""UI-only settings (AI keys) — separate from .env secrets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from connector.llm_client import resolve_ai_model

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "ui-settings.json"

_DEFAULTS = {
    "ai_provider": "google",
    "ai_api_key": "",
    "ai_model": "gemini-2.5-flash",
}


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    out = {**_DEFAULTS, **data}
    provider = str(out.get("ai_provider") or "google")
    out["ai_provider"] = provider
    out["ai_model"] = resolve_ai_model(provider, out.get("ai_model"))
    return out


def load_ui_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return _normalize({})
    return _normalize(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))


def save_ui_settings(data: dict[str, Any]) -> dict[str, Any]:
    current = load_ui_settings()
    current.update(data)
    normalized = _normalize(current)
    SETTINGS_FILE.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def mask_secret(value: str, show: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= show * 2:
        return "••••••••"
    return value[:show] + "••••" + value[-show:]
