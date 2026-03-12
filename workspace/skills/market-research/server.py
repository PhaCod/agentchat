"""
server.py — MCP Server for Market Research AI Assistant.

Provides tools via the Model Context Protocol (MCP) using FastMCP.
Can be used standalone or registered with OpenClaw.

Run:
  python server.py                    # stdio transport (for OpenClaw)
  python server.py --transport http   # HTTP transport (port 8100)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).parent
os.chdir(str(_HERE))

# Load .env
env_path = _HERE / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from fastmcp import FastMCP

mcp = FastMCP("Market Research AI")


@mcp.tool
def research_topic(
    topic: str,
    sources: str = "web,tiktok",
    language: str = "vi",
    web_max: int = 10,
    tiktok_max: int = 20,
    facebook_max: int = 30,
    days: int = 7,
    facebook_groups: str = "",
) -> str:
    """Perform comprehensive market research on any topic.

    Searches multiple sources (web, Facebook groups, TikTok), analyzes all collected
    data with Gemini AI, and generates a structured market research report.

    Args:
        topic: The research topic (e.g. "son môi Việt Nam", "quán cà phê Sài Gòn")
        sources: Comma-separated list of sources to use: web, facebook, tiktok
        language: Output language — "vi" for Vietnamese, "en" for English
        web_max: Maximum web search results to include
        tiktok_max: Maximum TikTok videos to analyze
        facebook_max: Maximum Facebook posts per group
        days: How many days back to search on social media
        facebook_groups: Comma-separated Facebook group URLs (uses defaults if empty)
    """
    import gemini_ai
    import storage
    from log_config import get_logger
    log = get_logger("mcp")

    source_list = [s.strip() for s in sources.split(",")]
    log.info("MCP research_topic: '%s' (sources: %s)", topic, source_list)
    collected = []

    if "web" in source_list:
        import web_search
        collected.append(web_search.search(topic, max_results=web_max))

    if "facebook" in source_list or "fb" in source_list:
        import facebook_search
        fb_groups = facebook_groups.split(",") if facebook_groups else None
        collected.append(
            facebook_search.search_groups(topic, group_urls=fb_groups, max_posts=facebook_max, days=days)
        )

    if "tiktok" in source_list or "tt" in source_list:
        import tiktok_search
        collected.append(tiktok_search.search(topic, max_videos=tiktok_max))

    # Auto-supplement if social scraping returned little data
    social_count = sum(len(c.get("data", [])) for c in collected if c.get("source") in ("facebook", "tiktok"))
    if social_count < 5:
        for platform in ("tiktok", "facebook", "instagram"):
            supplement = gemini_ai.search_social_insights(topic, platform=platform)
            if supplement.get("status") == "ok":
                collected.append(supplement)

    analysis = gemini_ai.analyze_data(topic, collected, language=language)
    report = ""
    if analysis.get("status") == "ok":
        report = gemini_ai.generate_report_text(topic, analysis.get("analysis", {}), language=language)

    full_result = {
        "topic": topic,
        "sources_used": source_list,
        "collected_data": collected,
        "analysis": analysis,
        "report": report,
    }
    path = storage.save_research(topic, full_result)

    if report:
        storage.save_report(topic, report)
        return report
    return json.dumps(analysis, ensure_ascii=False, indent=2)


@mcp.tool
def search_web(topic: str, max_results: int = 10) -> str:
    """Search the web for information about a topic using Google Search.

    Returns key findings, trends, statistics, and sources.

    Args:
        topic: What to search for
        max_results: Maximum number of results
    """
    import web_search
    result = web_search.search(topic, max_results=max_results)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool
def search_facebook(
    topic: str,
    group_urls: str = "",
    max_posts: int = 30,
    days: int = 7,
) -> str:
    """Search Facebook groups for posts about a topic.

    Scrapes real posts from Facebook groups using a headless browser.

    Args:
        topic: Topic to search for in posts
        group_urls: Comma-separated Facebook group URLs (uses defaults if empty)
        max_posts: Maximum posts to collect per group
        days: How many days back to search
    """
    import facebook_search
    groups = group_urls.split(",") if group_urls else None
    result = facebook_search.search_groups(topic, group_urls=groups, max_posts=max_posts, days=days)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool
def search_tiktok(topic: str, max_videos: int = 20) -> str:
    """Search TikTok for videos about a topic.

    Scrapes TikTok search results to find trending videos, views, likes.

    Args:
        topic: Topic to search for on TikTok
        max_videos: Maximum videos to collect
    """
    import tiktok_search
    result = tiktok_search.search(topic, max_videos=max_videos)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool
def search_social_insights(topic: str, platform: str = "all") -> str:
    """Search for social media insights about a topic via AI-powered web search.

    Works even without direct platform access — uses Google Search to find
    discussions, reviews, and opinions from social media platforms.

    Args:
        topic: Topic to research
        platform: Focus platform — "tiktok", "facebook", "instagram", or "all"
    """
    import gemini_ai
    result = gemini_ai.search_social_insights(topic, platform=platform)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool
def analyze_research(topic: str, language: str = "vi") -> str:
    """Re-analyze previously collected research data with AI.

    Args:
        topic: Topic to find and re-analyze
        language: Output language (vi/en)
    """
    import gemini_ai
    import storage

    data = storage.load_latest_research(topic)
    if not data:
        return json.dumps({"status": "error", "error": "No previous research found for this topic"})
    collected = data.get("result", {}).get("collected_data", [])
    analysis = gemini_ai.analyze_data(topic, collected, language=language)
    return json.dumps(analysis, ensure_ascii=False, indent=2)


@mcp.tool
def list_research() -> str:
    """List all saved market research results.

    Returns a list of topics, dates, and file paths.
    """
    import storage
    results = storage.list_research()
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool
def read_research(topic: str) -> str:
    """Read a previously saved market research result.

    Args:
        topic: Topic keyword to search for in saved results
    """
    import storage
    data = storage.load_latest_research(topic)
    if not data:
        return json.dumps({"status": "error", "error": "No research found"})

    report = data.get("result", {}).get("report", "")
    if report:
        return report
    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http"])
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    if args.transport == "http":
        try:
            mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
        except TypeError:
            mcp.run(transport="sse", host="127.0.0.1", port=args.port)
    else:
        mcp.run()
