"""
tiktok_search.py — Search TikTok for topic-related videos using Playwright.

Strategy: navigate to TikTok search, then extract data via JS from the rendered DOM.
The selectors adapt to TikTok's frequently changing class names by using
stable attributes (a[href*="/video/"], data-e2e, aria-label) plus a text-based
fallback that parses the visible page content.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from log_config import get_logger

_log = get_logger("tiktok")
_HERE = Path(__file__).parent


def _load_config() -> dict:
    cfg_path = _HERE / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def _parse_count(text: str) -> int:
    if not text:
        return 0
    text = text.strip().upper().replace(",", "")
    m = re.match(r"([\d.]+)\s*([KMB]?)", text)
    if not m:
        return 0
    num = float(m.group(1))
    mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2), 1)
    return int(num * mul)


def search(topic: str, max_videos: int = 20) -> dict[str, Any]:
    """Search TikTok for videos related to a topic."""
    _log.info("TikTok search: '%s' (max %d videos)", topic, max_videos)
    cfg = _load_config()
    headless = cfg.get("scraper", {}).get("headless", True)
    scroll_delay = cfg.get("scraper", {}).get("scroll_delay_ms", 2000)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "error",
            "source": "tiktok",
            "error": "playwright not installed",
        }

    videos: list[dict] = []
    search_url = f"https://www.tiktok.com/search?q={topic.replace(' ', '%20')}"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            context.add_init_script(
                'Object.defineProperty(navigator,"webdriver",{get:()=>undefined})'
            )

            page = context.new_page()
            _log.info("Navigating to TikTok search: %s", search_url)
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(6000)

            # Dismiss cookie consent
            for sel in [
                "button[data-testid='cookie-banner-accept']",
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    continue

            stall = 0
            prev_count = 0

            while len(videos) < max_videos and stall < 5:
                page.wait_for_timeout(scroll_delay)

                # Strategy: find each video link, walk up to its *individual* card
                # container, then extract description + stats scoped to that card only.
                items = page.evaluate(r"""
                    () => {
                        const results = [];
                        const seen = new Set();
                        const videoLinks = document.querySelectorAll('a[href*="/video/"]');

                        for (const link of videoLinks) {
                            const href = link.href || '';
                            const vidMatch = href.match(/\/@([\w.]+)\/video\/(\d+)/);
                            if (!vidMatch) continue;
                            const author = vidMatch[1];
                            const videoId = vidMatch[2];
                            if (seen.has(videoId)) continue;
                            seen.add(videoId);

                            // Walk up to find the card — stop when parent contains
                            // MORE than 1 video link (that means we went too far)
                            let card = link;
                            for (let i = 0; i < 10; i++) {
                                const p = card.parentElement;
                                if (!p) break;
                                const vlinks = p.querySelectorAll('a[href*="/video/"]');
                                if (vlinks.length > 1) break; // parent has siblings' links — card = current
                                card = p;
                            }

                            // Description: look in this specific card only
                            let desc = '';
                            // TikTok puts descriptions in various span/div elements
                            const textNodes = card.querySelectorAll('span, div > a');
                            for (const tn of textNodes) {
                                const t = tn.textContent.trim();
                                if (t.length > 20 && t.length < 600 && !t.includes('Log in')) {
                                    desc = t;
                                    break;
                                }
                            }
                            if (!desc) {
                                // Use textContent of the link itself
                                desc = (link.textContent || '').trim().substring(0, 300);
                            }

                            // Stats: engagement numbers scoped to this card
                            const stats = [];
                            const strongEls = card.querySelectorAll('strong');
                            for (const s of strongEls) {
                                const t = s.textContent.trim();
                                if (/^[\d,.]+[KMBkmb]?$/.test(t) && t !== '0') {
                                    stats.push(t);
                                }
                            }

                            results.push({
                                video_id: videoId,
                                url: href.split('?')[0],
                                author: author,
                                description: desc.substring(0, 500),
                                stats: stats.slice(0, 5),
                            });
                        }
                        return results;
                    }
                """)

                for item in items:
                    vid = item.get("video_id", "")
                    if vid and not any(v.get("video_id") == vid for v in videos):
                        stats = item.get("stats", [])
                        videos.append({
                            "video_id": vid,
                            "url": item.get("url", ""),
                            "author": item.get("author", ""),
                            "description": item.get("description", ""),
                            "engagement": _parse_count(stats[0]) if stats else 0,
                            "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
                        })

                if len(videos) == prev_count:
                    stall += 1
                else:
                    stall = 0
                prev_count = len(videos)

                _log.debug("TikTok: %d videos collected (stall=%d)", len(videos), stall)
                page.evaluate("window.scrollBy(0, 1000)")

            browser.close()

    except Exception as e:
        _log.error("TikTok search failed: %s", e)
        return {
            "status": "error" if not videos else "partial",
            "source": "tiktok",
            "topic": topic,
            "error": str(e),
            "total_videos": len(videos),
            "data": videos[:max_videos],
        }

    _log.info("TikTok search complete: %d videos", len(videos))
    return {
        "status": "ok",
        "source": "tiktok",
        "topic": topic,
        "total_videos": len(videos),
        "data": videos[:max_videos],
    }
