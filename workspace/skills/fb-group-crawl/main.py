"""
main.py — CLI entry point for fb-group-crawl skill.

Commands:
  scrape   Crawl posts from a Facebook group → SQLite
  ask      Query the database with natural language → AI answer
  stats    Show group statistics
  search   Full-text search posts
  market   Fast marketplace search (no LLM)
  rag-build Build a per-question RAG batch (FTS + metadata)
  rag-ask   Query a saved RAG batch (no re-crawl)
  rag-query RAG ask with auto-crawl fallback (max 20)
  export   Export posts to CSV
  groups   List tracked groups
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

# Fix Windows cp1252 encoding for Vietnamese output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).parent


def _load_config() -> dict:
    from load_config import load_config
    return load_config()


def _out(data, fmt: str = "text") -> None:
    """Print output in text or json format."""
    if fmt == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                print(f"\n{k}:")
                for kk, vv in v.items():
                    print(f"  {kk}: {vv}")
            elif isinstance(v, list):
                print(f"\n{k}: ({len(v)} items)")
                for item in v[:10]:
                    if isinstance(item, dict):
                        preview = item.get("preview") or item.get("content", "")
                        print(f"  - {preview[:100]}")
                    else:
                        print(f"  - {item}")
                if len(v) > 10:
                    print(f"  ... and {len(v) - 10} more")
            else:
                print(f"{k}: {v}")
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scrape(args, cfg):
    """Scrape posts from a Facebook group and store in SQLite."""
    import db

    db.init_db()

    if getattr(args, "vision", False):
        from vision_scraper import VisionGroupScraper
        scraper = VisionGroupScraper(cfg)
    else:
        from scraper import GroupPostScraper
        scraper = GroupPostScraper(cfg)
    group_url = args.group

    # Override config from CLI args
    if args.days:
        scraper.days_back = args.days
    if args.max_posts:
        scraper.max_posts = args.max_posts

    # Normalize URL before group_id extraction so bare IDs like "riviu.official"
    # don't get their dots replaced by fallback regex sanitization
    _norm_url = group_url if ("http" in group_url or "facebook.com" in group_url) \
        else f"https://www.facebook.com/groups/{group_url.strip()}"
    group_id = scraper._extract_group_id(_norm_url)

    # Incremental: get cursor
    cursor = db.get_group_cursor(group_id)
    if cursor and not args.full_rescrape:
        print(f"Incremental mode: will stop at post_id={cursor}")

    stats = _scrape_to_db(
        cfg,
        group_url=group_url,
        days=args.days,
        max_posts=args.max_posts,
        full_rescrape=args.full_rescrape,
        vision=getattr(args, "vision", False),
        group_id_override=group_id,
    )
    _out(stats, args.output)


def _scrape_to_db(
    cfg: dict,
    *,
    group_url: str,
    days: int | None,
    max_posts: int | None,
    full_rescrape: bool,
    vision: bool,
    group_id_override: str | None = None,
) -> dict:
    """Internal helper: scrape + write to fb_posts.db, return stats dict (no printing)."""
    import db

    db.init_db()

    if vision:
        from vision_scraper import VisionGroupScraper
        scraper = VisionGroupScraper(cfg)
    else:
        from scraper import GroupPostScraper
        scraper = GroupPostScraper(cfg)

    if days:
        scraper.days_back = days
    if max_posts:
        scraper.max_posts = max_posts

    _norm_url = group_url if ("http" in group_url or "facebook.com" in group_url) \
        else f"https://www.facebook.com/groups/{group_url.strip()}"
    group_id = group_id_override or scraper._extract_group_id(_norm_url)

    cursor = db.get_group_cursor(group_id)
    posts = scraper.scrape(
        group_url,
        stop_at_post_id=cursor if (cursor and not full_rescrape) else None,
    )

    if not posts:
        return {
            "status": "ok",
            "group_id": group_id,
            "message": "No new posts found.",
            "total_in_db": db.count_posts(group_id),
        }

    db.upsert_group(group_id, group_url)
    result = db.upsert_posts(posts)
    newest = posts[0] if posts else None
    if newest:
        db.update_group_after_scrape(group_id, newest.get("post_id"))

    total = db.count_posts(group_id)
    return {
        "status": "ok",
        "group_id": group_id,
        "scraped": len(posts),
        "inserted": result["inserted"],
        "skipped_duplicates": result["skipped"],
        "total_in_db": total,
    }


def cmd_ask(args, cfg):
    """Ask a natural language question about a group's posts."""
    import db
    from ai_query import ask

    db.init_db()
    group_id = args.group
    question = args.question

    if not question:
        print("Error: --question is required")
        sys.exit(1)

    total = db.count_posts(group_id)
    if total == 0:
        _out({"error": f"No posts in database for group '{group_id}'. Run scrape first."}, args.output)
        sys.exit(1)

    result = ask(group_id, question, cfg)

    if args.output == "json":
        _out(result, "json")
    else:
        print(f"\n{'='*60}")
        print(f"Group: {group_id} | Posts used: {result['posts_used']}", end="")
        if result.get("time_window_days"):
            print(f" | Window: {result['time_window_days']} days")
        else:
            print()
        print(f"{'='*60}\n")
        print(result["answer"])
        print()


