"""
web_search.py — Web search using Gemini with Google Search grounding.

Falls back to direct Gemini queries if grounding unavailable.
"""
from __future__ import annotations

from typing import Any

from gemini_ai import search_web as _gemini_search
from log_config import get_logger

_log = get_logger("web_search")


def search(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the web for a topic. Returns structured results."""
    _log.info("Searching web: %s (max %d)", query, max_results)
    return _gemini_search(query, num_results=max_results)
