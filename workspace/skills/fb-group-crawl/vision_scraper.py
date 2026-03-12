"""vision_scraper.py — Vision-AI-based Facebook group post scraper.

Instead of parsing the DOM for each field, this scraper:
  1. Identifies top-level post articles (minimal DOM: [role='feed'] + [role='article'])
  2. Extracts post_id/post_url from permalink href (needed for dedup only)
  3. Takes a screenshot of each article element
  4. Sends screenshot to Gemini Vision API with a structured extraction prompt
  5. Parses the JSON response into a post dict compatible with db.upsert_posts()

Advantages over DOM scraper:
  - Zero CSS selector maintenance — works regardless of Facebook class changes
  - Accurate timestamp ("3 giờ trước", "5 tháng 3" read visually)
  - Correct reaction breakdown (reads 👍❤️😂 icons and counts)
  - Media content description included
  - Comment count no longer inflated by minute-string parsing bugs
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import google.generativeai as genai
from playwright.sync_api import sync_playwright, Page

# Reuse session/login/nav helpers from scraper.py
from scraper import (
    _save_session,
    _load_session,
    _login,
    _dismiss_popups,
    _parse_relative_time,
    _get,
    _load_config,
)
from log_config import get_logger

_log = get_logger("vision_scraper")
_HERE = Path(__file__).parent


# ---------------------------------------------------------------------------
# Gemini Vision extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """Bạn là AI chuyên trích xuất dữ liệu có cấu trúc từ ảnh chụp màn hình bài đăng Facebook.

Phân tích ảnh này và trả về JSON với các trường sau (không có markdown, chỉ JSON thuần):
{
  "author": "Tên người đăng bài gốc (không phải người comment)",
  "posted_at_text": "Thời gian đăng, giữ nguyên text gốc, ví dụ: '3 giờ trước', '5 tháng 3 lúc 9:30 SA', 'Hôm qua lúc 14:00', 'March 5 at 9:30 AM'",
  "content": "Nội dung văn bản của bài đăng gốc. Giữ nguyên xuống dòng. Không lấy comment.",
  "reactions_total": số nguyên hoặc null,
  "reactions_breakdown": {
    "like": số hoặc 0,
    "love": số hoặc 0,
    "haha": số hoặc 0,
    "wow": số hoặc 0,
    "sad": số hoặc 0,
    "angry": số hoặc 0,
    "care": số hoặc 0
  },
  "comments_count": số nguyên hoặc null,
  "shares_count": số nguyên hoặc null,
  "has_image": true hoặc false,
  "has_video": true hoặc false,
  "media_description": "Mô tả ngắn về ảnh/video trong bài nếu có, null nếu không có",
  "content_type": "text" hoặc "image" hoặc "video" hoặc "link"
}

