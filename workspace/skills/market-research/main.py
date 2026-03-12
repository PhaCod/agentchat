"""
main.py — CLI entry point for Market Research AI Assistant.

Commands:
  research  — Full market research on a topic (web + social media + AI analysis)
  web       — Web search only
  facebook  — Facebook group search only
  tiktok    — TikTok search only
  analyze   — Analyze previously collected data
  report    — Generate report from latest research
  list      — List saved research results
  read      — Read a saved research result

All commands support --output json for machine-readable output.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).parent


def _load_config() -> dict:
    cfg_path = _HERE / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def _load_env():
    """Load .env file into environment."""
    import os
    env_path = _HERE / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _out(data, output_format: str):
    if output_format == "json":
        raw = json.dumps(data, ensure_ascii=False, indent=2)
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
                val = str(v)
                if len(val) > 200:
                    val = val[:200] + "..."
                print(f"{pad}{k}: {val}")
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

def cmd_research(args):
    """Full market research: web + facebook + tiktok + AI analysis."""
    from log_config import get_logger
    log = get_logger("main")

    topic = args.topic
    sources = [s.strip() for s in args.sources.split(",")]
    log.info("Starting research on: '%s' (sources: %s)", topic, sources)

    collected = []

    # 1. Web search
    if "web" in sources:
        log.info("Phase 1/4: Web search...")
        import web_search
        result = web_search.search(topic, max_results=args.web_max)
        collected.append(result)

    # 2. Facebook search
    if "facebook" in sources or "fb" in sources:
        log.info("Phase 2/4: Facebook search...")
        import facebook_search
        fb_groups = args.facebook_groups.split(",") if args.facebook_groups else None
        result = facebook_search.search_groups(
            topic,
            group_urls=fb_groups,
            max_posts=args.fb_max,
            days=args.days,
        )
        collected.append(result)

    # 3. TikTok search
    if "tiktok" in sources or "tt" in sources:
        log.info("Phase 3/4: TikTok search...")
        import tiktok_search
        result = tiktok_search.search(topic, max_videos=args.tiktok_max)
        collected.append(result)

    # 3.5. Auto-supplement: if social media scrapers returned little data, use Gemini
    import gemini_ai
    social_data_count = sum(
        len(c.get("data", [])) for c in collected
        if c.get("source") in ("facebook", "tiktok")
    )
    if social_data_count < 5:
        log.info("Phase 3.5: Social media data sparse (%d items) — supplementing with AI search...", social_data_count)
        for platform in ("tiktok", "facebook", "instagram"):
            supplement = gemini_ai.search_social_insights(topic, platform=platform)
            if supplement.get("status") == "ok":
                collected.append(supplement)

    # 4. AI Analysis
    log.info("Phase 4/4: AI analysis and synthesis...")
    analysis = gemini_ai.analyze_data(topic, collected, language=args.lang)

    # 5. Generate report
    report_text = ""
    if analysis.get("status") == "ok":
        report_text = gemini_ai.generate_report_text(
            topic, analysis.get("analysis", {}), language=args.lang,
        )

    # 6. Save results
    import storage
    full_result = {
        "topic": topic,
        "sources_used": sources,
        "collected_data": collected,
        "analysis": analysis,
        "report": report_text,
    }
    json_path = storage.save_research(topic, full_result)
    if report_text:
        md_path = storage.save_report(topic, report_text)
        log.info("Report saved: %s", md_path)

    log.info("Research complete: %s", json_path)
    _out(full_result, args.output)


def cmd_web(args):
    """Web search only."""
    import web_search
    result = web_search.search(args.topic, max_results=args.web_max)
    _out(result, args.output)


def cmd_facebook(args):
    """Facebook group search only."""
    import facebook_search
    fb_groups = args.facebook_groups.split(",") if args.facebook_groups else None
    result = facebook_search.search_groups(
        args.topic,
        group_urls=fb_groups,
        max_posts=args.fb_max,
        days=args.days,
    )
    _out(result, args.output)


def cmd_tiktok(args):
    """TikTok search only."""
    import tiktok_search
    result = tiktok_search.search(args.topic, max_videos=args.tiktok_max)
    _out(result, args.output)


def cmd_analyze(args):
    """Analyze previously collected or provided data."""
    import gemini_ai
    import storage

    data = storage.load_latest_research(args.topic)
    if not data:
        _out({"status": "error", "error": "No previous research found for this topic"}, args.output)
        return

    collected = data.get("result", {}).get("collected_data", [])
    analysis = gemini_ai.analyze_data(args.topic, collected, language=args.lang)
    _out(analysis, args.output)


def cmd_report(args):
    """Generate report from latest research."""
    import gemini_ai
    import storage

    data = storage.load_latest_research(args.topic)
    if not data:
        _out({"status": "error", "error": "No previous research found"}, args.output)
        return

    analysis = data.get("result", {}).get("analysis", {}).get("analysis", {})
    report = gemini_ai.generate_report_text(args.topic, analysis, language=args.lang)

    md_path = storage.save_report(args.topic, report)
    if args.output == "json":
        _out({"status": "ok", "report": report, "saved_to": str(md_path)}, args.output)
    else:
        print(report)


def cmd_list(args):
    """List saved research results."""
    import storage
    results = storage.list_research()
    _out(results, args.output)


def cmd_read(args):
    """Read a saved research result."""
    import storage

    data = storage.load_latest_research(args.topic)
    if not data:
        _out({"status": "error", "error": "No research found"}, args.output)
        return
    _out(data, args.output)


# ---------------------------------------------------------------------------
# Arg parser
# ---------------------------------------------------------------------------

def main():
    _load_env()

    parser = argparse.ArgumentParser(
        description="Market Research AI Assistant — multi-source market intelligence"
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # Shared args
    def add_common(p):
        p.add_argument("--output", choices=["json", "text"], default="json")
        p.add_argument("--lang", default="vi", help="Output language (vi/en)")

    def add_topic(p):
        p.add_argument("--topic", "-t", required=True, help="Research topic")

    def add_source_args(p):
        p.add_argument("--web-max", type=int, default=10, help="Max web results")
        p.add_argument("--fb-max", type=int, default=30, help="Max Facebook posts per group")
        p.add_argument("--tiktok-max", type=int, default=20, help="Max TikTok videos")
        p.add_argument("--days", type=int, default=7, help="Days back for social media")
        p.add_argument("--facebook-groups", default="", help="Comma-separated Facebook group URLs")

    # research
    p_res = sub.add_parser("research", help="Full market research")
    add_topic(p_res)
    add_common(p_res)
    add_source_args(p_res)
    p_res.add_argument(
        "--sources", default="web,tiktok",
        help="Comma-separated sources: web,facebook,tiktok (default: web,tiktok)",
    )
    p_res.set_defaults(func=cmd_research)

    # web
    p_web = sub.add_parser("web", help="Web search only")
    add_topic(p_web)
    add_common(p_web)
    p_web.add_argument("--web-max", type=int, default=10)
    p_web.set_defaults(func=cmd_web)

    # facebook
    p_fb = sub.add_parser("facebook", help="Facebook group search")
    add_topic(p_fb)
    add_common(p_fb)
    p_fb.add_argument("--fb-max", type=int, default=30)
    p_fb.add_argument("--days", type=int, default=7)
    p_fb.add_argument("--facebook-groups", default="")
    p_fb.set_defaults(func=cmd_facebook)

    # tiktok
    p_tt = sub.add_parser("tiktok", help="TikTok search")
    add_topic(p_tt)
    add_common(p_tt)
    p_tt.add_argument("--tiktok-max", type=int, default=20)
    p_tt.set_defaults(func=cmd_tiktok)

    # analyze
    p_an = sub.add_parser("analyze", help="Analyze previous data")
    add_topic(p_an)
    add_common(p_an)
    p_an.set_defaults(func=cmd_analyze)

    # report
    p_rp = sub.add_parser("report", help="Generate report")
    add_topic(p_rp)
    add_common(p_rp)
    p_rp.set_defaults(func=cmd_report)

    # list
    p_ls = sub.add_parser("list", help="List saved research")
    add_common(p_ls)
    p_ls.set_defaults(func=cmd_list)

    # read
    p_rd = sub.add_parser("read", help="Read saved research")
    add_topic(p_rd)
    add_common(p_rd)
    p_rd.set_defaults(func=cmd_read)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