def cmd_stats(args, cfg):
    """Show statistics for a group."""
    import db

    db.init_db()
    stats = db.get_stats(args.group)
    _out(stats, args.output)


def cmd_search(args, cfg):
    """Full-text search posts in a group."""
    import db

    db.init_db()
    posts = db.search_posts(args.group, args.keyword, limit=args.limit)

    if args.output == "json":
        _out(posts, "json")
    else:
        print(f"\nFound {len(posts)} posts matching '{args.keyword}':\n")
        for i, p in enumerate(posts, 1):
            content = (p.get("content") or "")[:150]
            posted = p.get("posted_at") or ""
            author = p.get("author") or "?"
            reactions = p.get("reactions", {}).get("total", 0)
            print(f"  [{i}] {posted[:16]} | {author} | react:{reactions}")
            print(f"      {content}")
            print()


def cmd_market(args, cfg):
    """Fast marketplace search with query expansion + price extraction (no LLM)."""
    import db
    from market_reasoner import build_market_query, extract_price_vnd, load_cache, save_cache
    from datetime import datetime, timedelta, timezone

    db.init_db()
    group_id = args.group
    q = args.query
    days = args.days or 7
    limit = args.limit or 10

    mq = build_market_query(group_id=group_id, query=q, days=days)

    cached = load_cache(mq, ttl_minutes=args.cache_ttl)
    if cached and not args.no_cache:
        _out(cached, args.output)
        return

    from_date = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()

    # Search multiple keywords (FTS), merge by post_id
    by_id: dict[str, dict] = {}
    for kw in mq.keywords:
        try:
            hits = db.search_posts(group_id, kw, limit=args.per_kw_limit)
        except Exception:
            hits = []
        for p in hits:
            pid = p.get("post_id") or ""
            if pid and pid not in by_id:
                by_id[pid] = p

    # If still too few, supplement with recent posts (helps when FTS misses)
    if len(by_id) < max(limit, 20):
        recent = db.get_posts(group_id, from_date=from_date, limit=max(limit, 50))
        for p in recent:
            pid = p.get("post_id") or ""
            if pid and pid not in by_id:
                by_id[pid] = p

    def _is_iso_dt(s: str) -> bool:
        if not s:
            return False
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}T", s))

    def _relevance_score(text: str) -> int:
        t = (text or "").lower()
        # score by must_any hits (domain) + sell intent signals + query tokens
        score = 0
        if mq.must_any:
            score += sum(1 for w in mq.must_any if w in t)
        # cheap/sell intent signals
        for w in ("bán", "pass", "thanh lý", "fix", "giá", "inbox", "ib"):
            if w in t:
                score += 1
        return score

    results = []
    for p in by_id.values():
        content = p.get("content") or ""
        price = extract_price_vnd(content)
        # Domain gate: if we inferred a domain, require at least 1 domain term hit.
        if mq.must_any:
            t = content.lower()
            if not any(w in t for w in mq.must_any):
                continue
        if mq.max_price_vnd is not None and price is not None and price > mq.max_price_vnd:
            continue
        posted_raw = p.get("posted_at") or ""
        posted_at = posted_raw if _is_iso_dt(posted_raw) else (p.get("scraped_at") or "")
        results.append({
            "post_id": p.get("post_id"),
            "posted_at": posted_at,
            "author": p.get("author") or "",
            "price_vnd": price,
            "reactions": (p.get("reactions") or {}).get("total", 0),
            "comments_count": p.get("comments_count", 0),
            "post_url": p.get("post_url") or "",
            "preview": (content[:200] if content else ""),
        })

    # Rank: known price first (lowest), then engagement
    def _rank_key(r: dict):
        price = r.get("price_vnd")
        return (
            0 if price is not None else 1,
            price if price is not None else 10**18,
            -(r.get("reactions") or 0),
        )

    results.sort(key=_rank_key)
    results = results[:limit]

    payload = {
        "status": "ok",
        "group_id": group_id,
        "query": q,
        "days": days,
        "max_price_vnd": mq.max_price_vnd,
        "keywords_used": mq.keywords,
        "domain_must_any": mq.must_any,
        "matches": results,
        "note": "Fast search (FTS+heuristics, no LLM). If sparse, scrape more then retry.",
    }
    save_cache(mq, payload)
    _out(payload, args.output)


