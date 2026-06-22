#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from connector.llm_client import call_google_gemini, LlmError
from connector.ui_settings import load_ui_settings

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash-8b",
]


async def main() -> None:
    key = load_ui_settings()["ai_api_key"]
    for m in MODELS:
        try:
            p, _ = await call_google_gemini(
                api_key=key,
                model=m,
                system='Reply JSON: {"brief":"...","action":"no_action"}',
                user_message="brief must be exactly: Pipeline test OK",
                max_tokens=200,
                temperature=0,
            )
            print(f"{m}: OK — {p.get('brief')}")
        except LlmError as e:
            print(f"{m}: FAIL — {str(e)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())