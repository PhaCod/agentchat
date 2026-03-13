from __future__ import annotations
import logging
import sys

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        logging.basicConfig(
            level=logging.INFO,
            format=_FMT,
            stream=sys.stderr,
        )
        _configured = True
    return logging.getLogger(name)
