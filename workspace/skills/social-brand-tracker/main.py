"""
main.py — CLI entry point for social-brand-tracker skill.

Commands: scrape, analyze, brand, trends, pain-points, influencers, report
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).parent


def _load_config() -> dict:
    from load_config import load_config
    return load_config()


def _out(data, fmt: str = "text") -> None:
    if fmt == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)


def _extract_source_id(url: str) -> str:
    m = re.search(r"groups/([^/?#]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"facebook\.com/([^/?#]+)", url)
    if m:
        return m.group(1)
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", url)[-40:]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scrape(args, cfg):
    """Crawl posts + comments from a Facebook source."""
    import db
    from scraper import BrandScraper

    db.init_db()
    scraper = BrandScraper(cfg)

    source_url = args.source
    source_id = _extract_source_id(source_url)
    source_type = "page" if args.page else "group"

    if args.max_posts:
        scraper.max_posts = args.max_posts
    if args.days:
        scraper.days_back = args.days

    result = scraper.scrape(
        source_url,
        source_type=source_type,
        with_comments=args.with_comments,
        max_comments=args.max_comments,
    )

    for p in result["posts"]:
        p["source_id"] = source_id
        p["source_type"] = source_type
    post_stats = db.upsert_posts(result["posts"])

    comment_stats = {"inserted": 0, "skipped": 0}
    if result.get("comments"):
        comment_stats = db.upsert_comments(result["comments"])

    # Extract and store hashtags/mentions
    from text_analysis import extract_hashtags, extract_mentions
    all_texts = [(p.get("content", ""), p["post_id"], None, source_id, p.get("posted_at", ""))
                 for p in result["posts"]]
    all_texts += [(c.get("content", ""), c.get("post_id", ""), c["comment_id"], source_id, c.get("posted_at", ""))
                  for c in result.get("comments", [])]

    hashtag_records, mention_records = [], []
    brands_cfg = cfg.get("brands", [])
    for text, pid, cid, sid, ts in all_texts:
        hashtag_records.extend(extract_hashtags(text, post_id=pid, comment_id=cid,
                                                source_id=sid, posted_at=ts))
        mention_records.extend(extract_mentions(text, brands=brands_cfg,
                                                post_id=pid, comment_id=cid,
                                                source_id=sid, posted_at=ts))

    ht_count = db.insert_hashtags(hashtag_records)
    mt_count = db.insert_mentions(mention_records)

    # Upsert user records
    for p in result["posts"]:
        if p.get("author_id"):
            db.upsert_user({
                "user_id": p["author_id"],
                "display_name": p.get("author_name", ""),
                "total_posts": 1, "total_comments": 0,
            })
    for c in result.get("comments", []):
        if c.get("commenter_id"):
            db.upsert_user({
                "user_id": c["commenter_id"],
                "display_name": c.get("commenter_name", ""),
                "total_posts": 0, "total_comments": 1,
            })

    out = {
        "status": "ok",
        "source_id": source_id,
        "source_type": source_type,
        "posts_scraped": len(result["posts"]),
        "posts_inserted": post_stats["inserted"],
        "comments_scraped": len(result.get("comments", [])),
        "comments_inserted": comment_stats["inserted"],
        "hashtags_stored": ht_count,
        "mentions_stored": mt_count,
        "total_posts_in_db": db.count_posts(source_id),
    }
    _out(out, args.output)


def cmd_analyze(args, cfg):
    """Full analysis pipeline on stored data."""
    import db
    from text_analysis import analyze_sentiment_batch, extract_keywords, cluster_topics
    from brand_tracker import analyze_brands
    from pain_detector import detect_pain_points
    from trend_detector import detect_trends
    from influencer import score_influencers

    db.init_db()
    source_id = _extract_source_id(args.source)
    days = args.days

    posts = db.get_posts(source_id, days=days)
    comments = db.get_comments(source_id=source_id, days=days)

    if not posts:
        _out({"status": "no_data", "message": f"No posts found for {source_id} in {days} days"}, args.output)
        return

    post_texts = [p["content"] for p in posts if p.get("content")]
    comment_texts = [c["content"] for c in comments if c.get("content")]
    all_texts = post_texts + comment_texts

    sentiment = analyze_sentiment_batch(all_texts)
    keywords = extract_keywords(all_texts, min_freq=cfg.get("analysis", {}).get("min_keyword_freq", 3))
    topics = cluster_topics(all_texts)
    brands = analyze_brands(posts, comments, cfg.get("brands", []))
    pains = detect_pain_points(comment_texts + post_texts)
    trends = detect_trends(posts, days=days, window_hours=cfg.get("analysis", {}).get("trend_window_hours", 24))
    influencer_list = score_influencers(source_id, threshold=cfg.get("analysis", {}).get("influencer_threshold", 10000))

    from datetime import datetime, timezone
    run_id = f"analyze_{source_id}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    results = {
        "source_id": source_id,
        "days": days,
        "total_posts": len(posts),
        "total_comments": len(comments),
        "sentiment": sentiment,
        "top_keywords": keywords[:20],
        "topics": topics[:10],
        "brands": brands,
        "pain_points": pains[:15],
        "trends": trends,
        "top_influencers": influencer_list[:10],
    }

    db.save_analysis_run(run_id, source_id, "full", {"days": days}, results)
    _out({"status": "ok", "run_id": run_id, **results}, args.output)


def cmd_brand(args, cfg):
    """Brand mention analysis."""
    import db
    from brand_tracker import analyze_brands

    db.init_db()
    source_id = _extract_source_id(args.source)
    posts = db.get_posts(source_id, days=args.days)
    comments = db.get_comments(source_id=source_id, days=args.days)

    brands_cfg = cfg.get("brands", [])
    if args.brands:
        brand_names = [b.strip() for b in args.brands.split(",")]
        brands_cfg = [b for b in brands_cfg if b["name"] in brand_names]
        for name in brand_names:
            if not any(b["name"] == name for b in brands_cfg):
                brands_cfg.append({"name": name, "aliases": [], "keywords": [name.lower()]})

    results = analyze_brands(posts, comments, brands_cfg)
    _out({"status": "ok", "source_id": source_id, "days": args.days, "brands": results}, args.output)


def cmd_trends(args, cfg):
    """Trend detection."""
    import db
    from trend_detector import detect_trends

    db.init_db()
    source_id = _extract_source_id(args.source)
    posts = db.get_posts(source_id, days=args.days)

    window = cfg.get("analysis", {}).get("trend_window_hours", 24)
    results = detect_trends(posts, days=args.days, window_hours=window)
    _out({"status": "ok", "source_id": source_id, "days": args.days, "trends": results}, args.output)


def cmd_pain_points(args, cfg):
    """Pain point detection."""
    import db
    from pain_detector import detect_pain_points

    db.init_db()
    source_id = _extract_source_id(args.source)
    posts = db.get_posts(source_id, days=args.days)
    comments = db.get_comments(source_id=source_id, days=args.days)

    texts = [p["content"] for p in posts if p.get("content")]
    texts += [c["content"] for c in comments if c.get("content")]

    if args.brand:
        texts = [t for t in texts if args.brand.lower() in t.lower()]

    results = detect_pain_points(texts)
    _out({"status": "ok", "source_id": source_id, "brand": args.brand,
          "days": args.days, "pain_points": results}, args.output)


def cmd_influencers(args, cfg):
    """Top influencers."""
    import db
    from influencer import score_influencers

    db.init_db()
    source_id = _extract_source_id(args.source)
    threshold = args.min_followers or cfg.get("analysis", {}).get("influencer_threshold", 10000)
    results = score_influencers(source_id, threshold=threshold)
    _out({"status": "ok", "source_id": source_id, "influencers": results}, args.output)


def cmd_report(args, cfg):
    """Generate full brand analytics report."""
    import db
    from report_generator import generate_report

    db.init_db()
    source_id = _extract_source_id(args.source)
    report = generate_report(source_id, days=args.days, cfg=cfg, fmt=args.format)
    _out(report, args.output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="social-brand-tracker",
                                description="Social Brand Tracker — Facebook analytics pipeline")
    sub = p.add_subparsers(dest="command")

    # scrape
    s = sub.add_parser("scrape", help="Crawl posts + comments from Facebook")
    s.add_argument("--source", required=True, help="Facebook group/page URL or ID")
    s.add_argument("--max-posts", type=int, default=None)
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--with-comments", action="store_true", help="Also crawl comments")
    s.add_argument("--max-comments", type=int, default=30, help="Max comments per post")
    s.add_argument("--page", action="store_true", help="Source is a page (not group)")
    s.add_argument("--output", choices=["text", "json"], default="json")

    # analyze
    a = sub.add_parser("analyze", help="Full analysis pipeline")
    a.add_argument("--source", required=True)
    a.add_argument("--days", type=int, default=7)
    a.add_argument("--output", choices=["text", "json"], default="json")

    # brand
    b = sub.add_parser("brand", help="Brand mention analysis")
    b.add_argument("--source", required=True)
    b.add_argument("--brands", type=str, help="Comma-separated brand names")
    b.add_argument("--days", type=int, default=7)
    b.add_argument("--output", choices=["text", "json"], default="json")

    # trends
    t = sub.add_parser("trends", help="Trend detection")
    t.add_argument("--source", required=True)
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--output", choices=["text", "json"], default="json")

    # pain-points
    pp = sub.add_parser("pain-points", help="Pain point detection")
    pp.add_argument("--source", required=True)
    pp.add_argument("--brand", type=str, default=None)
    pp.add_argument("--days", type=int, default=7)
    pp.add_argument("--output", choices=["text", "json"], default="json")

    # influencers
    inf = sub.add_parser("influencers", help="Top influencers")
    inf.add_argument("--source", required=True)
    inf.add_argument("--min-followers", type=int, default=None)
    inf.add_argument("--output", choices=["text", "json"], default="json")

    # report
    r = sub.add_parser("report", help="Generate full report")
    r.add_argument("--source", required=True)
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--format", choices=["json", "md"], default="json")
    r.add_argument("--output", choices=["text", "json"], default="json")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cfg = _load_config()

    commands = {
        "scrape": cmd_scrape,
        "analyze": cmd_analyze,
        "brand": cmd_brand,
        "trends": cmd_trends,
        "pain-points": cmd_pain_points,
        "influencers": cmd_influencers,
        "report": cmd_report,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args, cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
