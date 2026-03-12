"""
market_reasoner.py — Fast, non-LLM marketplace reasoning for broad queries.

Goal: turn vague user phrasing (\"giá rẻ\", \"thật chiến\", \"bán gấp\") into
an expanded keyword bundle + structured constraints, then rank results.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_HERE = Path(__file__).parent
_CACHE_DIR = _HERE / "data" / "cache"


@dataclass(frozen=True)
class MarketQuery:
    group_id: str
    query: str
    days: int
    max_price_vnd: int | None
    keywords: list[str]
    must_any: list[str]


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _default_lexicon() -> dict[str, list[str]]:
    # Generic marketplace Vietnamese + some EN shorthands.
    return {
        "cheap": ["giá rẻ", "giá mềm", "rẻ", "hời", "deal", "bán gấp", "cần tiền", "fix", "chốt", "pass", "thanh lý"],
        "buy_intent": ["cần mua", "need", "ib", "inbox", "dm", "để lại sdt", "giá bao nhiêu", "bnhiu"],
        "sell_intent": ["bán", "pass", "thanh lý", "bán gấp", "xả", "dọn nhà"],
        "condition_good": ["zin", "like new", "99%", "ít dùng", "fullbox", "đẹp", "mới", "seal"],
        "condition_bad": ["lỗi", "hỏng", "nứt", "trầy", "móp", "thay", "sửa"],
        "location_hcm": ["hcm", "tphcm", "sài gòn", "sg", "q1", "q3", "q7", "thủ đức", "bình thạnh", "gò vấp"],
        "location_hn": ["hn", "hà nội", "hanoi", "cầu giấy", "đống đa", "hai bà trưng", "hoàng mai"],
        # Domain hints (vehicles)
        "motorbike": ["xe", "xe máy", "côn tay", "tay ga", "exciter", "winner", "satria", "raider", "sh", "vision", "air blade", "ab"],
        # Domain hints (phones)
        "iphone": ["iphone", "ip", "ios", "vna", "ll/a", "fullbox", "pin", "bh", "bảo hành"],
    }


def _tokenize_query(q: str) -> list[str]:
    qn = _normalize_text(q)
    # Keep alnum tokens; preserve model numbers (15, 128, 256) by keeping digits too.
    tokens = re.findall(r"[\w]+", qn, flags=re.U)
    return [t for t in tokens if len(t) >= 2]


def _extract_max_price_vnd(q: str) -> int | None:
    # Parse constraints like: "dưới 10tr", "<10tr", "max 5 triệu", "under 8m"
    qn = _normalize_text(q)

    m = re.search(r"(?:dưới|<|under|max)\s*(\d+(?:[.,]\d+)?)\s*(tr|triệu|m)\b", qn)
    if m:
        val = float(m.group(1).replace(",", "."))
        return int(val * 1_000_000)

    m = re.search(r"(?:dưới|<|under|max)\s*(\d+(?:[.,]\d+)?)\s*(k|nghìn)\b", qn)
    if m:
        val = float(m.group(1).replace(",", "."))
        return int(val * 1_000)

    return None


_PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.,]\d{1,3})?)(?:\s*)(tr|triệu|m|k|nghìn)\b",
    flags=re.I | re.U,
)


def extract_price_vnd(text: str) -> int | None:
    """Extract a single representative price (min) from text."""
    if not text:
        return None
    t = _normalize_text(text)
    prices: list[int] = []
    for num, unit in _PRICE_RE.findall(t):
        n = float(num.replace(",", "."))
        u = unit.lower()
        if u in ("tr", "triệu", "m"):
            prices.append(int(n * 1_000_000))
        elif u in ("k", "nghìn"):
            prices.append(int(n * 1_000))
    return min(prices) if prices else None


def build_market_query(group_id: str, query: str, days: int = 7) -> MarketQuery:
    lex = _default_lexicon()
    qn = _normalize_text(query)
    tokens = _tokenize_query(qn)

    max_price = _extract_max_price_vnd(qn)

    keywords: set[str] = set()
    must_any: set[str] = set()
    # Always keep original tokens joined as phrase for FTS.
    if tokens:
        keywords.add(" ".join(tokens[:6]))

    # Expand by heuristics
    if any(w in qn for w in ("giá rẻ", "rẻ", "deal", "thanh lý", "bán gấp", "cần tiền", "fix")):
        keywords.update(lex["cheap"])
    if any(w in qn for w in ("xe", "xe máy", "côn tay", "tay ga")):
        keywords.update(lex["motorbike"])
        must_any.update(lex["motorbike"])
    if "iphone" in qn or "ip" in tokens:
        keywords.update(lex["iphone"])
        must_any.update(lex["iphone"])

    # Location hints
    if any(w in qn for w in ("hcm", "tphcm", "sài gòn", "sg")):
        keywords.update(lex["location_hcm"])
    if any(w in qn for w in ("hn", "hà nội", "hanoi")):
        keywords.update(lex["location_hn"])

    # Always include sell intent terms if query sounds like finding a deal
    if any(w in qn for w in ("tìm", "deal", "giá", "rẻ", "thanh lý", "bán")):
        keywords.update(lex["sell_intent"])

    # Dedup + keep short list for speed
    kw_list = [k for k in dict.fromkeys([_normalize_text(k) for k in keywords]) if k]
    kw_list = kw_list[:30]
    must_list = [k for k in dict.fromkeys([_normalize_text(k) for k in must_any]) if k]
    must_list = must_list[:20]

    return MarketQuery(
        group_id=group_id,
        query=query,
        days=days,
        max_price_vnd=max_price,
        keywords=kw_list,
        must_any=must_list,
    )


def _cache_key(mq: MarketQuery) -> str:
    h = hashlib.sha256()
    h.update(_normalize_text(mq.group_id).encode("utf-8"))
    h.update(b"\n")
    h.update(_normalize_text(mq.query).encode("utf-8"))
    h.update(b"\n")
    h.update(str(mq.days).encode("utf-8"))
    h.update(b"\n")
    h.update(str(mq.max_price_vnd or "").encode("utf-8"))
    h.update(b"\n")
    h.update("|".join(mq.must_any).encode("utf-8"))
    return h.hexdigest()[:24]


def load_cache(mq: MarketQuery, ttl_minutes: int = 30) -> dict[str, Any] | None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"market_{_cache_key(mq)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("_cached_at")
        if not ts:
            return None
        cached_at = datetime.fromisoformat(ts)
        if datetime.now(tz=timezone.utc) - cached_at > timedelta(minutes=ttl_minutes):
            return None
        return data
    except Exception:
        return None


def save_cache(mq: MarketQuery, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"market_{_cache_key(mq)}.json"
    payload = dict(payload)
    payload["_cached_at"] = datetime.now(tz=timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

