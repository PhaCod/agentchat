"""
load_config.py — Load config from config/config.json and override secrets from environment.
Production: set FB_EMAIL, FB_PASSWORD (and optional PROXY_*) in env; never commit secrets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_HERE = Path(__file__).parent
_CONFIG_PATH = _HERE / "config" / "config.json"
_ENV_PATH = _HERE / ".env"


def _load_dotenv() -> None:
    """Load .env into os.environ (simple KEY=VALUE)."""
    if not _ENV_PATH.exists():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and v:
                os.environ.setdefault(k, v)


def load_config() -> dict:
    """Load config.json and apply env overrides for secrets."""
    _load_dotenv()
    cfg = {}
    if _CONFIG_PATH.exists():
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))

    # Env overrides (production-safe)
    fb = cfg.setdefault("facebook", {})
    if os.environ.get("FB_EMAIL"):
        fb["email"] = os.environ["FB_EMAIL"]
    if os.environ.get("FB_PASSWORD"):
        fb["password"] = os.environ["FB_PASSWORD"]
    session_file = os.environ.get("FB_SESSION_FILE")
    if session_file:
        fb["session_file"] = session_file

    proxy = cfg.setdefault("proxy", {})
    if os.environ.get("PROXY_ENABLED", "").lower() in ("1", "true", "yes"):
        proxy["enabled"] = True
    if os.environ.get("PROXY_USERNAME"):
        proxy["username"] = os.environ["PROXY_USERNAME"]
    if os.environ.get("PROXY_PASSWORD"):
        proxy["password"] = os.environ["PROXY_PASSWORD"]

    return cfg
