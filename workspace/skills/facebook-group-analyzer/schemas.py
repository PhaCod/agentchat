"""
schemas.py — Canonical data structures and schema version for posts and reports.
Single source of truth for field names and structure; enables validation and migration.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Schema version (bump when breaking change)
# ---------------------------------------------------------------------------

POSTS_SCHEMA_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Post (raw scraped item)
# ---------------------------------------------------------------------------

POST_REQUIRED_FIELDS = (
    "post_id",
    "group_id",
    "author",
    "author_id",
    "content",
    "media",
    "reactions",
    "comments_count",
    "shares_count",
    "post_url",
    "timestamp",
    "content_type",
    "scraped_at",
)
POST_OPTIONAL_FIELDS = ("spam_score",)

def post_to_row(p: dict[str, Any]) -> dict[str, Any]:
    """Flatten a post for CSV/export; reactions.total → reactions_total."""
    row = {k: p.get(k) for k in POST_REQUIRED_FIELDS if k != "reactions"}
    row["reactions_total"] = (p.get("reactions") or {}).get("total", 0)
    if "spam_score" in p:
        row["spam_score"] = p["spam_score"]
    return row


def csv_fieldnames() -> list[str]:
    """Column order for CSV export."""
    return [
        "post_id", "group_id", "author", "author_id",
        "content", "content_type", "timestamp", "scraped_at",
        "reactions_total", "comments_count", "shares_count",
        "post_url", "spam_score",
    ]


# ---------------------------------------------------------------------------
# Report (analysis output)
# ---------------------------------------------------------------------------

REPORT_TOP_LEVEL_KEYS = (
    "schema_version",
    "group_id",
    "analyzed_at",
    "total_posts",
    "posts_with_content",
    "posts_excluded_from_text_analysis",
    "date_range",
    "sentiment",
    "top_keywords",
    "topics",
    "spam_posts_count",
    "spam_post_ids",
    "engagement",
    "trends",
)


def report_with_schema(report: dict[str, Any]) -> dict[str, Any]:
    """Ensure report has schema_version for storage."""
    out = dict(report)
    out["schema_version"] = REPORT_SCHEMA_VERSION
    return out


# ---------------------------------------------------------------------------
# Posts file container (metadata + list of posts)
# ---------------------------------------------------------------------------

def posts_container(group_id: str, posts: list[dict], updated_at: str | None = None) -> dict[str, Any]:
    """Wrap posts in versioned container with metadata."""
    from datetime import datetime, timezone
    return {
        "schema_version": POSTS_SCHEMA_VERSION,
        "group_id": group_id,
        "updated_at": (updated_at or datetime.now(timezone.utc).isoformat()),
        "post_count": len(posts),
        "posts": posts,
    }


def unwrap_posts(data: dict | list) -> list[dict]:
    """Return list of posts from either legacy (array) or new (container) format."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "posts" in data:
        return data["posts"]
    return []


# ---------------------------------------------------------------------------
# Manifest (index of groups and last run times)
# ---------------------------------------------------------------------------

def manifest_skeleton() -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "updated_at": None,
        "groups": [],
    }


def group_manifest_entry(
    group_id: str,
    post_count: int,
    date_from: str | None,
    date_to: str | None,
    last_scraped_at: str | None = None,
    last_analyzed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "post_count": post_count,
        "date_range": {"from": date_from, "to": date_to},
        "last_scraped_at": last_scraped_at,
        "last_analyzed_at": last_analyzed_at,
    }
