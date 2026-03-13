from __future__ import annotations
import json
import os
from pathlib import Path

_HERE = Path(__file__).parent
_DEFAULT_CFG = _HERE / "config" / "config.json"


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _DEFAULT_CFG
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _get(cfg: dict, *keys, default=None):
    node = cfg
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return default
        if node is None:
            return default
    return node
