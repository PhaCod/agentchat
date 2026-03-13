"""
trend_detector.py — Detect trending topics, post velocity, engagement velocity.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from log_config import get_logger

_log = get_logger("trend_detector")

_STOPWORDS = {
    "là", "và", "của", "có", "được", "cho", "này", "với", "các", "trong",
    "để", "đã", "khi", "từ", "một", "không", "nên", "thì", "cũng", "mà",
    "the", "is", "and", "of", "to", "in", "for", "on", "it", "this", "that",
}


def detect_trends(posts: list[dict], *, days: int = 7,
                  window_hours: int = 24) -> dict:
    if not posts:
        return {"post_velocity": [], "engagement_velocity": [], "rising_keywords": [], "top_posts": []}

    now = datetime.now(tz=timezone.utc)
    recent_cutoff = now - timedelta(hours=window_hours)
    older_cutoff = now - timedelta(days=days)

    recent_posts, older_posts = [], []
    for p in posts:
        ts = _parse_ts(p.get("posted_at", ""))
        if not ts:
            continue
        if ts >= recent_cutoff:
            recent_posts.append(p)
        elif ts >= older_cutoff:
            older_posts.append(p)

    # Post velocity (posts per hour in recent vs older windows)
    recent_hours = max(window_hours, 1)
    older_hours = max((days * 24) - window_hours, 1)
    recent_velocity = round(len(recent_posts) / recent_hours, 2)
    older_velocity = round(len(older_posts) / older_hours, 2)

    # Engagement velocity
    recent_engagement = sum(p.get("reactions_total", 0) + p.get("comments_count", 0)
                            for p in recent_posts)
    older_engagement = sum(p.get("reactions_total", 0) + p.get("comments_count", 0)
                           for p in older_posts)
    recent_eng_velocity = round(recent_engagement / recent_hours, 2)
    older_eng_velocity = round(older_engagement / older_hours, 2)

    # Rising / declining keywords
    recent_words = _extract_words([p.get("content", "") for p in recent_posts])
    older_words = _extract_words([p.get("content", "") for p in older_posts])

    rising, declining = [], []
    all_keywords = set(list(recent_words.keys())[:100] + list(older_words.keys())[:100])
    for kw in all_keywords:
        r_count = recent_words.get(kw, 0)
        o_count = older_words.get(kw, 0)
        if r_count > o_count and r_count >= 3:
            change = round((r_count - o_count) / max(o_count, 1) * 100, 0)
            rising.append({"keyword": kw, "recent": r_count, "previous": o_count, "change_pct": change})
        elif o_count > r_count and o_count >= 3:
            change = round((o_count - r_count) / max(o_count, 1) * 100, 0)
            declining.append({"keyword": kw, "recent": r_count, "previous": o_count, "change_pct": -change})

    rising.sort(key=lambda x: x["change_pct"], reverse=True)
    declining.sort(key=lambda x: x["change_pct"])

    # Top posts by engagement
    sorted_posts = sorted(posts, key=lambda p: p.get("reactions_total", 0) + p.get("comments_count", 0),
                          reverse=True)
    top_posts = []
    for p in sorted_posts[:10]:
        top_posts.append({
            "post_id": p["post_id"],
            "author": p.get("author_name", ""),
            "preview": (p.get("content", "") or "")[:150],
            "reactions": p.get("reactions_total", 0),
            "comments": p.get("comments_count", 0),
            "shares": p.get("shares_count", 0),
            "total_engagement": p.get("reactions_total", 0) + p.get("comments_count", 0) + p.get("shares_count", 0),
            "post_url": p.get("post_url", ""),
        })

    return {
        "post_velocity": {
            "recent_per_hour": recent_velocity,
            "previous_per_hour": older_velocity,
            "trend": "rising" if recent_velocity > older_velocity * 1.2 else
                     ("declining" if recent_velocity < older_velocity * 0.8 else "stable"),
        },
        "engagement_velocity": {
            "recent_per_hour": recent_eng_velocity,
            "previous_per_hour": older_eng_velocity,
            "trend": "rising" if recent_eng_velocity > older_eng_velocity * 1.2 else
                     ("declining" if recent_eng_velocity < older_eng_velocity * 0.8 else "stable"),
        },
        "rising_keywords": rising[:15],
        "declining_keywords": declining[:10],
        "top_posts": top_posts,
    }


def _parse_ts(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _extract_words(texts: list[str]) -> Counter:
    import re
    counter: Counter = Counter()
    for text in texts:
        words = re.findall(r"[\w]+", text.lower())
        words = [w for w in words if len(w) > 1 and w not in _STOPWORDS and not w.isdigit()]
        counter.update(words)
    return counter
