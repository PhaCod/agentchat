"""
log_config.py — Structured logging for production. LOG_LEVEL from env (default INFO).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text")  # "text" | "json"


def get_logger(name: str) -> logging.Logger:
    """Return a logger with level and format set from env."""
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    h = logging.StreamHandler(sys.stderr)
    h.setLevel(log.level)
    if LOG_FORMAT == "json":
        h.setFormatter(JsonFormatter())
    else:
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log.addHandler(h)
    return log


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
