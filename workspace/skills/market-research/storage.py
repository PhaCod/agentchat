"""
storage.py — Data persistence for market research results.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from log_config import get_logger

_log = get_logger("storage")
_HERE = Path(__file__).parent
_DATA_DIR = _HERE / "data"
_RESEARCH_DIR = _DATA_DIR / "research"
_CACHE_DIR = _DATA_DIR / "cache"


def _ensure_dirs():
    _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, text.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(path))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _slug(text: str) -> str:
    """Convert text to filesystem-safe slug."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "_", s).strip("_")
    return s[:80] or "untitled"


def save_research(topic: str, result: dict) -> Path:
    """Save research result to disk. Returns the file path."""
    _ensure_dirs()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _slug(topic)
    filename = f"{ts}_{slug}.json"
    path = _RESEARCH_DIR / filename

    envelope = {
        "topic": topic,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "result": result,
    }
    _atomic_write(path, json.dumps(envelope, ensure_ascii=False, indent=2))
    _log.info("Research saved: %s", path)
    return path


def save_report(topic: str, report_text: str) -> Path:
    """Save markdown report to disk. Returns the file path."""
    _ensure_dirs()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _slug(topic)
    filename = f"{ts}_{slug}_report.md"
    path = _RESEARCH_DIR / filename
    _atomic_write(path, report_text)
    _log.info("Report saved: %s", path)
    return path


def load_latest_research(topic: str | None = None) -> dict | None:
    """Load the most recent research result, optionally filtered by topic."""
    _ensure_dirs()
    files = sorted(_RESEARCH_DIR.glob("*.json"), reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if topic is None or _slug(topic) in f.name:
                return data
        except Exception:
            continue
    return None


def list_research() -> list[dict]:
    """List all saved research results."""
    _ensure_dirs()
    results = []
    for f in sorted(_RESEARCH_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "file": f.name,
                "topic": data.get("topic", ""),
                "created_at": data.get("created_at", ""),
            })
        except Exception:
            continue
    return results


def get_cache(key: str, ttl_hours: int = 6) -> dict | None:
    """Get cached search result if still fresh."""
    path = _CACHE_DIR / f"{_slug(key)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("cached_at", ""))
        age_hours = (datetime.now(tz=timezone.utc) - cached_at).total_seconds() / 3600
        if age_hours < ttl_hours:
            return data.get("result")
    except Exception:
        pass
    return None


def set_cache(key: str, result: dict):
    """Cache a search result."""
    _ensure_dirs()
    path = _CACHE_DIR / f"{_slug(key)}.json"
    envelope = {
        "key": key,
        "cached_at": datetime.now(tz=timezone.utc).isoformat(),
        "result": result,
    }
    _atomic_write(path, json.dumps(envelope, ensure_ascii=False, indent=2))
