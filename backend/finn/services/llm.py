"""LLM gateway: Google Gemini (free tier) through its OpenAI-compatible endpoint.

Rules first; Flash-Lite ("fast") for bulk extraction; Flash ("strong") only for synthesis.
The response cache lives in its own SQLite file so an LLM call made inside an open write
transaction on the main DB can never deadlock on it.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from typing import Any, Optional

import httpx

from ..config import settings

FALLBACK_FAST = "gemini-3.5-flash-lite"
FALLBACK_STRONG = "gemini-3.8-flash"
_EXCLUDE = re.compile(r"image|tts|audio|live|embed|vision|thinking|exp|preview|learnlm", re.I)

_lock = threading.Lock()
_cache_lock = threading.Lock()
_last_call = 0.0
_models: dict[str, str] | None = None
_json_mode_ok = True  # flipped off once the endpoint rejects response_format, so we stop paying for the retry
_stats = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0, "errors": 0}


def available() -> bool:
    return bool(settings.llm_api_key)


def reset_state() -> None:
    global _models, _last_call, _json_mode_ok
    _models = None
    _json_mode_ok = True
    _last_call = 0.0
    for k in _stats:
        _stats[k] = 0


def _version_key(model_id: str) -> tuple:
    head = model_id.split("flash")[0]
    return tuple(int(x) for x in re.findall(r"\d+", head))


def resolve_models() -> dict[str, str]:
    """Resolve fast/strong once per process. Env overrides win; else list models; else fallbacks."""
    global _models
    if _models is not None:
        return _models
    fast, strong = settings.llm_fast_model, settings.llm_strong_model
    if (not fast or not strong) and available():
        try:
            r = httpx.get(f"{settings.llm_base_url}/models", timeout=15,
                          headers={"Authorization": f"Bearer {settings.llm_api_key}"})
            r.raise_for_status()
            ids = [str(m.get("id", "")).removeprefix("models/") for m in r.json().get("data", [])]
            ids = [i for i in ids if i.startswith("gemini-") and not _EXCLUDE.search(i)]
            lites = sorted([i for i in ids if i.endswith("flash-lite")], key=_version_key)
            flashes = sorted([i for i in ids if i.endswith("-flash")], key=_version_key)
            fast = fast or (lites[-1] if lites else None)
            strong = strong or (flashes[-1] if flashes else None)
        except Exception:
            pass
    _models = {"fast": fast or FALLBACK_FAST, "strong": strong or FALLBACK_STRONG}
    return _models


# ---------------------------------------------------------------- cache
def _cache_conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(settings.llm_cache_path), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, at REAL)")
    return c


def _cache_get(key: str) -> Optional[str]:
    try:
        with _cache_lock:
            c = _cache_conn()
            try:
                row = c.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
            finally:
                c.close()
        return row[0] if row else None
    except Exception:
        return None


def _cache_put(key: str, value: str) -> None:
    try:
        with _cache_lock:
            c = _cache_conn()
            try:
                c.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, value, time.time()))
                c.commit()
            finally:
                c.close()
    except Exception:
        pass


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = settings.llm_min_interval_s - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def complete(messages: list[dict[str, str]], tier: str = "fast", json_mode: bool = False,
             max_tokens: int = 800, temperature: float = 0.0) -> Optional[str]:
    if not available():
        return None
    model = resolve_models()[tier]
    key = hashlib.sha256(json.dumps([model, messages, json_mode], sort_keys=True).encode()).hexdigest()
    hit = _cache_get(key)
    if hit is not None:
        _stats["cache_hits"] += 1
        return hit
    global _json_mode_ok
    use_json = json_mode and _json_mode_ok
    for attempt in range(4):
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature}
        if use_json:
            body["response_format"] = {"type": "json_object"}
        _throttle()
        try:
            r = httpx.post(f"{settings.llm_base_url}/chat/completions", json=body,
                           timeout=settings.llm_timeout_s,
                           headers={"Authorization": f"Bearer {settings.llm_api_key}"})
        except httpx.HTTPError:
            _stats["errors"] += 1
            continue
        if r.status_code == 429:
            _stats["errors"] += 1
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = 8 * (attempt + 1)
            time.sleep(min(60.0, wait))
            continue
        if r.status_code == 400 and use_json:
            use_json = _json_mode_ok = False
            continue
        if r.status_code >= 400:
            _stats["errors"] += 1
            continue
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
        except Exception:
            _stats["errors"] += 1
            continue
        _stats["calls"] += 1
        _stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        _stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        _cache_put(key, text)
        return text
    return None


def parse_json(text: Optional[str]) -> Any:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                continue
    return None


def complete_json(messages: list[dict[str, str]], tier: str = "fast", max_tokens: int = 1200) -> Any:
    return parse_json(complete(messages, tier=tier, json_mode=True, max_tokens=max_tokens))


def stats() -> dict[str, Any]:
    out: dict[str, Any] = dict(_stats)
    out["tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    out["provider"] = "Google Gemini"
    out["configured"] = available()
    out["models"] = resolve_models() if available() else None
    out["routing"] = {
        "fast": "classification fallback, summaries, bios, results-page fallback, guidance extraction",
        "strong": "narrative synthesis, guidance interpretation, bull vs bear",
    }
    return out
