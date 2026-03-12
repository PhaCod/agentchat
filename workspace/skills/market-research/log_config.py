from __future__ import annotations
import logging
import os
import sys

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FMT))
        logging.root.addHandler(handler)
        logging.root.setLevel(getattr(logging, level, logging.INFO))
        _configured = True
    return logging.getLogger(name)