def cmd_rag_build(args, cfg):
    """Build a per-question RAG batch from existing DB posts."""
    from rag_pipeline import build_batch
    result = build_batch(
        group_id=args.group,
        query=args.query,
        days=args.days,
        max_posts=args.max_posts,
        batch_id=getattr(args, "batch_id", None),
    )
    _out(result, args.output)


def cmd_rag_ask(args, cfg):
    """Query a saved RAG batch (FTS+metadata)."""
    from rag_pipeline import ask_batch
    result = ask_batch(
        group_id=args.group,
        query=args.query,
        batch_id=getattr(args, "batch_id", None),
        limit=args.limit,
    )
    _out(result, args.output)


def _ensure_chronological(url_or_id: str) -> str:
    u = (url_or_id or "").strip()
    if not u:
        return u
    if "http" not in u and "facebook.com" not in u:
        u = f"https://www.facebook.com/groups/{u}"
    if "sorting_setting=CHRONOLOGICAL" in u:
        return u
    join = "&" if "?" in u else "?"
    return u + f"{join}sorting_setting=CHRONOLOGICAL"


def cmd_rag_query(args, cfg):
    """RAG query with fallback: if no matching batch, auto-crawl max 20 newest posts then build batch."""
    import db
    import rag_db
    from rag_pipeline import build_batch, ask_batch
    from ai_query import _detect_time_window
    from datetime import datetime, timedelta, timezone

    db.init_db()
    rag_db.init_rag_db()

    group_input = args.group
    q = args.query

    # Determine group_id (stored id) without crawling when possible
    group_url = _ensure_chronological(group_input)
    try:
        from scraper import GroupPostScraper
        scraper = GroupPostScraper(cfg)
        group_id = scraper._extract_group_id(group_url)
    except Exception:
        group_id = group_input

    # 1) Try reuse a matching batch (normalized equality) within TTL
    match = rag_db.find_matching_batch(group_id, q, ttl_hours=args.batch_ttl_hours, scan_limit=100)
    if match:
        res = ask_batch(group_id=group_id, query=q, batch_id=match["batch_id"], limit=args.limit)
        res["reused_batch"] = True
        _out(res, args.output)
        return

    # 2) No batch: decide analysis window from question; if none, use default
    days_question = _detect_time_window(q)
    if not days_question:
        days_question = args.default_days_if_missing

    # DB-first coverage check: if we already have enough posts in the analysis window,
    # do not crawl (avoid wasting time/tokens).
    from_date_question = (datetime.now(tz=timezone.utc) - timedelta(days=int(days_question))).isoformat()
    existing_in_window = db.count_posts_window(group_id, from_date=from_date_question)
    should_crawl = (not args.no_crawl) and (existing_in_window < int(args.min_db_posts))

    # Crawl window is capped for efficiency (newest-first). Analysis window remains days_question.
    days_crawl = min(int(days_question), int(args.max_crawl_days))

    # 3) Auto-crawl max N newest posts (no printing), only if DB coverage is low
    scrape_stats = None
    if should_crawl:
        scrape_stats = _scrape_to_db(
            cfg,
            group_url=group_url,
            days=int(days_crawl),
            max_posts=int(args.crawl_max_posts),
            full_rescrape=False,
            vision=False,
            group_id_override=group_id,
        )

    # 4) Build batch from DB analysis window then ask
    build = build_batch(
        group_id=group_id,
        query=q,
        days=int(days_question),
        max_posts=int(args.crawl_max_posts),
        batch_id=None,
    )
    if build.get("status") != "ok":
        _out(build, args.output)
        return

    res = ask_batch(group_id=group_id, query=q, batch_id=build["batch_id"], limit=args.limit)
    res["reused_batch"] = False
    res["built_batch"] = build
    res["time_policy"] = {
        "days_question": int(days_question),
        "days_crawl": int(days_crawl),
        "min_db_posts": int(args.min_db_posts),
        "existing_posts_in_window": int(existing_in_window),
        "did_crawl": bool(should_crawl),
    }
    if scrape_stats:
        res["scrape"] = scrape_stats
    _out(res, args.output)

