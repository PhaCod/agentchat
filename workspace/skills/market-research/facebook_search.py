"""
facebook_search.py — Search Facebook groups for topic-related posts.

Reuses the facebook-group-analyzer scraper infrastructure.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from log_config import get_logger

_log = get_logger("facebook")
_HERE = Path(__file__).parent
_FB_SKILL = _HERE.parent / "facebook-group-analyzer"


def _load_config() -> dict:
    cfg_path = _HERE / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def _get_fb_env() -> dict[str, str]:
    """Load Facebook credentials from this skill's .env or parent skill's .env."""
    env_vars: dict[str, str] = {}
    for env_path in [_HERE / ".env", _FB_SKILL / ".env"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env_vars


def search_groups(
    topic: str,
    group_urls: list[str] | None = None,
    max_posts: int = 30,
    days: int = 7,
) -> dict[str, Any]:
    """Search Facebook groups for posts related to a topic.

    Args:
        topic: Search topic/keyword
        group_urls: List of Facebook group URLs to search. Uses defaults from config if empty.
        max_posts: Maximum posts to collect per group
        days: How many days back to search
    """
    cfg = _load_config()
    if not group_urls:
        group_urls = cfg.get("facebook", {}).get("default_groups", [])
    if not group_urls:
        return {
            "status": "error",
            "source": "facebook",
            "error": "No Facebook groups configured. Add groups to config.json or pass --facebook-groups",
        }

    # Check if facebook-group-analyzer exists and is usable
    if not (_FB_SKILL / "main.py").exists():
        return {
            "status": "error",
            "source": "facebook",
            "error": f"facebook-group-analyzer skill not found at {_FB_SKILL}",
        }

    # Add the FB skill to path so we can import its modules
    fb_skill_str = str(_FB_SKILL)
    if fb_skill_str not in sys.path:
        sys.path.insert(0, fb_skill_str)

    env_vars = _get_fb_env()
    import os
    for k, v in env_vars.items():
        os.environ.setdefault(k, v)

    all_posts: list[dict] = []

    for group_url in group_urls:
        _log.info("Scraping Facebook group: %s (max %d posts, %d days)", group_url, max_posts, days)
        try:
            from post_scraper import GroupPostScraper
            from load_config import load_config as fb_load_config

            fb_cfg = fb_load_config()
            fb_cfg.setdefault("scraper", {})
            fb_cfg["scraper"]["max_posts"] = max_posts
            fb_cfg["scraper"]["days_back"] = days
            fb_cfg["scraper"]["headless"] = True

            scraper = GroupPostScraper(cfg=fb_cfg)
            posts = scraper.scrape(group_url)
            _log.info("Collected %d posts from group", len(posts))
            all_posts.extend(posts)

        except Exception as e:
            _log.error("Facebook scrape failed for %s: %s", group_url, e)
            continue

    # Filter posts by topic keyword if possible
    topic_lower = topic.lower()
    topic_words = set(re.split(r"\s+", topic_lower))
    relevant = []
    other = []
    for p in all_posts:
        content = (p.get("content") or "").lower()
        if any(w in content for w in topic_words if len(w) > 2):
            relevant.append(p)
        else:
            other.append(p)

    # Include all posts but mark relevance
    result_posts = []
    for p in relevant + other:
        result_posts.append({
            "post_id": p.get("post_id", ""),
            "author": p.get("author", "Unknown"),
            "content": (p.get("content") or "")[:500],
            "reactions": p.get("reactions", {}).get("total", 0),
            "comments": p.get("comments_count", 0),
            "shares": p.get("shares_count", 0),
            "timestamp": p.get("timestamp", ""),
            "post_url": p.get("post_url", ""),
            "content_type": p.get("content_type", "text"),
            "relevant_to_topic": p in relevant,
        })

    _log.info(
        "Facebook search complete: %d total posts, %d relevant to '%s'",
        len(result_posts), len(relevant), topic,
    )

    return {
        "status": "ok",
        "source": "facebook",
        "topic": topic,
        "groups_searched": len(group_urls),
        "total_posts": len(result_posts),
        "relevant_posts": len(relevant),
        "data": result_posts[:max_posts],
    }
