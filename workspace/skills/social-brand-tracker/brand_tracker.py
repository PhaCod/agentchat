"""
brand_tracker.py — Brand mention analysis, share of voice, sentiment per brand.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from text_analysis import analyze_sentiment
from log_config import get_logger

_log = get_logger("brand_tracker")


def analyze_brands(posts: list[dict], comments: list[dict],
                   brands_cfg: list[dict]) -> list[dict]:
    if not brands_cfg:
        return []

    brand_lookup: dict[str, str] = {}
    for b in brands_cfg:
        name = b["name"]
        for kw in b.get("keywords", []) + [name.lower()] + [a.lower() for a in b.get("aliases", [])]:
            brand_lookup[kw] = name

    all_texts = [(p.get("content", ""), p.get("reactions_total", 0),
                  p.get("comments_count", 0), p.get("shares_count", 0))
                 for p in posts]
    all_texts += [(c.get("content", ""), c.get("likes_count", 0), 0, 0)
                  for c in comments]

    brand_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0, "positive": 0, "negative": 0, "neutral": 0,
        "total_engagement": 0, "sample_texts": [],
    })

    total_mentions = 0
    for text, reactions, cmt_count, shares in all_texts:
        text_lower = text.lower()
        for kw, brand_name in brand_lookup.items():
            if kw in text_lower:
                d = brand_data[brand_name]
                d["mentions"] += 1
                total_mentions += 1

                sentiment = analyze_sentiment(text)
                d[sentiment["label"]] += 1
                d["total_engagement"] += reactions + cmt_count + shares

                if len(d["sample_texts"]) < 5:
                    d["sample_texts"].append(text[:200])
                break

    results = []
    for b in brands_cfg:
        name = b["name"]
        d = brand_data[name]
        total = d["mentions"] or 1
        sov = round(d["mentions"] / max(total_mentions, 1) * 100, 1)

        results.append({
            "brand": name,
            "mentions": d["mentions"],
            "share_of_voice_pct": sov,
            "sentiment": {
                "positive": d["positive"],
                "negative": d["negative"],
                "neutral": d["neutral"],
                "positive_pct": round(d["positive"] / total * 100, 1),
                "negative_pct": round(d["negative"] / total * 100, 1),
            },
            "avg_engagement": round(d["total_engagement"] / total, 1),
            "sample_texts": d["sample_texts"],
        })

    results.sort(key=lambda x: x["mentions"], reverse=True)
    return results
