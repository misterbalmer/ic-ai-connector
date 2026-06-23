"""LLM client for orchestrator (Google Gemini default; Anthropic/OpenAI optional)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "google": "gemini-2.5-flash",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}


def default_model_for_provider(provider: str) -> str:
    key = (provider or "google").lower()
    return DEFAULT_MODEL_BY_PROVIDER.get(key, "gemini-2.5-flash")


def model_matches_provider(provider: str, model: str) -> bool:
    m = (model or "").strip().lower()
    if not m:
        return False
    p = (provider or "google").lower()
    if p in ("google", "gemini"):
        return m.startswith("gemini")
    if p == "anthropic":
        return m.startswith("claude")
    if p == "openai":
        return m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")
    return True


def resolve_ai_model(provider: str, model: str | None) -> str:
    if model and model_matches_provider(provider, model):
        return model.strip()
    return default_model_for_provider(provider)


logger = logging.getLogger(__name__)


class LlmError(Exception):
    pass


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def _extract_json(text: str) -> dict[str, Any]:
    text = _strip_markdown_fences(text)
    if not text:
        raise LlmError("LLM response did not contain valid JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise LlmError("LLM response did not contain valid JSON")


def _gemini_answer_text(data: dict[str, Any]) -> tuple[str, str | None]:
    """Return visible answer text (skip thought parts) and finishReason."""
    cand = (data.get("candidates") or [{}])[0]
    finish = cand.get("finishReason")
    parts = cand.get("content", {}).get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if part.get("thought"):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks), finish


async def call_anthropic(
    *,
    api_key: str,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> tuple[dict[str, Any], str]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            raise LlmError(f"Anthropic HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    parts = data.get("content") or []
    raw = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if not raw.strip():
        raise LlmError("Empty Anthropic response")
    return _extract_json(raw), raw


async def call_google_gemini(
    *,
    api_key: str,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.35,
) -> tuple[dict[str, Any], str]:
    """Google AI Studio (Gemini) — same API as trading-dashboard google_llm.php."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            # 2.5 Flash thinks by default; thinking tokens share maxOutputTokens and
            # truncate JSON (finishReason=MAX_TOKENS). Disable for structured trader output.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    retry_statuses = {429, 503}
    last_err: LlmError | None = None
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
            else:
                err = LlmError(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")
                last_err = err
                if resp.status_code in retry_statuses and attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise err

            api_err = (data.get("error") or {}).get("message")
            if api_err:
                err = LlmError(f"Gemini error: {api_err}")
                last_err = err
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise err

            raw, finish = _gemini_answer_text(data)
            if not raw.strip():
                block = (data.get("promptFeedback") or {}).get("blockReason")
                err = LlmError(f"Empty Gemini response{f' ({block})' if block else ''}")
                last_err = err
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise err

            try:
                return _extract_json(raw), raw
            except LlmError as exc:
                last_err = exc
                usage = data.get("usageMetadata") or {}
                logger.warning(
                    "Gemini JSON parse failed (attempt %s/%s finish=%s raw_len=%s thoughts=%s output=%s tail=%r)",
                    attempt + 1,
                    3,
                    finish,
                    len(raw),
                    usage.get("thoughtsTokenCount"),
                    usage.get("candidatesTokenCount"),
                    raw[-200:],
                )
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise LlmError(
                    f"LLM response did not contain valid JSON (finish={finish}, len={len(raw)})"
                ) from exc
        assert last_err is not None
        raise last_err


async def call_openai(
    *,
    api_key: str,
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> tuple[dict[str, Any], str]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            raise LlmError(f"OpenAI HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    return _extract_json(raw), raw


async def call_llm(
    *,
    provider: str,
    api_key: str,
    model: str,
    system: str,
    user_message: str,
) -> tuple[dict[str, Any], str]:
    provider = (provider or "google").lower()
    if provider in ("google", "gemini"):
        return await call_google_gemini(
            api_key=api_key, model=model, system=system, user_message=user_message
        )
    if provider == "anthropic":
        return await call_anthropic(
            api_key=api_key, model=model, system=system, user_message=user_message
        )
    if provider == "openai":
        return await call_openai(
            api_key=api_key, model=model, system=system, user_message=user_message
        )
    raise LlmError(
        f"Unsupported provider: {provider}. Use google, anthropic, or openai."
    )
