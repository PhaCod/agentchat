"""
influencer.py — Score and rank users by influence metrics.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from log_config import get_logger

_log = get_logger("influencer")
_HERE = Path(__file__).parent
_DB_PATH = _HERE / "data" / "brand_tracker.db"


def score_influencers(source_id: str, *, threshold: int = 10000,
                      top_n: int = 20) -> list[dict]:
    db_path = _DB_PATH
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get users who posted or commented in this source
    rows = conn.execute("""
        SELECT u.user_id, u.display_name, u.follower_count, u.is_verified,
               u.is_influencer, u.total_posts, u.total_comments,
               u.location, u.bio_keywords
        FROM users u
        WHERE u.user_id IN (
            SELECT DISTINCT author_id FROM posts WHERE source_id = ?
            UNION
            SELECT DISTINCT commenter_id FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE p.source_id = ?
        )
        ORDER BY u.follower_count DESC, (u.total_posts + u.total_comments) DESC
        LIMIT ?
    """, (source_id, source_id, top_n)).fetchall()

    conn.close()

    results = []
    for r in rows:
        r = dict(r)
        activity = r.get("total_posts", 0) + r.get("total_comments", 0)
        followers = r.get("follower_count", 0)

        # Simple influence score: followers weight + activity weight
        score = followers * 0.7 + activity * 100 * 0.3
        if r.get("is_verified"):
            score *= 1.5

        tier = "mega" if followers >= 100_000 else \
               "macro" if followers >= 50_000 else \
               "micro" if followers >= threshold else "nano"

        results.append({
            "user_id": r["user_id"],
            "display_name": r.get("display_name", ""),
            "follower_count": followers,
            "is_verified": bool(r.get("is_verified")),
            "tier": tier,
            "total_posts": r.get("total_posts", 0),
            "total_comments": r.get("total_comments", 0),
            "activity_score": activity,
            "influence_score": round(score, 1),
            "location": r.get("location", ""),
        })

    results.sort(key=lambda x: x["influence_score"], reverse=True)
    return results
