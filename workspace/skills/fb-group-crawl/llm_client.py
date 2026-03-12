"""
llm_client.py — Shared LLM wrapper for fb-group-crawl.

Goals:
- One place to configure provider/model/keys for this skill.
- Simple logging of model + error.
- Light retry for transient errors (non-429).

NOTE: This wrapper is intentionally minimal to stay compatible with the
existing ai_query.py logic. It does NOT change prompts or answers.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from log_config import get_logger

_log = get_logger("llm_client")

# Ledger for token usage (skill-side Gemini calls) — append-only JSONL
_WORKSPACE_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_LEDGER_PATH = _WORKSPACE_DATA / "token_usage.jsonl"


def _append_token_record(skill: str, call: str, model: str, input_tokens: int, output_tokens: int) -> None:
    try:
        _WORKSPACE_DATA.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "date": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "skill": skill,
            "call": call,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        with open(_LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _log.debug("Token ledger append failed: %s", e)


class LLMError(RuntimeError):
    pass


def get_gemini_config(cfg: dict | None = None) -> dict:
    """Resolve Gemini config for this skill.

    Priority:
    1) cfg["gemini"] passed from caller
    2) Environment variables (GOOGLE_API_KEY, GEMINI_MODEL)
    3) Reasonable defaults
    """
    c = (cfg or {}).get("gemini", {}) if cfg else {}
    api_key = c.get("api_key") or os.environ.get("GOOGLE_API_KEY", "")
    model = c.get("model") or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    lang = c.get("language", "vi")
    return {"api_key": api_key, "model": model, "language": lang}


def call_gemini(
    system_and_user_prompt: str,
    *,
    cfg: dict | None = None,
    context_truncate_fn: Callable[[str], str] | None = None,
    max_retries: int = 2,
) -> str:
    """Call Gemini via google-generativeai with light retry.

    - `system_and_user_prompt` should already contain any context.
    - `context_truncate_fn` can optionally shorten context on retry.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        return "[google-generativeai package not installed. Run: pip install google-generativeai]"

    gcfg = get_gemini_config(cfg)
    api_key = gcfg["api_key"]
    model_name = gcfg["model"]
    if not api_key:
        return "[Gemini API key not configured. Set GOOGLE_API_KEY env or gemini.api_key in config.]"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = system_and_user_prompt
    for attempt in range(max_retries + 1):
        try:
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", "") or ""
            _log.info("Gemini ok model=%s len=%d", model_name, len(text))
            # Token usage: from API if available, else estimate (~4 chars/token)
            inp, out = 0, 0
            um = getattr(resp, "usage_metadata", None)
            if um is not None:
                inp = getattr(um, "prompt_token_count", 0) or 0
                out = getattr(um, "candidates_token_count", 0) or getattr(um, "output_token_count", 0) or 0
            if inp == 0 and out == 0:
                inp = max(1, len(prompt) // 4)
                out = max(1, len(text) // 4)
            _append_token_record("fb-group-crawl", "ask", model_name, inp, out)
            return text
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            is_429 = "429" in msg or "TooManyRequests" in msg or "rate limit" in msg.lower()
            _log.warning("Gemini error (attempt %d/%d): %s", attempt + 1, max_retries + 1, msg)
            if is_429:
                # Do not hammer on 429; bubble up as-is.
                return f"[Gemini rate limit or quota error: {msg}]"
            if attempt >= max_retries:
                return f"[Gemini error after retries: {msg}]"
            # Best-effort small backoff + optional truncation.
            if context_truncate_fn is not None:
                prompt = context_truncate_fn(prompt)
            time.sleep(1.0 + attempt * 1.0)

    # Should not reach here
    return "[Gemini call failed unexpectedly.]"

