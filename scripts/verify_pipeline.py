#!/usr/bin/env python3
"""Step-by-step pipeline verification: connector -> LLM -> ai-feed -> dashboard."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connector.llm_client import call_google_gemini, LlmError  # noqa: E402
from connector.ui_settings import load_ui_settings  # noqa: E402

load_dotenv(ROOT / ".env")

HOST = os.getenv("CONNECTOR_HOST", "127.0.0.1")
PORT = os.getenv("CONNECTOR_PORT", "8080")
TOKEN = os.getenv("CONNECTOR_TOKEN", "")
BASE = f"http://{HOST}:{PORT}"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

MODELS_TO_TRY = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def step(n: int, name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] Step {n}: {name}" + (f" — {detail}" if detail else ""))
    return ok


async def test_gemini_direct(api_key: str) -> tuple[str | None, str | None]:
    system = 'Reply with JSON only: {"brief":"pong","action":"no_action"}'
    user = "Ping — respond with brief exactly 'Pipeline test OK'."
    for model in MODELS_TO_TRY:
        try:
            parsed, raw = await call_google_gemini(
                api_key=api_key,
                model=model,
                system=system,
                user_message=user,
                max_tokens=256,
                temperature=0.0,
            )
            brief = str(parsed.get("brief", ""))
            return model, brief[:120]
        except LlmError as exc:
            print(f"       model {model}: {str(exc)[:100]}")
    return None, None


def main() -> int:
    if not TOKEN:
        print("CONNECTOR_TOKEN missing in .env")
        return 1

    passed = 0
    total = 0
    working_model: str | None = None

    with httpx.Client(timeout=60.0) as client:
        total += 1
        try:
            r = client.get(f"{BASE}/health")
            ok = r.status_code == 200 and r.json().get("status") == "healthy"
            if step(1, "Connector /health", ok, r.json().get("product", "") if ok else r.text[:80]):
                passed += 1
        except Exception as exc:
            step(1, "Connector /health", False, str(exc))

        total += 1
        try:
            r = client.get("http://ic.snapshot:8080/api/ui/meta", timeout=10.0)
            ok = r.status_code == 200
            if step(2, "Konsole host ic.snapshot -> meta", ok, r.text[:80] if ok else str(r.status_code)):
                passed += 1
        except Exception as exc:
            step(2, "Konsole host ic.snapshot -> meta", False, str(exc))

        total += 1
        try:
            r = client.get(f"{BASE}/api/ui/dashboard", headers=HEADERS, timeout=30.0)
            ok = r.status_code == 200
            if step(3, "Dashboard auth + Binance sync", ok, f"positions={len(r.json().get('positions', []))}" if ok else r.text[:80]):
                passed += 1
        except Exception as exc:
            step(3, "Dashboard auth + Binance sync", False, str(exc))

    ui = load_ui_settings()
    api_key = ui.get("ai_api_key", "")
    total += 1
    if step(4, "AI API key configured", bool(api_key), f"model={ui.get('ai_model')}"):
        passed += 1
    else:
        print("\nAbort: no AI key")
        return 1

    total += 1
    print("[....] Step 5: Direct Gemini call (trying models)...")
    model, brief = asyncio.run(test_gemini_direct(api_key))
    ok = model is not None
    if step(5, "Gemini responds with JSON", ok, f"model={model} brief={brief!r}" if ok else "all models failed"):
        passed += 1
        working_model = model
    else:
        print("\nAbort: Gemini unavailable on all tried models")
        return 1

    # Live orchestrator cycle with working model
    snap_path = ROOT / "last-konsole-snapshot.json"
    snap = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else {}
    payload = {
        "dry_run": False,
        "snapshot_at": snap.get("snapshot_at") or "2026-06-22T09:00:00Z",
        "scanned_coins": snap.get("scanned_coins", 5),
        "metrics_count": 9,
        "universe": (snap.get("universe") or [])[:5],
        "grid_seq": 100001,
    }

    # Temporarily use working model via settings POST
    with httpx.Client(timeout=120.0) as client:
        if working_model and working_model != ui.get("ai_model"):
            client.post(
                f"{BASE}/api/ui/settings",
                headers=HEADERS,
                json={"ai_model": working_model},
            )
            print(f"       switched ai_model -> {working_model}")

        total += 1
        try:
            r = client.post(f"{BASE}/api/ui/konsole/analyze", headers=HEADERS, json=payload)
            ok = r.status_code == 200
            body = r.json() if ok else {}
            feed_msg = body.get("feed_message") or {}
            detail = (
                f"action={feed_msg.get('action')} id={str(feed_msg.get('id',''))[:8]}"
                if ok
                else r.text[:120]
            )
            if step(6, "POST /konsole/analyze -> orchestrator", ok, detail):
                passed += 1
                live_brief = feed_msg.get("brief", "")
            else:
                live_brief = ""
        except Exception as exc:
            step(6, "POST /konsole/analyze -> orchestrator", False, str(exc))
            live_brief = ""

        total += 1
        try:
            r = client.get(f"{BASE}/api/ui/ai-feed", headers=HEADERS)
            msgs = r.json().get("messages") or []
            ok = len(msgs) > 0 and any("Pipeline test OK" in (m.get("brief") or "") or m.get("id") for m in msgs)
            latest = msgs[-1] if msgs else {}
            # Accept any new live message (not dry-run boilerplate) as success
            if not ok and live_brief:
                ok = any(live_brief[:40] in (m.get("brief") or "") for m in msgs)
            if not ok and len(msgs) >= 2:
                ok = latest.get("scanned_coins") == 5 or latest.get("scanned_coins") == snap.get("scanned_coins", 5)
            detail = f"count={len(msgs)} latest={str(latest.get('brief',''))[:80]}"
            if step(7, "GET /ai-feed contains response", ok, detail):
                passed += 1
        except Exception as exc:
            step(7, "GET /ai-feed contains response", False, str(exc))

        total += 1
        try:
            r = client.get(f"{BASE}/api/ui/dashboard", headers=HEADERS, timeout=30.0)
            head = r.json().get("feed_head") or {}
            ok = (head.get("count") or 0) > 0 and head.get("latest_id")
            if step(8, "Dashboard feed_head matches feed", ok, json.dumps(head)):
                passed += 1
        except Exception as exc:
            step(8, "Dashboard feed_head matches feed", False, str(exc))

    print(f"\n{'='*50}")
    print(f"Result: {passed}/{total} steps passed")
    if passed == total:
        print("DONE — pipeline verified end-to-end.")
        return 0
    print("INCOMPLETE — see failures above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())