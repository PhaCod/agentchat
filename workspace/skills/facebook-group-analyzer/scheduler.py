"""
scheduler.py — Objective 5: Automated periodic reporting.

Runs the full scrape+analyze pipeline on a schedule using Python's
APScheduler. Groups and schedule are defined in config/scheduled_groups.json.

Also provides NL-like preset query shortcuts for fast reporting.

Usage:
    python scheduler.py --run-now          # Run all groups once, then exit
    python scheduler.py --run-now --group 1125804114216204  # Single group
    python scheduler.py                    # Start scheduler loop

Config: config/scheduled_groups.json
    {
      "groups": [
        {
          "id": "riviu.official",
          "url": "https://www.facebook.com/groups/riviu.official",
          "days_back": 7,
          "max_posts": 500,
          "enabled": true
        }
      ],
      "defaults": { "days_back": 7, "max_posts": 500 }
    }
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_log = logging.getLogger(__name__)
_HERE = Path(__file__).parent
_SCHEDULED_GROUPS_PATH = _HERE / "config" / "scheduled_groups.json"

# ---------------------------------------------------------------------------
# NL-like preset queries
# ---------------------------------------------------------------------------

NL_PRESETS: dict[str, dict] = {
    "hot leads": {
        "description": "Posts with immediate purchase intent (Hot tier)",
        "report_type": "leads",
        "filter": lambda r: [l for l in r.get("leads", {}).get("hot_leads", [])],
    },
    "pain points": {
        "description": "Posts expressing frustration or unmet needs",
        "report_type": "pain_points",
        "filter": lambda r: r.get("pain_points", {}).get("top_pain_posts", []),
    },
    "viral posts": {
        "description": "Posts with significantly above-average reactions",
        "report_type": "engagement",
        "filter": lambda r: r.get("engagement", {}).get("top_posts", [])[:5],
    },
    "negative posts": {
        "description": "Posts with negative sentiment (sorted by reactions)",
        "report_type": "sentiment",
        "filter": lambda r: r.get("sentiment", {}),
    },
    "competitors": {
        "description": "Competitor brand mention analysis",
        "report_type": "competitors",
        "filter": lambda r: r.get("competitors", {}),
    },
    "summary": {
        "description": "Full group summary with AI insights",
        "report_type": "summary",
        "filter": lambda r: {
            "sentiment": r.get("sentiment", {}).get("distribution_pct", {}),
            "top_topic": r.get("topics", [{}])[0] if r.get("topics") else {},
            "avg_reactions": r.get("engagement", {}).get("avg_reactions"),
            "leads": r.get("leads", {}).get("tier_breakdown", {}),
            "ai_insights": r.get("ai_insights", {}),
        },
    },
}


def run_nl_query(group_id: str, query: str) -> dict:
    """Run an NL preset query against a stored report."""
    import storage
    report = storage.load_report(group_id)
    if not report:
        return {"error": f"No report for '{group_id}'. Run analyze first."}

    query_lower = query.lower().strip()
    preset = NL_PRESETS.get(query_lower)
    if not preset:
        # Fuzzy match — find closest
        matches = [k for k in NL_PRESETS if query_lower in k or k in query_lower]
        if matches:
            preset = NL_PRESETS[matches[0]]
            query_lower = matches[0]
        else:
            return {
                "error": f"Unknown query: '{query}'",
                "available_queries": list(NL_PRESETS.keys()),
            }

    return {
        "query": query_lower,
        "group_id": group_id,
        "results": preset["filter"](report),
    }


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _load_scheduled_groups() -> list[dict]:
    if not _SCHEDULED_GROUPS_PATH.exists():
        return []
    try:
        data = json.loads(_SCHEDULED_GROUPS_PATH.read_text(encoding="utf-8"))
        defaults = data.get("defaults", {})
        groups = []
        for g in data.get("groups", []):
            if not g.get("enabled", True):
                continue
            merged = {**defaults, **g}
            groups.append(merged)
        return groups
    except Exception as exc:
        _log.error("Failed to load scheduled groups: %s", exc)
        return []


def run_group_pipeline(group_entry: dict, cfg: dict) -> dict:
    """Run full analyze pipeline for one group (no browser — uses stored posts)."""
    import storage
    from analyzer import GroupAnalyzer

    group_id = group_entry.get("id") or group_entry.get("url", "")
    if not group_id:
        return {"status": "error", "message": "Group entry missing 'id'"}

    _log.info("Scheduled run: group=%s", group_id)
    print(f"  [{datetime.now(tz=timezone.utc).strftime('%H:%M:%S')}] Processing group: {group_id}")

    posts = storage.load_posts(group_id)
    if not posts:
        return {"status": "skip", "group_id": group_id, "message": "No posts stored"}

    cached_report = storage.load_report(group_id)
    analyzer = GroupAnalyzer(cfg)
    report = analyzer.analyze_with_ai(posts, group_id, cached_report=cached_report)
    storage.save_report(group_id, report)

    result = {
        "status": "ok",
        "group_id": group_id,
        "posts_analyzed": len(posts),
        "leads": report.get("leads", {}).get("total_leads", 0),
        "pain_posts": report.get("pain_points", {}).get("total_pain_posts", 0),
        "negative_pct": report.get("sentiment", {}).get("distribution_pct", {}).get("negative", 0),
        "has_ai_insights": bool(report.get("ai_insights")),
        "report_path": str(_HERE / "data" / "reports" / f"{group_id}_analysis.json"),
    }
    print(f"    -> {len(posts)} posts | leads={result['leads']} | "
          f"pain={result['pain_posts']} | neg={result['negative_pct']}%")
    return result


def run_all_now(cfg: dict, target_group: str | None = None) -> list[dict]:
    """Run pipeline immediately for all (or one) scheduled groups."""
    groups = _load_scheduled_groups()
    if not groups:
        print("No scheduled groups found. Check config/scheduled_groups.json")
        return []

    if target_group:
        groups = [g for g in groups if g.get("id") == target_group or g.get("url") == target_group]
        if not groups:
            print(f"Group '{target_group}' not found in scheduled_groups.json")
            return []

    print(f"\nRunning pipeline for {len(groups)} group(s)...\n")
    results = []
    for g in groups:
        result = run_group_pipeline(g, cfg)
        results.append(result)

    # Summary
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"\nDone: {ok}/{len(results)} groups processed successfully.")
    return results


# ---------------------------------------------------------------------------
# APScheduler loop
# ---------------------------------------------------------------------------

def start_scheduler(cfg: dict, interval_hours: int = 6) -> None:
    """Start APScheduler for recurring pipeline runs."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("APScheduler not installed. Run: pip install apscheduler")
        print("Falling back to simple sleep loop...\n")
        import time
        while True:
            run_all_now(cfg)
            print(f"Next run in {interval_hours}h. Sleeping...\n")
            time.sleep(interval_hours * 3600)
        return

    scheduler_cfg = cfg.get("scheduler", {})
    interval = scheduler_cfg.get("interval_hours", interval_hours)

    sched = BlockingScheduler(timezone="UTC")
    groups = _load_scheduled_groups()

    if not groups:
        print("No enabled groups in scheduled_groups.json — nothing to schedule.")
        return

    def job():
        print(f"\n[Scheduler] Triggered at {datetime.now(tz=timezone.utc).isoformat()}")
        run_all_now(cfg)

    sched.add_job(job, "interval", hours=interval, id="full_pipeline")
    print(f"Scheduler started. Running every {interval}h for {len(groups)} group(s).")
    print("Press Ctrl+C to stop.\n")

    # Run once immediately on start
    job()

    try:
        sched.start()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Scheduler — automated analysis + NL query interface"
    )
    parser.add_argument("--run-now", action="store_true",
                        help="Run pipeline immediately and exit")
    parser.add_argument("--group", help="Limit --run-now to specific group_id")
    parser.add_argument("--interval", type=int, default=6,
                        help="Schedule interval in hours (default 6)")
    parser.add_argument("--query", help="NL query: 'hot leads', 'pain points', 'viral posts', etc.")
    parser.add_argument("--query-group", help="Group ID for --query")
    args = parser.parse_args()

    from load_config import load_config
    cfg = load_config()

    if args.query:
        group_id = args.query_group or args.group
        if not group_id:
            print("--query-group required with --query")
            sys.exit(1)
        result = run_nl_query(group_id, args.query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.run_now:
        results = run_all_now(cfg, args.group)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    start_scheduler(cfg, args.interval)


if __name__ == "__main__":
    main()