def cmd_export(args, cfg):
    """Export posts to CSV."""
    import db

    db.init_db()
    try:
        path = db.export_csv(
            args.group,
            from_date=getattr(args, "from_date", None),
            to_date=getattr(args, "to_date", None),
        )
        total = db.count_posts(args.group)
        _out({
            "status": "ok",
            "group_id": args.group,
            "total_posts": total,
            "file": str(path),
        }, args.output)
    except ValueError as e:
        _out({"status": "error", "message": str(e)}, args.output)
        sys.exit(1)


def cmd_groups(args, cfg):
    """List all tracked groups."""
    import db

    db.init_db()
    groups = db.list_groups()
    if args.output == "json":
        _out(groups, "json")
    else:
        if not groups:
            print("No groups tracked yet. Run 'scrape' to add a group.")
            return
        print(f"\n{'Group ID':<30} {'Posts':>6} {'Last Scraped':<20}")
        print("-" * 60)
        for g in groups:
            print(f"{g['group_id']:<30} {g['total_posts']:>6} {(g.get('last_scraped_at') or 'never')[:19]:<20}")
        print()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fb-group-crawl",
        description="Crawl Facebook group posts → SQLite → AI query",
    )
    sub = parser.add_subparsers(dest="command")

    # scrape
    p_scrape = sub.add_parser("scrape", help="Crawl posts from a Facebook group")
    p_scrape.add_argument("--group", required=True, help="Group URL or ID")
    p_scrape.add_argument("--days", type=int, help="Days back to scrape")
    p_scrape.add_argument("--max-posts", type=int, help="Max posts to collect")
    p_scrape.add_argument("--full-rescrape", action="store_true", help="Ignore cursor, rescrape all")
    p_scrape.add_argument("--vision", action="store_true", help="Use Gemini Vision AI for extraction instead of DOM parsing")
    p_scrape.add_argument("--output", default="text", choices=["text", "json"])

    # ask
    p_ask = sub.add_parser("ask", help="Ask AI about group posts")
    p_ask.add_argument("--group", required=True, help="Group ID")
    p_ask.add_argument("--question", "-q", required=True, help="Your question")
    p_ask.add_argument("--output", default="text", choices=["text", "json"])

    # stats
    p_stats = sub.add_parser("stats", help="Show group statistics")
    p_stats.add_argument("--group", required=True)
    p_stats.add_argument("--output", default="text", choices=["text", "json"])

    # search
    p_search = sub.add_parser("search", help="Full-text search posts")
    p_search.add_argument("--group", required=True)
    p_search.add_argument("--keyword", "-k", required=True)
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--output", default="text", choices=["text", "json"])

    # market
    p_market = sub.add_parser("market", help="Fast marketplace search (no LLM)")
    p_market.add_argument("--group", required=True)
    p_market.add_argument("--query", "-q", required=True, help="Broad query, e.g. 'xe thật chiến giá rẻ dưới 10tr'")
    p_market.add_argument("--days", type=int, default=7, help="Days back window (default: 7)")
    p_market.add_argument("--limit", type=int, default=10, help="Max results to return")
    p_market.add_argument("--per-kw-limit", dest="per_kw_limit", type=int, default=30, help="FTS limit per expanded keyword")
    p_market.add_argument("--cache-ttl", dest="cache_ttl", type=int, default=30, help="Cache TTL minutes")
    p_market.add_argument("--no-cache", action="store_true", help="Disable cache")
    p_market.add_argument("--output", default="text", choices=["text", "json"])

    # export
    p_export = sub.add_parser("export", help="Export posts to CSV")
    p_export.add_argument("--group", required=True)
    p_export.add_argument("--from-date", dest="from_date", help="Start date (ISO)")
    p_export.add_argument("--to-date", dest="to_date", help="End date (ISO)")
    p_export.add_argument("--output", default="text", choices=["text", "json"])

    # groups
    p_groups = sub.add_parser("groups", help="List tracked groups")
    p_groups.add_argument("--output", default="text", choices=["text", "json"])

    # rag-build
    p_rb = sub.add_parser("rag-build", help="Build a per-question RAG batch (no re-crawl)")
    p_rb.add_argument("--group", required=True, help="Group ID (must already be scraped into fb_posts.db)")
    p_rb.add_argument("--query", "-q", required=True, help="Question/topic for this batch, e.g. 'iphone 17' or 'xe giá rẻ'")
    p_rb.add_argument("--days", type=int, default=7, help="Days back window to include in the batch")
    p_rb.add_argument("--max-posts", dest="max_posts", type=int, default=500, help="Max posts to include from DB window")
    p_rb.add_argument("--batch-id", dest="batch_id", help="Optional custom batch_id")
    p_rb.add_argument("--output", default="text", choices=["text", "json"])

    # rag-ask
    p_ra = sub.add_parser("rag-ask", help="Query a saved RAG batch")
    p_ra.add_argument("--group", required=True, help="Group ID")
    p_ra.add_argument("--query", "-q", required=True, help="Your question, e.g. 'tìm bài bán iphone 17 dưới 20tr'")
    p_ra.add_argument("--batch-id", dest="batch_id", help="Optional batch_id; if omitted uses latest batch for group")
    p_ra.add_argument("--limit", type=int, default=10, help="Max matches to return")
    p_ra.add_argument("--output", default="text", choices=["text", "json"])

    # rag-query
    p_rq = sub.add_parser("rag-query", help="RAG ask with auto-crawl fallback (max 20 newest-first)")
    p_rq.add_argument("--group", required=True, help="Group URL or ID")
    p_rq.add_argument("--query", "-q", required=True, help="Your question/topic")
    p_rq.add_argument("--limit", type=int, default=10)
    p_rq.add_argument("--crawl-max-posts", dest="crawl_max_posts", type=int, default=20, help="Max posts to crawl when query is new")
    p_rq.add_argument("--default-days-if-missing", dest="default_days_if_missing", type=int, default=7, help="If no time window mentioned, use this many days for analysis (default: 7)")
    p_rq.add_argument("--max-crawl-days", dest="max_crawl_days", type=int, default=7, help="Cap crawl window for efficiency (default: 7)")
    p_rq.add_argument("--min-db-posts", dest="min_db_posts", type=int, default=60, help="If DB already has >= this many posts in the analysis window, skip crawling (default: 60)")
    p_rq.add_argument("--batch-ttl-hours", dest="batch_ttl_hours", type=int, default=72, help="Reuse existing batch within TTL")
    p_rq.add_argument("--no-crawl", action="store_true", help="Don't crawl on miss; just attempt to build batch from existing DB")
    p_rq.add_argument("--output", default="text", choices=["text", "json"])

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    cfg = _load_config()

    dispatch = {
        "scrape": cmd_scrape,
        "ask": cmd_ask,
        "stats": cmd_stats,
        "search": cmd_search,
        "market": cmd_market,
        "rag-build": cmd_rag_build,
        "rag-ask": cmd_rag_ask,
        "rag-query": cmd_rag_query,
        "export": cmd_export,
        "groups": cmd_groups,
    }

    fn = dispatch.get(args.command)
    if fn:
        fn(args, cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
