"""
scraper.py — Playwright-based Facebook scraper for social-brand-tracker.

Crawls posts + comments from Facebook Groups and Pages.
Reuses proven patterns from fb-group-crawl with additions:
  - Comment thread expansion
  - User profile extraction from DOM
  - 120s hard timeout, 4-stall detection
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from log_config import get_logger

_log = get_logger("scraper")
_HERE = Path(__file__).parent

_SCRAPE_TIMEOUT_S = 120
_STALL_LIMIT = 4


def _get(cfg: dict, *keys, default=None):
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_count(raw: str) -> int:
    raw = raw.strip().replace("\u00a0", "").replace(",", "").replace(" ", "")
    m = re.match(r"([\d.]+)\s*([KMBkmb]?)", raw)
    if not m:
        return 0
    num = float(m.group(1))
    suffix = m.group(2).upper()
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(num * mult)


_RELATIVE_RE = re.compile(
    r"(\d+)\s*(ph[uú]t|minute|min|gi[oờ]|hour|hr|ng[aà]y|day|tu[aầ]n|week|th[aá]ng|month|gi[aâ]y|second|sec)",
    re.IGNORECASE,
)


def _parse_relative_time(text: str) -> datetime | None:
    text_lower = text.lower().strip()
    now = datetime.now(tz=timezone.utc)
    if any(w in text_lower for w in ("just now", "vừa xong", "vừa", "now")):
        return now
    if any(w in text_lower for w in ("yesterday", "hôm qua")):
        return now - timedelta(days=1)

    m = _RELATIVE_RE.search(text)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2).lower()
    if any(u in unit for u in ("ph", "min")):
        return now - timedelta(minutes=val)
    if any(u in unit for u in ("gi", "hour", "hr")):
        return now - timedelta(hours=val)
    if any(u in unit for u in ("ng", "day")):
        return now - timedelta(days=val)
    if any(u in unit for u in ("tu", "week")):
        return now - timedelta(weeks=val)
    if any(u in unit for u in ("th", "month")):
        return now - timedelta(days=val * 30)
    if any(u in unit for u in ("sec", "giây")):
        return now - timedelta(seconds=val)
    return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _load_session(context, session_file: Path) -> bool:
    if session_file.exists():
        try:
            cookies = json.loads(session_file.read_text(encoding="utf-8"))
            context.add_cookies(cookies)
            _log.info("Session loaded from %s", session_file)
            return True
        except Exception as e:
            _log.warning("Failed to load session: %s", e)
    return False


def _save_session(context, session_file: Path) -> None:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    cookies = context.cookies()
    session_file.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    _log.info("Session saved to %s", session_file)


def _login(page: Page, email: str, password: str) -> None:
    _log.info("Logging into Facebook...")
    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    page.fill("input[name='email']", email)
    page.fill("input[name='pass']", password)
    page.click("button[name='login']")
    page.wait_for_timeout(5000)
    _log.info("Login submitted, URL: %s", page.url)


def _dismiss_popups(page: Page) -> None:
    for sel in [
        "[aria-label='Close']", "[aria-label='Đóng']",
        "div[role='dialog'] div[role='button']",
    ]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Post parsing
# ---------------------------------------------------------------------------

def _parse_post(post_el, source_id: str) -> dict | None:
    try:
        # Post ID from permalink
        post_id, post_url = "", ""
        for link in post_el.query_selector_all("a[href*='/posts/'], a[href*='story_fbid'], a[href*='permalink']"):
            href = link.get_attribute("href") or ""
            if href:
                post_url = href.split("?")[0]
                m = re.search(r"/posts/(\d+)", href) or re.search(r"story_fbid=(\d+)", href)
                if m:
                    post_id = m.group(1)
                    break
        if not post_id:
            post_id = f"unknown_{int(time.time() * 1000)}"

        # Author
        author_name, author_id = "", ""
        author_el = post_el.query_selector("strong a, h3 a, h4 a, [data-testid='story-subtitle'] a")
        if author_el:
            author_name = (author_el.inner_text() or "").strip()
            href = author_el.get_attribute("href") or ""
            m = re.search(r"facebook\.com/(?:profile\.php\?id=)?(\d+|[^/?#]+)", href)
            if m:
                author_id = m.group(1)

        # Timestamp
        timestamp = ""
        for strategy in [
            lambda: _try_data_utime(post_el),
            lambda: _try_aria_label_time(post_el),
            lambda: _try_visible_time(post_el),
            lambda: _try_js_time_scan(post_el),
        ]:
            try:
                result = strategy()
                if result:
                    timestamp = result
                    break
            except Exception:
                continue

        # Expand "See more"
        try:
            see_more = post_el.query_selector(
                "div[role='button']:has-text('See more'), "
                "div[role='button']:has-text('Xem thêm'), "
                "span:has-text('See more'), span:has-text('Xem thêm')"
            )
            if see_more and see_more.is_visible():
                see_more.click(timeout=2000)
                time.sleep(0.3)
        except Exception:
            pass

        # Content (exclude comment zones)
        content = ""
        for sel in ["[data-ad-comet-preview='message']", "[data-testid='post_message']",
                     "div[class*='userContent']"]:
            el = post_el.query_selector(sel)
            if el:
                content = el.inner_text().strip()
                if content:
                    break
        if not content:
            try:
                for cand in post_el.query_selector_all("div[dir='auto']"):
                    in_comment = cand.evaluate("el => !!el.closest(\"[aria-label*='comment' i], [data-testid*='UFI2Comments']\")")
                    if in_comment:
                        continue
                    txt = (cand.inner_text() or "").strip()
                    if txt and len(txt) > 5:
                        noise = {"like", "comment", "share", "see more", "xem thêm"}
                        if txt.lower() not in noise:
                            content = txt
                            break
            except Exception:
                pass

        # Media type
        media_type = "text"
        if post_el.query_selector("video, [data-testid*='video']"):
            media_type = "video"
        elif post_el.query_selector("img[src*='fbcdn']"):
            media_type = "image"
        elif post_el.query_selector("a[href*='l.facebook.com'], a[href*='lm.facebook.com']"):
            media_type = "link"

        # Reactions
        reactions_total = _extract_metric(post_el, [
            "[aria-label*='reaction']", "[aria-label*='lượt cảm xúc']",
            "[data-testid='UFI2ReactionsCount']",
        ])

        # Comments count
        comments_count = _extract_metric(post_el, [
            "a[href*='comment']", "[aria-label*='comment']",
            "[aria-label*='bình luận']",
        ])

        # Shares
        shares_count = _extract_metric(post_el, [
            "[aria-label*='share']", "[aria-label*='chia sẻ']",
        ])

        return {
            "post_id": post_id,
            "author_id": author_id,
            "author_name": author_name,
            "content": content,
            "post_url": post_url,
            "media_type": media_type,
            "reactions_total": reactions_total,
            "comments_count": comments_count,
            "shares_count": shares_count,
            "views_count": 0,
            "posted_at": timestamp,
            "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        _log.debug("Error parsing post: %s", e)
        return None


def _extract_metric(post_el, selectors: list[str]) -> int:
    for sel in selectors:
        try:
            el = post_el.query_selector(sel)
            if el:
                txt = el.get_attribute("aria-label") or el.inner_text()
                nums = re.findall(r"[\d,.]+\s*[KMBkmb]?", txt.replace("\u00a0", " "))
                if nums:
                    val = _parse_count(nums[0].strip())
                    if val:
                        return val
        except Exception:
            continue
    return 0


def _try_data_utime(el) -> str | None:
    utime_el = el.query_selector("[data-utime], abbr[data-utime]")
    if utime_el:
        utime = utime_el.get_attribute("data-utime")
        if utime and str(utime).isdigit():
            return datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
    return None


def _try_aria_label_time(el) -> str | None:
    for link in el.query_selector_all("a[href*='/posts/'], a[href*='story_fbid']"):
        label = link.get_attribute("aria-label") or ""
        if label and 3 < len(label) < 120:
            dt = _parse_relative_time(label)
            if dt:
                return dt.isoformat()
    return None


def _try_visible_time(el) -> str | None:
    for sel in ["abbr", "span[role='text']", "a[role='link'] span"]:
        sub = el.query_selector(sel)
        if sub:
            txt = (sub.inner_text() or "").strip()
            if txt and len(txt) < 80:
                dt = _parse_relative_time(txt)
                if dt:
                    return dt.isoformat()
    return None


def _try_js_time_scan(el) -> str | None:
    found = el.evaluate(r"""
        el => {
            const RE = /phút|minute|min|giờ|hour|ngày|day|tuần|week|tháng|month|giây|second|hôm qua|yesterday|just now|vừa/i;
            for (const s of el.querySelectorAll('span, abbr, a[aria-label]')) {
                const t = (s.getAttribute('aria-label') || s.textContent || '').trim();
                if (t.length > 2 && t.length < 100 && RE.test(t)) return t;
            }
            return '';
        }
    """)
    if found:
        dt = _parse_relative_time(found)
        if dt:
            return dt.isoformat()
    return None


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------

def _parse_comments(page: Page, post_el, post_id: str, max_comments: int = 30) -> list[dict]:
    """Expand and parse comments within a post element."""
    comments = []
    try:
        # Click "View more comments" up to 3 times
        for _ in range(3):
            more_btn = post_el.query_selector(
                "div[role='button']:has-text('View more comments'), "
                "div[role='button']:has-text('Xem thêm bình luận'), "
                "span:has-text('View more comments'), "
                "span:has-text('previous comments')"
            )
            if more_btn and more_btn.is_visible():
                more_btn.click(timeout=2000)
                page.wait_for_timeout(1500)
            else:
                break

        # Find comment elements (nested articles within the post)
        comment_els = post_el.query_selector_all("div[role='article'] div[role='article']")
        if not comment_els:
            comment_els = post_el.query_selector_all("ul li div[data-testid*='comment']")

        for i, cel in enumerate(comment_els[:max_comments]):
            try:
                comment = _parse_single_comment(cel, post_id, i)
                if comment:
                    comments.append(comment)
            except Exception:
                continue

    except Exception as e:
        _log.debug("Error expanding comments for post %s: %s", post_id, e)

    return comments


def _parse_single_comment(cel, post_id: str, idx: int) -> dict | None:
    commenter_name, commenter_id = "", ""
    name_el = cel.query_selector("a[role='link'] span, a > strong, a > span")
    if name_el:
        commenter_name = (name_el.inner_text() or "").strip()
        href = name_el.evaluate("el => el.closest('a')?.href || ''") or ""
        m = re.search(r"facebook\.com/(?:profile\.php\?id=)?(\d+|[^/?#]+)", href)
        if m:
            commenter_id = m.group(1)

    content = ""
    for sel in ["div[dir='auto']", "span[dir='auto']"]:
        el = cel.query_selector(sel)
        if el:
            content = (el.inner_text() or "").strip()
            if content and len(content) > 1:
                break

    if not content:
        return None

    # Likes on comment
    likes_count = 0
    like_el = cel.query_selector("[aria-label*='like'], [aria-label*='thích']")
    if like_el:
        txt = like_el.get_attribute("aria-label") or ""
        nums = re.findall(r"\d+", txt)
        if nums:
            likes_count = int(nums[0])

    # Check verified badge
    is_verified = bool(cel.query_selector("svg[aria-label*='Verified'], [data-testid*='verified']"))

    # Check if reply (has parent)
    parent_comment_id = None
    try:
        is_reply = cel.evaluate("""
            el => {
                let p = el.parentElement;
                for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
                    if (p.getAttribute('role') === 'article' &&
                        p.querySelector('[role="article"]') === el) return true;
                }
                return false;
            }
        """)
        if is_reply:
            parent_comment_id = f"{post_id}_parent"
    except Exception:
        pass

    comment_id = f"{post_id}_c{idx}_{int(time.time()*1000) % 100000}"

    return {
        "comment_id": comment_id,
        "post_id": post_id,
        "parent_comment_id": parent_comment_id,
        "commenter_id": commenter_id,
        "commenter_name": commenter_name,
        "is_verified": is_verified,
        "content": content,
        "likes_count": likes_count,
        "replies_count": 0,
        "posted_at": "",
        "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class BrandScraper:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.headless = _get(self.cfg, "scraper", "headless", default=False)
        self.scroll_delay = _get(self.cfg, "scraper", "scroll_delay_ms", default=2500)
        self.max_posts = _get(self.cfg, "scraper", "max_posts", default=50)
        self.days_back = _get(self.cfg, "scraper", "days_back", default=7)
        self.timeout_s = _get(self.cfg, "scraper", "scrape_timeout_s", default=_SCRAPE_TIMEOUT_S)
        self.session_file = Path(
            _get(self.cfg, "facebook", "session_file",
                 default=str(_HERE / "sessions" / "fb_session.json"))
        )
        self.email = _get(self.cfg, "facebook", "email", default="") or os.environ.get("FB_EMAIL", "")
        self.password = _get(self.cfg, "facebook", "password", default="") or os.environ.get("FB_PASSWORD", "")

    def scrape(self, source_url: str, *, source_type: str = "group",
               with_comments: bool = False, max_comments: int = 30) -> dict:
        if not ("http" in source_url or "facebook.com" in source_url):
            source_url = f"https://www.facebook.com/groups/{source_url.strip()}"

        source_id = self._extract_source_id(source_url)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=self.days_back)
        posts: dict[str, dict] = {}
        all_comments: list[dict] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            # Session
            session_loaded = _load_session(context, self.session_file)
            if not session_loaded:
                if self.email and self.password:
                    _login(page, self.email, self.password)
                    if "login" not in page.url and "checkpoint" not in page.url:
                        _save_session(context, self.session_file)
                else:
                    _log.error("No session and no credentials.")
                    browser.close()
                    return {"posts": [], "comments": []}

            # Navigate
            feed_url = source_url if "?" in source_url else source_url.rstrip("/") + "/"
            _log.info("Navigating to %s", feed_url)
            page.goto(feed_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            # Handle login redirect
            if "login" in page.url or "checkpoint" in page.url:
                if self.session_file.exists():
                    self.session_file.unlink()
                context.clear_cookies()
                if self.email and self.password:
                    _login(page, self.email, self.password)
                    page.goto(feed_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(5000)
                else:
                    browser.close()
                    return {"posts": [], "comments": []}

            _dismiss_popups(page)
            _log.info("Page loaded: %s", page.url)

            # Scroll loop
            prev_count = 0
            stall_count = 0
            scrape_start = time.monotonic()

            while len(posts) < self.max_posts:
                elapsed = time.monotonic() - scrape_start
                if elapsed > self.timeout_s:
                    _log.warning("Timeout (%ds). Returning %d partial posts.", int(elapsed), len(posts))
                    break

                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                    page.wait_for_timeout(1200)
                except Exception:
                    pass

                # Find top-level posts
                try:
                    feed_el = page.query_selector("[role='feed']")
                    if not feed_el:
                        page.wait_for_timeout(3000)
                        continue
                    all_articles = feed_el.query_selector_all("div[role='article']")
                except Exception:
                    page.wait_for_timeout(3000)
                    continue

                top_level = []
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
                            top_level.append(art)
                    except Exception:
                        continue

                for el in top_level:
                    if len(posts) >= self.max_posts:
                        break
                    p = _parse_post(el, source_id)
                    if not p or p["post_id"] in posts:
                        continue

                    has_content = bool(p.get("content", "").strip())
                    has_ts = bool(p.get("posted_at", "").strip())
                    if p["post_id"].startswith("unknown_") and not has_content:
                        continue
                    if not has_content and not has_ts:
                        continue

                    # Date filter
                    if p["posted_at"]:
                        try:
                            ts = datetime.fromisoformat(p["posted_at"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                continue
                        except ValueError:
                            pass

                    posts[p["post_id"]] = p
                    _log.info("[%3d] %s | %s | r:%s c:%s",
                              len(posts), p["author_name"][:20],
                              (p["posted_at"] or "")[:10],
                              p["reactions_total"], p["comments_count"])

                    # Crawl comments if requested
                    if with_comments and p["comments_count"] > 0:
                        try:
                            cmnts = _parse_comments(page, el, p["post_id"], max_comments)
                            all_comments.extend(cmnts)
                            _log.info("  -> %d comments parsed", len(cmnts))
                        except Exception as e:
                            _log.debug("Comment parse error: %s", e)

                # Scroll
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    page.keyboard.press("End")
                page.wait_for_timeout(self.scroll_delay)
                try:
                    page.mouse.wheel(0, 800)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                # Stall detection
                if len(posts) == prev_count:
                    stall_count += 1
                    if stall_count >= _STALL_LIMIT:
                        _log.info("No new posts after %d scrolls. Stopping.", stall_count)
                        break
                else:
                    stall_count = 0
                prev_count = len(posts)

            browser.close()

        result_posts = list(posts.values())
        _log.info("Done. %d posts, %d comments from %s", len(result_posts), len(all_comments), source_id)
        return {"posts": result_posts, "comments": all_comments}

    @staticmethod
    def _extract_source_id(url: str) -> str:
        m = re.search(r"groups/([^/?#]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"facebook\.com/([^/?#]+)", url)
        if m:
            return m.group(1)
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", url)[-40:]
