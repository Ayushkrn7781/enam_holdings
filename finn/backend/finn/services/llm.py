"""Thin LLM gateway with model routing, response caching and graceful degradation.

Provider: Google Gemini through its OpenAI-compatible endpoint (free tier: Flash / Flash-Lite).
Routing policy (cost discipline):
  fast   -> Flash-Lite: classification fallback, one-line summaries, bio / guidance extraction
  strong -> Flash: research synthesis, promise-vs-delivered interpretation only
Model IDs are discovered from the provider's /models list (newest Flash-Lite / Flash), so a Gemini
version bump never breaks the app; LLM_FAST_MODEL / LLM_STRONG_MODEL override the choice.
A client-side throttle keeps calls under the free-tier requests-per-minute limit.

Every call is cached by sha256(model + messages), so re-running a refresh or re-asking a question
costs nothing. If no API key is configured, `available()` is False and every caller has a deterministic
fallback path — the app never depends on a paid or keyed service to run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Literal

import httpx

import sqlite3
import threading

from ..config import DATA_DIR, settings

log = logging.getLogger("finn.llm")
Tier = Literal["fast", "strong"]

_stats = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0, "errors": 0}


# The response cache lives in its own SQLite file so a cache write can never contend with
# (or deadlock against) an in-flight transaction in the main database.
_CACHE_PATH = DATA_DIR / "llm_cache.db"
_cache_lock = threading.Lock()


def _cache_conn() -> sqlite3.Connection:
    c = sqlite3.connect(_CACHE_PATH, timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, model TEXT, response TEXT, prompt_tokens INT, completion_tokens INT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return c


def _cache_get(key: str) -> str | None:
    try:
        with _cache_lock, _cache_conn() as c:
            row = c.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error as e:
        log.warning("llm cache read failed: %s", e)
        return None


def _cache_put(key: str, model: str, text: str, usage: dict) -> None:
    try:
        with _cache_lock, _cache_conn() as c:
            c.execute("INSERT OR REPLACE INTO llm_cache (key, model, response, prompt_tokens, completion_tokens) VALUES (?,?,?,?,?)",
                      (key, model, text, usage.get("prompt_tokens"), usage.get("completion_tokens")))
    except sqlite3.Error as e:  # a cache miss next time is fine; failing the call is not
        log.warning("llm cache write failed: %s", e)


def available() -> bool:
    return bool(settings.llm_api_key)


def stats() -> dict[str, Any]:
    m = resolve_models() if available() else {"fast": settings.llm_fast_model or "auto (Flash-Lite)", "strong": settings.llm_strong_model or "auto (Flash)"}
    return {
        **_stats,
        "provider": ("Google Gemini" if "generativelanguage" in settings.llm_base_url else settings.llm_base_url) if available() else None,
        "fast_model": m["fast"],
        "strong_model": m["strong"],
        "configured": available(),
    }


_models: dict[str, str] = {}
_FALLBACK = {"fast": "gemini-3.5-flash-lite", "strong": "gemini-3.8-flash"}
_last_call = 0.0
_throttle = threading.Lock()


def _version(mid: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", mid.split("flash")[0])) or (0,)


def resolve_models() -> dict[str, str]:
    """Pick models once per process: env override > newest stable Flash-Lite / Flash from /models > fallback."""
    if _models:
        return _models
    fast, strong = settings.llm_fast_model, settings.llm_strong_model
    if (not fast or not strong) and available():
        try:
            r = httpx.get(f"{settings.llm_base_url}/models", headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=15)
            r.raise_for_status()
            ids = [m["id"].removeprefix("models/") for m in r.json().get("data", [])]
            text_ok = lambda m: m.startswith("gemini-") and not re.search(r"image|tts|audio|live|embed|vision|thinking|exp|preview|learnlm", m)  # noqa: E731
            lites = sorted((m for m in ids if text_ok(m) and "flash-lite" in m), key=_version)
            flashes = sorted((m for m in ids if text_ok(m) and m.endswith("-flash")), key=_version)
            fast = fast or (lites[-1] if lites else None)
            strong = strong or (flashes[-1] if flashes else None)
        except Exception as e:
            log.warning("could not list provider models (%s); using fallbacks", e)
    _models.update(fast=fast or _FALLBACK["fast"], strong=strong or _FALLBACK["strong"])
    log.info("LLM models: fast=%s strong=%s", _models["fast"], _models["strong"])
    return _models


def _model(tier: Tier) -> str:
    return resolve_models()[tier]


def _wait_turn() -> None:
    global _last_call
    with _throttle:
        gap = settings.llm_min_interval_s - (time.time() - _last_call)
        if gap > 0:
            time.sleep(gap)
        _last_call = time.time()


def complete(
    messages: list[dict[str, str]],
    tier: Tier = "fast",
    *,
    json_mode: bool = False,
    max_tokens: int = 700,
    temperature: float = 0.0,
) -> str | None:
    """Return model text, or None if the LLM is unavailable/failed (caller must fall back)."""
    if not available():
        return None
    model = _model(tier)
    key = hashlib.sha256(json.dumps([model, messages, json_mode], sort_keys=True).encode()).hexdigest()
    hit = _cache_get(key)
    if hit is not None:
        _stats["cache_hits"] += 1
        return hit

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    for attempt in range(4):
        try:
            _wait_turn()
            r = httpx.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
                timeout=settings.llm_timeout_s,
            )
            if r.status_code == 429:  # free-tier rate limit: honour Retry-After, else back off
                wait = float(r.headers.get("retry-after", 0) or 0) or 8 * (attempt + 1)
                log.info("rate limited by provider; waiting %.0fs", wait)
                time.sleep(min(wait, 60))
                continue
            if r.status_code == 400 and "response_format" in payload:
                payload.pop("response_format")  # some compatible endpoints reject JSON mode: ask in-prompt instead
                continue
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
        except Exception as e:  # network, 5xx, malformed
            log.warning("LLM call failed (%s, attempt %d): %s", model, attempt + 1, e)
            time.sleep(1)
            continue
        usage = data.get("usage", {})
        _stats["calls"] += 1
        _stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        _stats["completion_tokens"] += usage.get("completion_tokens", 0)
        _cache_put(key, model, text, usage)
        return text
    _stats["errors"] += 1
    return None


def complete_json(messages: list[dict[str, str]], tier: Tier = "fast", **kw) -> Any | None:
    text = complete(messages, tier, json_mode=True, **kw)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    log.warning("LLM returned non-JSON output")
    return None
