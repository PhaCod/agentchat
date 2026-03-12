"""
main.py — CLI entry point for Facebook Group Post Analyzer.

Commands:
  scrape   – Scrape posts from a group
  analyze  – Analyze stored posts
  report   – Generate a specific sub-report
  export   – Export posts to CSV
  full     – Scrape + analyze in one shot
  list     – List all stored groups

All commands support --output json for machine-readable output (agent tool interface).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Windows console encoding fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Bootstrap config
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent


def _load_config() -> dict:
    from load_config import load_config
    return load_config()


def _out(data: dict | list, output_format: str):
    """Print result — JSON for agents, pretty text for humans."""
    if output_format == "json":
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        # Write UTF-8 bytes directly to avoid Windows cp1252 re-encoding
        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf:
                buf.write(raw.encode("utf-8"))
                buf.write(b"\n")
                buf.flush()
            else:
                sys.stdout.write(raw + "\n")
                sys.stdout.flush()
        except Exception:
            sys.stdout.write(raw + "\n")
    else:
        _pretty(data)


def _pretty(data, indent=0):
    pad = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                _pretty(v, indent + 1)
            else:
                print(f"{pad}{k}: {v}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                print(f"{pad}[{i}]")
                _pretty(item, indent + 1)
            else:
                print(f"{pad}- {item}")
    else:
        print(f"{pad}{data}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scrape(args, cfg):
    from post_scraper import GroupPostScraper
    import storage

    # Allow overriding days_back and max_posts via CLI
    if args.days:
        cfg.setdefault("scraper", {})["days_back"] = args.days
    if args.max_posts:
        cfg.setdefault("scraper", {})["max_posts"] = args.max_posts

    scraper = GroupPostScraper(cfg)

    posts = scraper.scrape(args.group)
    if not posts:
        result = {"status": "error", "message": "No posts collected."}
        _out(result, args.output)
        sys.exit(1)

    group_id = scraper._extract_group_id(args.group)
    path = storage.save_posts(group_id, posts)
    result = {
        "status": "ok",
        "group_id": group_id,
        "new_posts": len(posts),
        "saved_to": str(path),
    }
    _out(result, args.output)
    return group_id, posts


def cmd_analyze(args, cfg):
    from analyzer import GroupAnalyzer
    import storage

    group_id = args.group
    posts = storage.load_posts(group_id)
    if not posts:
        _out({"status": "error", "message": f"No posts found for group '{group_id}'. Run scrape first."}, args.output)
        sys.exit(1)

    analyzer = GroupAnalyzer(cfg)
    report = analyzer.analyze(posts, group_id)
    storage.save_report(group_id, report)
    _out(report, args.output)
    return report


def cmd_report(args, cfg):
    import storage

    report = storage.load_report(args.group)
    if not report:
        _out({"status": "error", "message": f"No analysis found for '{args.group}'. Run analyze first."}, args.output)
        sys.exit(1)

    rtype = args.type or "full"
    if rtype == "full":
        _out(report, args.output)
    elif rtype == "engagement":
        _out(report.get("engagement", {}), args.output)
    elif rtype == "trends":
        _out(report.get("trends", {}), args.output)
    elif rtype == "sentiment":
        _out(report.get("sentiment", {}), args.output)
    elif rtype == "topics":
        _out(report.get("topics", []), args.output)
    elif rtype == "keywords":
        _out(report.get("top_keywords", []), args.output)
    elif rtype == "spam":
        _out({
            "spam_posts_count": report.get("spam_posts_count", 0),
            "spam_post_ids": report.get("spam_post_ids", []),
        }, args.output)
    elif rtype == "summary":
        # Human-friendly summary
        eng = report.get("engagement", {})
        sen = report.get("sentiment", {})
        topics = report.get("topics", [])
        top_topic = topics[0] if topics else {}
        _out({
            "group_id": report.get("group_id"),
            "total_posts": report.get("total_posts"),
            "posts_with_content": report.get("posts_with_content"),
            "posts_excluded_from_text_analysis": report.get("posts_excluded_from_text_analysis"),
            "date_range": report.get("date_range"),
            "sentiment_summary": sen.get("distribution_pct", {}),
            "top_topic": top_topic,
            "avg_reactions": eng.get("avg_reactions"),
            "avg_comments": eng.get("avg_comments"),
            "top_post_preview": eng.get("top_posts", [{}])[0].get("content_preview", "") if eng.get("top_posts") else "",
            "rising_keywords": report.get("trends", {}).get("rising_keywords", [])[:5],
            "spam_posts": report.get("spam_posts_count", 0),
        }, args.output)
    else:
        _out({"status": "error", "message": f"Unknown report type '{rtype}'. Options: full, engagement, trends, sentiment, topics, keywords, spam, summary"}, args.output)
        sys.exit(1)


def cmd_export(args, cfg):
    import storage

    group_id = args.group
    posts = storage.load_posts(group_id)
    if not posts:
        _out({"status": "error", "message": f"No posts found for '{group_id}'."}, args.output)
        sys.exit(1)

    path = storage.export_csv(group_id, posts)
    _out({"status": "ok", "group_id": group_id, "post_count": len(posts), "file": str(path)}, args.output)


def cmd_full(args, cfg):
    """Scrape + analyze in one shot."""
    from analyzer import GroupAnalyzer
    import storage
    from post_scraper import GroupPostScraper

    if args.days:
        cfg.setdefault("scraper", {})["days_back"] = args.days
    if hasattr(args, "max_posts") and args.max_posts:
        cfg.setdefault("scraper", {})["max_posts"] = args.max_posts

    scraper = GroupPostScraper(cfg)
    group_id = scraper._extract_group_id(args.group)

    # Start run log (data lineage)
    run_id = storage.start_run(
        group_id=group_id,
        group_url=args.group,
        trigger="manual",
        settings={
            "days_back": cfg.get("scraper", {}).get("days_back", 30),
            "max_posts": cfg.get("scraper", {}).get("max_posts", 500),
        },
    )

    posts = []
    errors: list[str] = []
    try:
        posts = scraper.scrape(args.group, run_id=run_id)
    except Exception as e:
        errors.append(str(e))
        storage.finish_run(run_id, status="error", errors=errors)
        _out({"status": "error", "message": str(e)}, args.output)
        sys.exit(1)

    if not posts:
        storage.finish_run(run_id, posts_scraped=0, posts_saved=0, status="empty")
        _out({"status": "error", "message": "No posts collected."}, args.output)
        sys.exit(1)

    storage.save_posts(group_id, posts, run_id=run_id)

    # Analyze all stored posts (including previously scraped)
    all_posts = storage.load_posts(group_id)
    analyzer = GroupAnalyzer(cfg)
    report = analyzer.analyze(all_posts, group_id)
    storage.save_report(group_id, report)

    storage.finish_run(run_id, posts_scraped=len(posts), posts_saved=len(all_posts), status="success")
    _out(report, args.output)


def cmd_list(args, cfg):
    import storage
    groups = storage.list_groups()
    if not groups:
        _out({"status": "ok", "groups": []}, args.output)
        return
    result = [storage.group_stats(g) for g in groups]
    _out(result, args.output)


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Facebook Group Post Analyzer — OpenClaw Skill",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Scrape posts from a Facebook group")
    p_scrape.add_argument("--group", required=True, help="Group URL or group_id")
    p_scrape.add_argument("--days", type=int, help="Days back to scrape (default: from config)")
    p_scrape.add_argument("--max-posts", dest="max_posts", type=int, help="Max posts to collect")
    p_scrape.add_argument("--output", default="text", choices=["text", "json"])

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze stored posts for a group")
    p_analyze.add_argument("--group", required=True, help="group_id (as stored)")
    p_analyze.add_argument("--output", default="text", choices=["text", "json"])

    # report
    p_report = sub.add_parser("report", help="Print a specific sub-report")
    p_report.add_argument("--group", required=True)
    p_report.add_argument("--type", default="summary",
                          choices=["full", "engagement", "trends", "sentiment", "topics", "keywords", "spam", "summary"])
    p_report.add_argument("--output", default="text", choices=["text", "json"])

    # export
    p_export = sub.add_parser("export", help="Export posts to CSV")
    p_export.add_argument("--group", required=True)
    p_export.add_argument("--format", default="csv", choices=["csv"])
    p_export.add_argument("--output", default="text", choices=["text", "json"])

    # full
    p_full = sub.add_parser("full", help="Scrape + analyze + report in one shot")
    p_full.add_argument("--group", required=True, help="Group URL")
    p_full.add_argument("--days", type=int)
    p_full.add_argument("--max-posts", dest="max_posts", type=int)
    p_full.add_argument("--output", default="text", choices=["text", "json"])

    # list
    p_list = sub.add_parser("list", help="List all stored groups")
    p_list.add_argument("--output", default="text", choices=["text", "json"])

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    cfg = _load_config()

    dispatch = {
        "scrape": cmd_scrape,
        "analyze": cmd_analyze,
        "report": cmd_report,
        "export": cmd_export,
        "full": cmd_full,
        "list": cmd_list,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args, cfg)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
