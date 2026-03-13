"""
report_generator.py — Generate full brand analytics reports in JSON or Markdown.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import db
from text_analysis import analyze_sentiment_batch, extract_keywords, cluster_topics
from brand_tracker import analyze_brands
from pain_detector import detect_pain_points
from trend_detector import detect_trends
from influencer import score_influencers
from log_config import get_logger

_log = get_logger("report")


def generate_report(source_id: str, *, days: int = 7,
                    cfg: dict | None = None, fmt: str = "json") -> dict:
    cfg = cfg or {}
    posts = db.get_posts(source_id, days=days)
    comments = db.get_comments(source_id=source_id, days=days)

    if not posts:
        return {"status": "no_data", "message": f"No posts for {source_id} in {days} days"}

    post_texts = [p["content"] for p in posts if p.get("content")]
    comment_texts = [c["content"] for c in comments if c.get("content")]
    all_texts = post_texts + comment_texts

    sentiment = analyze_sentiment_batch(all_texts)
    keywords = extract_keywords(all_texts, min_freq=cfg.get("analysis", {}).get("min_keyword_freq", 3))
    topics = cluster_topics(all_texts)
    brands = analyze_brands(posts, comments, cfg.get("brands", []))
    pains = detect_pain_points(all_texts)
    trends = detect_trends(posts, days=days,
                           window_hours=cfg.get("analysis", {}).get("trend_window_hours", 24))
    influencer_list = score_influencers(source_id,
                                        threshold=cfg.get("analysis", {}).get("influencer_threshold", 10000))

    report_data = {
        "status": "ok",
        "source_id": source_id,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "period_days": days,
        "overview": {
            "total_posts": len(posts),
            "total_comments": len(comments),
            "total_texts_analyzed": len(all_texts),
            "total_reactions": sum(p.get("reactions_total", 0) for p in posts),
            "total_shares": sum(p.get("shares_count", 0) for p in posts),
        },
        "sentiment": sentiment,
        "top_keywords": keywords[:20],
        "topics": topics[:10],
        "brands": brands,
        "pain_points": pains[:15],
        "trends": trends,
        "top_influencers": influencer_list[:10],
    }

    # Save run
    run_id = f"report_{source_id}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    db.save_analysis_run(run_id, source_id, "full_report", {"days": days}, report_data)

    if fmt == "md":
        report_data["markdown"] = _render_markdown(report_data)

    return report_data


def _render_markdown(data: dict) -> str:
    lines = []
    lines.append(f"# Brand Analytics Report: {data['source_id']}")
    lines.append(f"**Period**: {data['period_days']} days | **Generated**: {data['generated_at'][:10]}")
    lines.append("")

    ov = data.get("overview", {})
    lines.append("## Overview")
    lines.append(f"- Posts: {ov.get('total_posts', 0)}")
    lines.append(f"- Comments: {ov.get('total_comments', 0)}")
    lines.append(f"- Total reactions: {ov.get('total_reactions', 0)}")
    lines.append(f"- Total shares: {ov.get('total_shares', 0)}")
    lines.append("")

    # Sentiment
    s = data.get("sentiment", {})
    lines.append("## Sentiment")
    lines.append(f"- Positive: {s.get('positive_pct', 0)}% ({s.get('positive', 0)})")
    lines.append(f"- Negative: {s.get('negative_pct', 0)}% ({s.get('negative', 0)})")
    lines.append(f"- Neutral: {s.get('neutral', 0)}")
    lines.append(f"- Average score: {s.get('avg_score', 0)}")
    lines.append("")

    # Topics
    topics = data.get("topics", [])
    if topics:
        lines.append("## Top Topics")
        for t in topics[:10]:
            lines.append(f"- **{t['topic']}**: {t['mentions']} mentions ({t['share_pct']}%)")
        lines.append("")

    # Keywords
    kws = data.get("top_keywords", [])
    if kws:
        lines.append("## Top Keywords")
        for k in kws[:15]:
            lines.append(f"- {k['keyword']}: {k['count']}")
        lines.append("")

    # Brands
    brands = data.get("brands", [])
    if brands:
        lines.append("## Brand Performance")
        for b in brands:
            lines.append(f"### {b['brand']}")
            lines.append(f"- Mentions: {b['mentions']} (SOV: {b['share_of_voice_pct']}%)")
            bs = b.get("sentiment", {})
            lines.append(f"- Sentiment: +{bs.get('positive_pct', 0)}% / -{bs.get('negative_pct', 0)}%")
            lines.append(f"- Avg engagement: {b['avg_engagement']}")
        lines.append("")

    # Pain points
    pains = data.get("pain_points", [])
    if pains:
        lines.append("## Pain Points")
        for p in pains:
            lines.append(f"- **{p['label']}**: {p['mentions']} mentions ({p['severity_pct']}%)")
        lines.append("")

    # Trends
    tr = data.get("trends", {})
    rising = tr.get("rising_keywords", [])
    if rising:
        lines.append("## Rising Keywords")
        for r in rising[:10]:
            lines.append(f"- **{r['keyword']}**: {r['recent']} (was {r['previous']}, +{r['change_pct']}%)")
        lines.append("")

    # Top posts
    top = tr.get("top_posts", [])
    if top:
        lines.append("## Top Engagement Posts")
        for i, p in enumerate(top[:5], 1):
            lines.append(f"{i}. [{p['preview'][:80]}...]({p.get('post_url', '')})")
            lines.append(f"   Reactions: {p['reactions']} | Comments: {p['comments']} | Shares: {p['shares']}")
        lines.append("")

    # Influencers
    infs = data.get("top_influencers", [])
    if infs:
        lines.append("## Top Influencers")
        for inf in infs[:5]:
            lines.append(f"- **{inf['display_name']}** ({inf['tier']}) — {inf['follower_count']} followers, score: {inf['influence_score']}")
        lines.append("")

    return "\n".join(lines)