Quy tắc:
- Chỉ trích xuất thông tin của BÀI ĐĂNG GỐC, không lấy từ comment.
- Nếu không thấy một trường, trả về null (không đoán mò).
- Trả về JSON thuần, không có ```json``` hay dấu backtick nào."""


# ---------------------------------------------------------------------------
# Timestamp: parse Gemini's text output to ISO-8601
# ---------------------------------------------------------------------------

def _parse_vision_timestamp(text: str | None) -> str:
    """Convert text like '3 giờ trước', '5 tháng 3 lúc 9:30 SA' to ISO-8601.
    Falls back to reusing _parse_relative_time from scraper.
    """
    if not text:
        return ""
    # Try the existing relative/absolute parser from scraper.py
    dt = _parse_relative_time(text)
    if dt:
        return dt.isoformat()
    # Return the raw text so downstream still has some time info
    return ""


# ---------------------------------------------------------------------------
# Post ID extraction (minimal DOM — only needed for deduplication)
# ---------------------------------------------------------------------------

def _extract_post_id_from_el(article_el, group_id: str) -> tuple[str, str]:
    """Return (post_id, post_url) from minimal DOM query on the article element.
    Falls back to a content-hash-based ID if no permalink link is found.
    """
    post_id = None
    post_url = ""

    try:
        for link in article_el.query_selector_all("a[href]"):
            href = link.get_attribute("href") or ""
            if "/user/" in href and "/posts/" not in href:
                continue
            for pattern in [r"story_fbid=(\d+)", r"/(?:posts|permalink)/(\d+)", r"fbid=(\d+)"]:
                m = re.search(pattern, href)
                if m:
                    post_id = m.group(1)
                    post_url = re.sub(r"\?.*$", "", href).rstrip("/")
                    break
            if post_id:
                break
    except Exception:
        pass

    if not post_id:
        # Fallback: timestamp-based unique ID
        post_id = f"vision_{int(time.time() * 1000)}"

    if post_url and not post_url.startswith("http"):
        post_url = "https://www.facebook.com" + post_url

    return post_id, post_url


# ---------------------------------------------------------------------------
# Core Vision extraction call
# ---------------------------------------------------------------------------

def _vision_extract_post(
    model,
    screenshot_bytes: bytes,
    post_id: str,
    post_url: str,
    group_id: str,
) -> dict[str, Any] | None:
    """Send article screenshot to Gemini Vision, parse structured JSON.
    Retries once on 429 quota errors with delay parsed from the error message.
    """
    try:
        image_part = {"mime_type": "image/png", "data": screenshot_bytes}

        # Call with one 429-aware retry
        response = None
        for attempt in range(2):
            try:
                response = model.generate_content([image_part, _EXTRACTION_PROMPT])
                break
            except Exception as api_err:
                err_str = str(api_err)
                if "429" in err_str and attempt == 0:
                    # Parse retry delay from error message (e.g. "retry in 44s")
                    m = re.search(r"retry[^\d]+(\d+)", err_str)
                    delay = int(m.group(1)) + 5 if m else 65
                    _log.warning("429 quota — waiting %ds before retry for %s", delay, post_id)
                    time.sleep(delay)
                else:
                    raise

        if response is None:
            return None

        raw = (response.text or "").strip()
        _log.debug("Gemini raw response (%s): %s", post_id, raw[:300])

        # Strip markdown code fences if model wraps in them
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        data = json.loads(raw)

        posted_at = _parse_vision_timestamp(data.get("posted_at_text"))

        reactions = data.get("reactions_breakdown") or {}
        reactions_total = data.get("reactions_total")
        if reactions_total is None:
            reactions_total = sum(v for v in reactions.values() if isinstance(v, (int, float)))

        # Append media description to content so FTS and AI queries can use it
        content = data.get("content") or ""
        media_desc = data.get("media_description") or ""
        if media_desc:
            content = f"{content}\n[Ảnh/Video: {media_desc}]".strip()

        return {
            "post_id": post_id,
            "group_id": group_id,
            "author": data.get("author") or "Unknown",
            "author_id": "",
            "content": content,
            "media": json.dumps([]),
            "reactions_total": int(reactions_total or 0),
            "reactions_like": int(reactions.get("like") or 0),
            "reactions_love": int(reactions.get("love") or 0),
            "reactions_haha": int(reactions.get("haha") or 0),
            "reactions_wow": int(reactions.get("wow") or 0),
            "reactions_sad": int(reactions.get("sad") or 0),
            "reactions_angry": int(reactions.get("angry") or 0),
            "comments_count": int(data.get("comments_count") or 0),
            "shares_count": int(data.get("shares_count") or 0),
            "post_url": post_url,
            "content_type": data.get("content_type") or "text",
            "timestamp": posted_at,
            "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    except json.JSONDecodeError as e:
        _log.warning("Vision JSON parse error (post_id=%s): %s | raw: %s",
                     post_id, e, (response.text or "")[:200])
        return None
    except Exception as e:
        _log.warning("Vision extract failed (post_id=%s): %s", post_id, e)
        return None


# ---------------------------------------------------------------------------
# VisionGroupScraper
# ---------------------------------------------------------------------------

class VisionGroupScraper:
    """Scrapes a Facebook group using Gemini Vision for field extraction.

    Drop-in replacement for GroupPostScraper — same .scrape() interface.
    """

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or _load_config()

        # Browser config
        self.headless: bool = _get(self.cfg, "scraper", "headless", default=False)
        self.scroll_delay: int = _get(self.cfg, "scraper", "scroll_delay_ms", default=2500)
        self.max_posts: int = _get(self.cfg, "scraper", "max_posts", default=500)
        self.days_back: int = _get(self.cfg, "scraper", "days_back", default=30)

        # Session / auth
        self.session_file = Path(
            _get(self.cfg, "facebook", "session_file",
                 default=str(_HERE / "sessions" / "fb_session.json"))
        )
        self.email: str = _get(self.cfg, "facebook", "email", default="")
        self.password: str = _get(self.cfg, "facebook", "password", default="")

        # Vision API
        api_key = os.environ.get("GOOGLE_API_KEY") or _get(self.cfg, "gemini", "api_key", default="")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set. Add to .env or config.")
        genai.configure(api_key=api_key)

        model_name = _get(self.cfg, "gemini", "vision_model",
                          default=_get(self.cfg, "gemini", "model", default="gemini-2.5-flash"))
        self.model = genai.GenerativeModel(model_name)
        _log.info("Vision model: %s", model_name)

        # Rate limiting: Gemini free tier = 15 req/min
        self._api_call_interval: float = _get(self.cfg, "gemini", "vision_call_interval_s", default=4.5)

        # Optional proxy
        proxy_cfg = _get(self.cfg, "proxy")
        self.proxy = None
        if proxy_cfg and proxy_cfg.get("enabled"):
            provider = proxy_cfg.get("provider", "custom")
            hosts = {
                "brightdata": ("brd.superproxy.io", 22225),
                "iproyal": ("proxy.iproyal.com", 12321),
                "stormproxies": ("rotating.stormproxies.com", 9999),
                "netnut": ("gw-resi.netnut.io", 5959),
            }
            host, port = hosts.get(provider, (proxy_cfg.get("host", ""), proxy_cfg.get("port", 8080)))
            self.proxy = {
                "server": f"http://{host}:{port}",
                "username": proxy_cfg.get("username", ""),
                "password": proxy_cfg.get("password", ""),
            }

    # -----------------------------------------------------------------------

    def scrape(
        self,
        group_url: str,
        run_id: str | None = None,
        stop_at_post_id: str | None = None,
    ) -> list[dict]:
        """Scrape posts from a Facebook group URL using Vision AI extraction.

        Returns list of post dicts compatible with db.upsert_posts().
        """
        if not ("http" in group_url or "facebook.com" in group_url):
            group_url = f"https://www.facebook.com/groups/{group_url.strip()}"
        group_id = self._extract_group_id(group_url)
        cutoff = datetime.now(tz=timezone.utc).timestamp() - self.days_back * 86400

        posts: dict[str, dict] = {}  # post_id → post (dedup)
        attempted: set[str] = set()  # all post_ids tried this session (incl. failures)
        last_api_call = 0.0

        launch_args = {
            "headless": self.headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        }
        if self.proxy:
            launch_args["proxy"] = self.proxy

        with sync_playwright() as pw:
            browser = pw.chromium.launch(**launch_args)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            # Session handling
            session_loaded = _load_session(context, self.session_file)
            if not session_loaded:
                if self.email and self.password:
                    _login(page, self.email, self.password)
                    if "login" not in page.url and "checkpoint" not in page.url:
                        _save_session(context, self.session_file)
                    else:
                        _log.warning("Login may not have succeeded.")
                else:
                    _log.error("No session and no credentials. Set FB_EMAIL/FB_PASSWORD.")
                    browser.close()
                    return []

            _log.info("Navigating to %s", group_url)
            page.goto(group_url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            _dismiss_popups(page)
            page.wait_for_timeout(1500)

            reached_cursor = False
            no_new_posts_rounds = 0

            while len(posts) < self.max_posts:
                # Find top-level feed articles (same logic as DOM scraper)
                try:
                    feed_el = page.query_selector("[role='feed']")
                    if not feed_el:
                        _log.warning("No [role='feed'] found, waiting...")
                        page.wait_for_timeout(3000)
                        continue
                    all_articles = feed_el.query_selector_all("div[role='article']")
                except Exception as e:
                    _log.warning("Feed query error: %s", e)
                    page.wait_for_timeout(3000)
                    continue

                top_level_els = []
                for art in all_articles:
                    try:
                        is_nested = art.evaluate("""
                            el => {
                                let p = el.parentElement;
                                while (p) {
                                    if (p.getAttribute('role') === 'feed') return false;
                                    if (p.getAttribute('role') === 'article') return true;
                                    p = p.parentElement;
                                }
                                return false;
                            }
                        """)
                        if not is_nested:
                            top_level_els.append(art)
                    except Exception:
                        continue

                _log.debug("Feed: %d total articles, %d top-level posts", len(all_articles), len(top_level_els))

                new_this_round = 0
                for el in top_level_els:
                    if len(posts) >= self.max_posts:
                        break

                    try:
                        post_id, post_url = _extract_post_id_from_el(el, group_id)
                    except Exception:
                        continue

                    # Skip already processed or attempted (failed ones too)
                    if post_id in posts or post_id in attempted:
                        continue

                    # Incremental stop
                    if stop_at_post_id and post_id == stop_at_post_id:
                        _log.info("Reached cursor post_id=%s — stopping.", stop_at_post_id)
                        reached_cursor = True
                        break

                    # Mark as attempted now — prevents re-trying on next scroll round
                    attempted.add(post_id)

                    # DOM-level comment filter: comment cards have "Reply" but no "Comment"
                    # Top-level posts always have a "Comment" action button
                    # Only scan buttons at direct article level — skip nested article (comment section)
                    try:
                        action_info = el.evaluate("""
                            el => {
                                let hasReply = false, hasComment = false;
                                const buttons = el.querySelectorAll(
                                    'div[role="button"], a[role="link"], span[role="button"]'
                                );
                                for (const btn of buttons) {
                                    let p = btn.parentElement, inNested = false;
                                    while (p && p !== el) {
                                        if (p.getAttribute('role') === 'article') { inNested = true; break; }
                                        p = p.parentElement;
                                    }
                                    if (inNested) continue;
                                    const t = (btn.textContent || btn.getAttribute('aria-label') || '')
                                                .trim().toLowerCase();
                                    if (t === 'reply' || t === 'phản hồi') hasReply = true;
                                    if (t === 'comment' || t === 'bình luận') hasComment = true;
                                }
                                return { hasReply, hasComment };
                            }
                        """)
                        if action_info.get("hasReply") and not action_info.get("hasComment"):
                            _log.debug("Comment card detected (hasReply=True, hasComment=False), skipping %s", post_id)
                            continue
                    except Exception:
                        pass  # if check fails, proceed anyway

                    # Rate limit: ensure minimum gap between API calls
                    wait = self._api_call_interval - (time.time() - last_api_call)
                    if wait > 0:
                        time.sleep(wait)

                    # Screenshot the article element
                    # Scroll into view first so Facebook lazy-loads the post content
                    try:
                        el.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(800)  # let lazy content render
                        screenshot_bytes = el.screenshot(type="png")
                        # Save debug screenshot if debug dir exists
                        dbg_dir = _HERE / "debug_screenshots"
                        if dbg_dir.exists():
                            dbg_path = dbg_dir / f"{post_id}.png"
                            dbg_path.write_bytes(screenshot_bytes)
                    except Exception as e:
                        _log.debug("Screenshot failed for %s: %s", post_id, e)
                        continue

                    # Skip loading skeleton (< 5 KB means FB hasn't rendered content yet)
                    if len(screenshot_bytes) < 5000:
                        _log.debug("Skeleton screenshot (%d bytes), skipping %s", len(screenshot_bytes), post_id)
                        continue

                    # Vision extraction
                    _log.info("[%4d] Extracting via Vision: %s …", len(posts) + 1, post_id)
                    last_api_call = time.time()
                    post = _vision_extract_post(self.model, screenshot_bytes, post_id, post_url, group_id)

                    if not post:
                        continue

                    # Quality filter: skip if Vision extracted nothing useful
                    # (happens for comment cards, ads, or partially-rendered posts)
                    if post.get("author", "Unknown") == "Unknown" and not post.get("content", "").strip():
                        _log.debug("Vision returned no data for %s — skipping (comment card or ad)", post_id)
                        continue

                    # Date cutoff check on extracted timestamp
                    if post.get("timestamp"):
                        try:
                            ts = datetime.fromisoformat(post["timestamp"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts.timestamp() < cutoff:
                                _log.info("Post %s older than cutoff, stopping.", post_id)
                                reached_cursor = True
                                break
                        except ValueError:
                            pass

                    if run_id:
                        post["scrape_run_id"] = run_id
                    posts[post_id] = post
                    new_this_round += 1
                    _log.info("[%4d] %s | %s | r:%s c:%s",
                              len(posts),
                              post.get("author", "?")[:30],
                              post.get("timestamp", "")[:10] or "no-ts",
                              post.get("reactions_total", 0),
                              post.get("comments_count", 0))

                if reached_cursor:
                    break

                if new_this_round == 0:
                    no_new_posts_rounds += 1
                    if no_new_posts_rounds >= 3:
                        _log.info("No new posts for 3 scroll rounds — stopping.")
                        break
                else:
                    no_new_posts_rounds = 0

                if len(posts) >= self.max_posts:
                    _log.info("Reached max_posts=%d. Stopping.", self.max_posts)
                    break

                # Scroll down
                page.evaluate("""
                    (() => {
                        const feed = document.querySelector('[role="feed"]');
                        if (feed) feed.scrollTop = feed.scrollHeight;
                        window.scrollTo(0, document.body.scrollHeight);
                    })()
                """)
                page.wait_for_timeout(self.scroll_delay)

            browser.close()

        _log.info("Vision scrape done. Collected %d posts from %s.", len(posts), group_id)
        return list(posts.values())

    @staticmethod
    def _extract_group_id(group_url: str) -> str:
        m = re.search(r"groups/([^/?#]+)", group_url)
        if m:
            return m.group(1)
        m = re.search(r"facebook\.com/([^/?#]+)", group_url)
        if m:
            return m.group(1)
        return re.sub(r"[^a-zA-Z0-9_-]", "_", group_url)[-40:]
