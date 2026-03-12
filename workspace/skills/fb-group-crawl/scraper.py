"""
post_scraper.py — Scrape posts from a Facebook group using Playwright.

Flow:
  1. Load or create a Facebook session (login once, reuse cookies).
  2. Navigate to the group feed.
  3. Scroll + parse posts until max_posts or days_back limit is reached.
  4. Return a list of post dicts (see schema in SKILL.md).
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent


def _load_config() -> dict:
    from load_config import load_config
    return load_config()


def _get(cfg: dict, *keys, default=None):
    """Safe nested dict getter."""
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


def _parse_count(raw: str) -> int:
    """Convert '1.2K', '3,456', '1M' etc. to int."""
    if not raw:
        return 0
    raw = raw.strip().replace(",", "")
    m = re.match(r"([\d.]+)\s*([KMB]?)(?![a-zA-Z])", raw, re.I)
    if not m:
        return 0
    num, suffix = float(m.group(1)), m.group(2).upper()
    mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(num * mul)


def _detect_content_type(post_el) -> str:
    try:
        if post_el.query_selector("[data-sigil='inlineVideo'], video"):
            return "video"
        if post_el.query_selector("[data-sigil='photo-image'], img[class*='photo']"):
            return "image"
        if post_el.query_selector("a[href*='l.facebook.com']"):
            return "link"
    except Exception:
        pass
    return "text"


def _parse_media_expiry(url: str) -> str | None:
    """Parse Facebook CDN URL expiry from `oe=` hex timestamp param.
    Example: ...&oe=69ADD00C → 2026-03-04T... (Unix ts decoded from hex)
    Returns ISO-8601 string or None if not present.
    """
    m = re.search(r"\boe=([0-9A-Fa-f]{8,})\b", url)
    if not m:
        return None
    try:
        ts = int(m.group(1), 16)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None


def _looks_like_time_text(text: str) -> bool:
    """True if text looks like relative time or media duration — don't use as author."""
    if not text or len(text) > 50:
        return False
    t = text.strip().lower()
    if re.match(r"^\d+\s*(?:phút|minute|min|giờ|hour|h|ngày|day|d|tuần|week|tháng|month)\s*(?:trước|ago)?$", t):
        return True
    if t in ("just now", "vừa xong", "vừa", "vừa mới", "hôm qua", "yesterday", "today", "hôm nay"):
        return True
    if re.match(r"^\d+[hd]$", t):
        return True
    # Video/audio duration: "0:00 / 0:11", "1:23", "0:45 / 3:12"
    if re.match(r"^\d{1,2}:\d{2}(?:\s*/\s*\d{1,2}:\d{2})?$", t):
        return True
    # "See more", "Xem thêm" fragments sometimes appear alone
    if t in ("see more", "xem thêm", "…", "..."):
        return True
    return False


_VI_MONTHS = {
    "tháng 1": 1, "tháng 2": 2, "tháng 3": 3, "tháng 4": 4,
    "tháng 5": 5, "tháng 6": 6, "tháng 7": 7, "tháng 8": 8,
    "tháng 9": 9, "tháng 10": 10, "tháng 11": 11, "tháng 12": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_relative_time(text: str) -> datetime | None:
    """Parse Facebook timestamp text to UTC datetime.

    Handles:
    - Absolute VI first: '4 tháng 3, 2026 lúc 15:45', '4 tháng 3 lúc 9:30 SA'
    - Absolute EN first: 'March 4, 2026 at 9:45 AM', 'March 4 at 3:45 PM'
    - Special: 'Yesterday', 'Hôm qua', 'Today', 'Hôm nay', 'Just now', 'Vừa xong'
    - Relative: '2 giờ trước', '5 phút', '1 ngày', '3 weeks ago'
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    tl = text.lower()
    now = datetime.now(tz=timezone.utc)

    # ── absolute Vietnamese: "4 tháng 3, 2026 lúc 9:30" or "4 tháng 3 lúc 9:30 SA" ──
    # Must be checked BEFORE relative patterns to avoid "4 tháng" → "4 months ago"
    vi_m = re.search(
        r"(\d{1,2})\s+(tháng\s+\d{1,2})"
        r"(?:[, ]+(\d{4}))?(?:\s+lúc\s+(\d{1,2}):(\d{2})(?:\s*(sa|ch|am|pm))?)?",
        tl, re.I
    )
    if vi_m:
        try:
            day = int(vi_m.group(1))
            month_key = re.sub(r"\s+", " ", vi_m.group(2).strip())
            month = _VI_MONTHS.get(month_key, 0)
            year = int(vi_m.group(3)) if vi_m.group(3) else now.year
            hour = int(vi_m.group(4)) if vi_m.group(4) else 12
            minute = int(vi_m.group(5)) if vi_m.group(5) else 0
            meridiem = (vi_m.group(6) or "").lower()
            if meridiem in ("ch", "pm") and hour < 12:
                hour += 12
            elif meridiem in ("sa", "am") and hour == 12:
                hour = 0
            if month and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    # ── absolute English: "March 4, 2026 at 3:45 PM" or "March 4 at 3:45 PM" ──
    en_m = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
        r"\s+(\d{1,2})(?:,?\s*(\d{4}))?(?:\s+at\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?)?",
        tl, re.I
    )
    if en_m:
        try:
            month = _EN_MONTHS.get(en_m.group(1).lower(), 0)
            day = int(en_m.group(2))
            year = int(en_m.group(3)) if en_m.group(3) else now.year
            hour = int(en_m.group(4)) if en_m.group(4) else 12
            minute = int(en_m.group(5)) if en_m.group(5) else 0
            meridiem = (en_m.group(6) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            if month and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    # ── keyword shortcuts ─────────────────────────────────────────────────────
    if any(x in tl for x in ("just now", "vừa xong", "vừa mới", "vừa")):
        return now

    # "Hôm nay lúc 9:30" or just "Hôm nay"
    if "hôm nay" in tl or "today" in tl:
        t_m = re.search(r"lúc\s+(\d{1,2}):(\d{2})|at\s+(\d{1,2}):(\d{2})", tl)
        if t_m:
            h = int(t_m.group(1) or t_m.group(3))
            mn = int(t_m.group(2) or t_m.group(4))
            return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        return now.replace(hour=12, minute=0, second=0, microsecond=0)

    # "Hôm qua lúc 9:30" or just "Hôm qua"
    if "yesterday" in tl or "hôm qua" in tl:
        base = now - timedelta(days=1)
        t_m = re.search(r"lúc\s+(\d{1,2}):(\d{2})|at\s+(\d{1,2}):(\d{2})", tl)
        if t_m:
            h = int(t_m.group(1) or t_m.group(3))
            mn = int(t_m.group(2) or t_m.group(4))
            return base.replace(hour=h, minute=mn, second=0, microsecond=0)
        return base.replace(hour=12, minute=0, second=0, microsecond=0)

    # ── relative offsets ──────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*(?:giây|seconds?|sec)\s*(?:trước|ago)?", tl, re.I)
    if m:
        return now - timedelta(seconds=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:phút|minutes?|mins?)\s*(?:trước|ago)?", tl, re.I)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:giờ|hours?|hr)\b", tl, re.I)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"^(\d+)h$", tl.strip())
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:ngày|days?)\b", tl, re.I)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s*(?:tuần|weeks?)\b", tl, re.I)
    if m:
        return now - timedelta(weeks=int(m.group(1)))
    # Months relative only when followed by "trước" or "ago"
    m = re.search(r"(\d+)\s*(?:tháng|months?)\s+(?:trước|ago)", tl, re.I)
    if m:
        return now - timedelta(days=30 * int(m.group(1)))

    return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _save_session(context, session_path: Path):
    session_path.parent.mkdir(parents=True, exist_ok=True)
    cookies = context.cookies()
    session_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    _log.info("Session saved to %s", session_path)


def _load_session(context, session_path: Path) -> bool:
    if not session_path.exists():
        return False
    try:
        cookies = json.loads(session_path.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        _log.info("Session loaded from %s", session_path)
        return True
    except Exception as e:
        _log.warning("Session load failed: %s", e)
        return False


def _login(page: Page, email: str, password: str):
    _log.info("Logging in to Facebook...")
    page.goto("https://www.facebook.com/login/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Try multiple known selectors for the email field
    email_selectors = [
        "#email",
        "input[name='email']",
        "input[type='email']",
        "input[data-testid='royal_email']",
    ]
    pass_selectors = [
        "#pass",
        "input[name='pass']",
        "input[type='password']",
        "input[data-testid='royal_pass']",
    ]
    login_selectors = [
        "[name='login']",
        "button[type='submit']",
        "[data-testid='royal_login_button']",
        "button[id='loginbutton']",
        "[aria-label='Log in']",
        "[aria-label='Đăng nhập']",
        "div[role='button'][tabindex='0'][data-testid]",
        "form button",
        "form [role='button']",
    ]

    email_sel = None
    for sel in email_selectors:
        try:
            page.wait_for_selector(sel, timeout=5_000)
            email_sel = sel
            break
        except Exception:
            continue

    if not email_sel:
        _log.warning("Cannot find login form at %s. Maybe already logged in or page structure changed.", page.url)
        return

    # Click then fill email — ensures React form events fire correctly
    page.locator(email_sel).click()
    page.wait_for_timeout(500)
    page.locator(email_sel).fill(email)
    page.wait_for_timeout(500)

    # Find and fill password field
    pass_sel = None
    for sel in pass_selectors:
        try:
            page.wait_for_selector(sel, timeout=3_000)
            pass_sel = sel
            break
        except Exception:
            continue

    if pass_sel:
        page.locator(pass_sel).click()
        page.wait_for_timeout(500)
        page.locator(pass_sel).fill(password)
        page.wait_for_timeout(500)
    else:
        _log.warning("Cannot find password field — login may fail.")

    # Click submit button
    clicked = False
    for sel in login_selectors:
        btn = page.query_selector(sel)
        if btn:
            btn.click()
            clicked = True
            _log.info("Clicked login button: %s", sel)
            break
    if not clicked:
        _log.warning("Cannot find login submit button — pressing Enter as fallback.")
        page.keyboard.press("Return")

    # Wait for FB to redirect away from login page after form submit
    try:
        page.wait_for_url(lambda url: "login" not in url and "checkpoint" not in url, timeout=12_000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    # Handle 2FA / checkpoint if needed
    if "checkpoint" in page.url or "two_step" in page.url:
        _log.warning("Login requires 2FA/checkpoint. Complete verification in the browser window (up to 60s).")
        try:
            page.wait_for_url(lambda url: "checkpoint" not in url and "two_step" not in url, timeout=60_000)
        except Exception:
            _log.warning("Timed out waiting for 2FA verification. Proceeding anyway...")
    elif "login" in page.url:
        _log.warning("Login may have failed — still on login page after submit. Check credentials or CAPTCHA in browser.")

    _log.info("Current URL: %s", page.url)


def _dismiss_popups(page: Page):
    """Dismiss cookie consent, notification prompts, and other blocking overlays."""
    dismiss_selectors = [
        "div[role='dialog'] button[data-cookiebanner='accept_button']",
        "div[role='dialog'] [aria-label='Allow all cookies']",
        "div[role='dialog'] [aria-label='Decline optional cookies']",
        "div[role='dialog'] [aria-label='Close']",
        "div[role='dialog'] [aria-label='Not Now']",
        "div[role='dialog'] [aria-label='Không phải bây giờ']",
        "div[role='dialog'] [aria-label='Đóng']",
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                _log.info("Dismissed popup: %s", sel)
                page.wait_for_timeout(1000)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Post parsing
# ---------------------------------------------------------------------------

def _parse_post(post_el, group_id: str) -> dict[str, Any] | None:
    """Extract structured data from a single post element."""
    try:
        # ----- Post URL & ID: try all links and data attributes -----
        post_id = None
        post_url = ""
        for link in post_el.query_selector_all("a[href]"):
            href = link.get_attribute("href") or ""
            # Skip user profile links — these belong to comments/authors
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
        if not post_id:
            for attr in ("data-id", "data-story-id", "data-feedstorykey"):
                val = post_el.get_attribute(attr)
                if val and re.match(r"^\d+$", val):
                    post_id = val
                    break
        if not post_id:
            link_el = post_el.query_selector("a[href*='/posts/'], a[href*='story_fbid'], a[href*='permalink/']")
            if link_el:
                href = link_el.get_attribute("href") or ""
                post_url = re.sub(r"\?.*$", "", href).rstrip("/")
                post_id = re.search(r"story_fbid=(\d+)|/(?:posts|permalink)/(\d+)", href)
                if post_id:
                    post_id = post_id.group(1) or post_id.group(2)
        if not post_id:
            aria = post_el.get_attribute("aria-label") or ""
            post_id = re.sub(r"\W+", "_", aria)[:40] or f"unknown_{int(time.time() * 1000)}"

        # ----- Author: multiple selectors; skip action links and time-like text -----
        skip_texts = {"like", "comment", "share", "see more", "xem thêm", "more", "reaction", "phản hồi", "bình luận", "chia sẻ"}
        author = "Unknown"
        author_id = ""
        for sel in [
            "h2 a", "h3 a", "h4 a", "strong a", "[data-hovercard] a",
            "a[role='link'][href*='facebook.com']",
            "div[role='article'] > div > div a[role='link']",
            "span strong a", "a[href*='profile.php'], a[href*='user/']",
        ]:
            try:
                for el in post_el.query_selector_all(sel):
                    txt = (el.inner_text() or "").strip()
                    if not txt or len(txt) > 100:
                        continue
                    if any(s in txt.lower() for s in skip_texts):
                        continue
                    if re.match(r"^[\d\s,]+$", txt):
                        continue
                    if _looks_like_time_text(txt):
                        continue
                    href = el.get_attribute("href") or ""
                    if "/posts/" in href or "story_fbid" in href or "permalink" in href:
                        continue
                    author = txt
                    aid_match = re.search(r"/(?:profile\.php\?id=)?(\d+)|/([\w.]+)(?:\?|$)", href)
                    if aid_match:
                        author_id = (aid_match.group(1) or aid_match.group(2) or "").strip()
                    break
            except Exception:
                continue
            if author != "Unknown":
                break

        # ----- Timestamp: data-utime → link aria-label → JS text scan -----
        timestamp = ""
        # 1. Legacy data-utime attributes (old Facebook)
        time_el = post_el.query_selector("abbr[data-utime], abbr[data-store], span[data-utime], [data-store*='time']")
        if time_el:
            utime = time_el.get_attribute("data-utime") or time_el.get_attribute("data-store")
            if utime and str(utime).isdigit():
                timestamp = datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()

        # 2. aria-label on post permalink link (Facebook 2024+ React DOM)
        if not timestamp:
            for link in post_el.query_selector_all("a[href*='/posts/'], a[href*='story_fbid']"):
                try:
                    label = link.get_attribute("aria-label") or ""
                    if label and 3 < len(label) < 120:
                        dt = _parse_relative_time(label)
                        if dt:
                            timestamp = dt.isoformat()
                            break
                except Exception:
                    continue

        # 3. Visible text in known selectors
        if not timestamp:
            for sel in ["abbr", "span[role='text']", "a[role='link'] span", "span.x4k7w5x"]:
                try:
                    el = post_el.query_selector(sel)
                    if el:
                        txt = (el.inner_text() or "").strip()
                        if txt and len(txt) < 80:
                            dt = _parse_relative_time(txt)
                            if dt:
                                timestamp = dt.isoformat()
                                break
                except Exception:
                    continue

        # 4. JS full-DOM span scan — finds relative/absolute time in any span
        if not timestamp:
            try:
                found = post_el.evaluate(r"""
                    el => {
                        const TIME_RE = /phút|minute|min|giờ|hour|ngày|day|tuần|week|tháng|month|giây|second|hôm qua|yesterday|just now|vừa|lúc \d|at \d/i;
                        const spans = el.querySelectorAll('span, abbr, a[aria-label]');
                        for (const s of spans) {
                            const t = (s.getAttribute('aria-label') || s.textContent || '').trim();
                            if (t.length > 2 && t.length < 100 && TIME_RE.test(t)) return t;
                        }
                        return '';
                    }
                """)
                if found:
                    dt = _parse_relative_time(found)
                    if dt:
                        timestamp = dt.isoformat()
            except Exception:
                pass

        # 5. Any element with data-utime in the subtree (legacy or mobile)
        if not timestamp:
            try:
                utime_el = post_el.query_selector("[data-utime]")
                if utime_el:
                    utime = utime_el.get_attribute("data-utime")
                    if utime and str(utime).isdigit():
                        timestamp = datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
            except Exception:
                pass

        # Click "See more" / "Xem thêm" to expand collapsed content
        try:
            see_more = post_el.query_selector(
                "div[role='button']:has-text('See more'), "
                "div[role='button']:has-text('Xem thêm'), "
                "span:has-text('See more'), "
                "span:has-text('Xem thêm')"
            )
            if see_more and see_more.is_visible():
                see_more.click(timeout=2000)
                time.sleep(0.3)
        except Exception:
            pass

        # Content text — strict selectors first, exclude comment zones
        _COMMENT_ZONES = (
            "[aria-label*='comment' i]",
            "[aria-label*='bình luận']",
            "[data-testid*='UFI2Comments']",
            "div[role='article'] div[role='article']",
        )
        content = ""
        for sel in [
            "[data-ad-comet-preview='message']",
            "[data-testid='post_message']",
            "div[class*='userContent']",
        ]:
            el = post_el.query_selector(sel)
            if el:
                content = el.inner_text().strip()
                if content:
                    break

        # Fallback: div[dir='auto'] but only the FIRST one not inside a comment zone
        if not content:
            try:
                candidates = post_el.query_selector_all("div[dir='auto']")
                for cand in candidates:
                    in_comment = False
                    for cz in _COMMENT_ZONES:
                        try:
                            parent_match = cand.evaluate(
                                f"el => !!el.closest('{cz}')"
                            )
                            if parent_match:
                                in_comment = True
                                break
                        except Exception:
                            continue
                    if in_comment:
                        continue
                    txt = (cand.inner_text() or "").strip()
                    if txt and len(txt) > 5:
                        _ui_noise = {"like", "comment", "share", "see more", "xem thêm",
                                     "write a comment", "viết bình luận", "most relevant",
                                     "phù hợp nhất", "all comments", "tất cả bình luận"}
                        if txt.lower().strip() not in _ui_noise:
                            content = txt
                            break
            except Exception:
                pass

        # Reactions — CSS selectors first, then JS full-DOM scan
        reaction_count = 0
        for sel in [
            "[aria-label*='reaction']",
            "[aria-label*='reacted']",
            "[aria-label*='lượt cảm xúc']",
            "[aria-label*='cảm xúc']",
            "[data-testid='UFI2ReactionsCount/root']",
            "[data-testid='UFI2ReactionsCount']",
        ]:
            el = post_el.query_selector(sel)
            if el:
                txt = el.get_attribute("aria-label") or el.inner_text()
                nums = re.findall(r"[\d,.]+\s*[KMBkmb]?", txt.replace("\u00a0", " "))
                if nums:
                    reaction_count = _parse_count(nums[0].strip())
                    if reaction_count:
                        break

        if not reaction_count:
            try:
                raw = post_el.evaluate(r"""
                    el => {
                        // 1. aria-label with reaction keywords
                        const all = el.querySelectorAll('[aria-label]');
                        for (const e of all) {
                            const lbl = e.getAttribute('aria-label') || '';
                            if (/react|reacted|lượt cảm xúc|cảm xúc/i.test(lbl)) {
                                const m = lbl.match(/([\d,.\u00a0]+\s*[KMBkmb]?)/);
                                if (m) return m[1].replace(/\u00a0/g, '');
                            }
                        }
                        // 2. reaction count span: small number near emoji images
                        const imgs = el.querySelectorAll('img[alt*="reaction"], img[alt*="Like"], img[alt*="Love"]');
                        for (const img of imgs) {
                            let sib = img.nextElementSibling;
                            for (let i = 0; i < 4 && sib; i++, sib = sib.nextElementSibling) {
                                const t = sib.textContent.trim();
                                if (/^[\d,.]+[KMBkmb]?$/.test(t)) return t;
                            }
                            let parent = img.parentElement;
                            for (let i = 0; i < 4 && parent; i++, parent = parent.parentElement) {
                                const spans = parent.querySelectorAll('span');
                                for (const s of spans) {
                                    const t = s.textContent.trim();
                                    if (/^[\d,.]+[KMBkmb]?$/.test(t) && t !== '0') return t;
                                }
                            }
                        }
                        return '';
                    }
                """)
                if raw:
                    reaction_count = _parse_count(raw.strip())
            except Exception:
                pass

        # Comments
        comments_count = 0
        for sel in [
            "a[href*='comment']",
            "[aria-label*='comment']",
            "[aria-label*='bình luận']",
            "[data-testid*='comment-count']",
        ]:
            el = post_el.query_selector(sel)
            if el:
                txt = el.get_attribute("aria-label") or el.inner_text()
                nums = re.findall(r"[\d,.]+[KMBkmb]?", txt)
                if nums:
                    comments_count = _parse_count(nums[0])
                    if comments_count:
                        break

        if not comments_count:
            try:
                raw = post_el.evaluate(r"""
                    el => {
                        const all = el.querySelectorAll('[aria-label]');
                        for (const e of all) {
                            const lbl = e.getAttribute('aria-label') || '';
                            if (/comment|bình luận/i.test(lbl)) {
                                const m = lbl.match(/([\d,.\u00a0]+\s*[KMBkmb]?)/);
                                if (m) return m[1].replace(/\u00a0/g, '');
                            }
                        }
                        return '';
                    }
                """)
                if raw:
                    comments_count = _parse_count(raw.strip())
            except Exception:
                pass

        # Shares
        shares_count = 0
        for sel in [
            "a[href*='share']",
            "[aria-label*='share']",
            "[aria-label*='chia sẻ']",
            "[data-testid*='share-count']",
        ]:
            el = post_el.query_selector(sel)
            if el:
                txt = el.get_attribute("aria-label") or el.inner_text()
                nums = re.findall(r"[\d,.]+[KMBkmb]?", txt)
                if nums:
                    shares_count = _parse_count(nums[0])
                    if shares_count:
                        break

        # Media — with CDN expiry timestamp parsed from oe= param
        media = []
        for img in post_el.query_selector_all("img[src*='fbcdn'], img[src*='facebook']"):
            src = img.get_attribute("src") or ""
            if src and "emoji" not in src and "reaction" not in src and "static" not in src:
                item: dict = {"type": "image", "url": src}
                expiry = _parse_media_expiry(src)
                if expiry:
                    item["expires_at"] = expiry
                media.append(item)

        content_type = _detect_content_type(post_el)
        # Detect image-only posts (has media but no meaningful text)
        if not content.strip() and media:
            content_type = "image_only"

        # Sanity: log raw metrics text for debugging if suspiciously high
        if comments_count > 100_000 or reaction_count > 100_000 or shares_count > 100_000:
            _log.warning(
                "Suspicious metrics for post %s: react=%s cmt=%s share=%s",
                post_id, reaction_count, comments_count, shares_count,
            )

        return {
            "post_id": post_id,
            "group_id": group_id,
            "author": author,
            "author_id": author_id,
            "content": content,
            "media": media,
            "reactions": {
                "total": reaction_count,
                "like": 0, "love": 0, "haha": 0, "wow": 0, "sad": 0, "angry": 0,
            },
            "comments_count": comments_count,
            "shares_count": shares_count,
            "post_url": post_url,
            "timestamp": timestamp,
            "content_type": content_type,
            "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        _log.debug("Error parsing post: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

class GroupPostScraper:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or _load_config()
        self.headless: bool = _get(self.cfg, "scraper", "headless", default=False)
        self.scroll_delay: int = _get(self.cfg, "scraper", "scroll_delay_ms", default=2000)
        self.max_posts: int = _get(self.cfg, "scraper", "max_posts", default=500)
        self.days_back: int = _get(self.cfg, "scraper", "days_back", default=30)
        self.skip_low_quality: bool = _get(self.cfg, "scraper", "skip_low_quality", default=True)
        self.session_file = Path(
            _get(self.cfg, "facebook", "session_file", default=str(_HERE / "sessions" / "fb_session.json"))
        )
        self.email: str = _get(self.cfg, "facebook", "email", default="")
        self.password: str = _get(self.cfg, "facebook", "password", default="")

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
            user = proxy_cfg.get("username", os.environ.get("PROXY_USERNAME", ""))
            pwd = proxy_cfg.get("password", os.environ.get("PROXY_PASSWORD", ""))
            self.proxy = {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": pwd,
            }

    # -----------------------------------------------------------------------

    def scrape(self, group_url: str, run_id: str | None = None, stop_at_post_id: str | None = None) -> list[dict]:
        """Scrape posts from a Facebook group URL or group ID. Returns list of post dicts.
        Optionally accepts run_id for data lineage — each post will carry scrape_run_id.
        stop_at_post_id: if set, scraping stops as soon as this post_id is seen
            (incremental mode — avoids re-fetching already-stored posts).
        """
        if not ("http" in group_url or "facebook.com" in group_url):
            group_url = f"https://www.facebook.com/groups/{group_url.strip()}"
        group_id = self._extract_group_id(group_url)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=self.days_back)
        posts: dict[str, dict] = {}  # post_id → post (dedup)
        reached_cursor = False        # set True when stop_at_post_id found

        if stop_at_post_id:
            _log.info("Incremental mode: will stop at post_id=%s", stop_at_post_id)

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
                viewport={"width": 1280, "height": 800},
            )
            # Stealth: hide webdriver flag
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
                    # Verify login before saving session
                    if "login" not in page.url and "checkpoint" not in page.url:
                        _save_session(context, self.session_file)
                    else:
                        _log.warning("Initial login may not have succeeded — skipping session save.")
                else:
                    _log.error("No session and no credentials. Set FB_EMAIL/FB_PASSWORD in env or config.")
                    browser.close()
                    return []

            # Navigate to group (keep query e.g. ?sorting_setting=CHRONOLOGICAL)
            if "?" in group_url:
                feed_url = group_url.strip()
            else:
                feed_url = group_url.rstrip("/") + "/"
            _log.info("Navigating to %s", feed_url)
            page.goto(feed_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            # Detect login needed: URL redirect OR login modal/popup on page
            needs_login = False
            if "login" in page.url or "checkpoint" in page.url:
                needs_login = True
                _log.warning("Redirected to login URL — session expired.")
            else:
                login_modal = page.query_selector(
                    "div[role='dialog'] input[name='email'], "
                    "div[role='dialog'] input[type='email'], "
                    "form[action*='login'] input[name='email'], "
                    "div[data-testid='login_form']"
                )
                if login_modal:
                    needs_login = True
                    _log.warning("Login modal/popup detected — session expired.")

            if needs_login:
                # Delete stale session and clear cookies from browser context
                if self.session_file.exists():
                    self.session_file.unlink()
                    _log.info("Deleted stale session file.")
                context.clear_cookies()
                _log.info("Cleared stale cookies from browser context.")
                if self.email and self.password:
                    # Dismiss modal if present, then do a clean login
                    try:
                        close_btn = page.query_selector(
                            "div[role='dialog'] [aria-label='Close'], "
                            "div[role='dialog'] div[role='button']:has(svg)"
                        )
                        if close_btn:
                            close_btn.click()
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    _login(page, self.email, self.password)

                    # Verify login: visit home first to stabilize session
                    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    if "login" in page.url or "checkpoint" in page.url:
                        _log.error("Login failed — still redirected to login after credentials submitted.")
                        browser.close()
                        return []
                    _save_session(context, self.session_file)
                    _dismiss_popups(page)

                    # Now navigate to group
                    page.goto(feed_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(6000)
                    _dismiss_popups(page)
                else:
                    _log.error("Login required but no credentials configured.")
                    browser.close()
                    return []
            else:
                _dismiss_popups(page)

            _log.info("Page URL: %s", page.url)

            prev_count = 0
            stall_count = 0
            _scrape_start = time.monotonic()
            _SCRAPE_TIMEOUT_S = 120  # hard cap: 2 minutes, return partial data after

            while len(posts) < self.max_posts:
                elapsed = time.monotonic() - _scrape_start
                if elapsed > _SCRAPE_TIMEOUT_S:
                    _log.warning(
                        "Scrape timeout (%ds). Returning %d partial posts.",
                        int(elapsed), len(posts),
                    )
                    break
                # Wait for page to settle after scrolls/navigations
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8_000)
                    page.wait_for_timeout(1200)
                except Exception:
                    pass

                # Parse visible posts — only feed-level articles (NOT comments)
                # Strategy: find articles inside [role="feed"], then exclude any
                # article whose ancestor chain hits another article before the feed.
                try:
                    feed_el = page.query_selector("[role='feed']")
                    if not feed_el:
                        _log.warning("No [role='feed'] found on page")
                        page.wait_for_timeout(3000)
                        continue
                    all_articles = feed_el.query_selector_all("div[role='article']")
                except Exception as nav_err:
                    _log.warning("Context destroyed (navigation?), retrying... %s", nav_err)
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

                _log.debug("Feed articles: %s total, %s top-level (post)", len(all_articles), len(top_level_els))

                reached_cutoff = False
                skipped_unknown = 0
                skipped_low_q = 0
                for el in top_level_els:
                    try:
                        p = _parse_post(el, group_id)
                    except Exception:
                        continue
                    if not p:
                        continue
                    if p["post_id"] in posts:
                        continue

                    # QC: reject entries that are actually comments (user profile links)
                    purl = p.get("post_url") or ""
                    if "/user/" in purl and "/posts/" not in purl and "permalink" not in purl:
                        skipped_low_q += 1
                        continue

                    # QC: reject comment cards shown as feed items (Reply button, no Comment button)
                    # Chronological feeds surface recent comment activity — these are NOT original posts
                    # NOTE: only scan buttons at the direct article level — skip buttons nested inside
                    # expanded comment sections (role="article") to avoid false positives.
                    try:
                        action_info = el.evaluate("""
                            el => {
                                let hasReply = false, hasComment = false;
                                const found = [];
                                const buttons = el.querySelectorAll(
                                    'div[role="button"],a[role="link"],span[role="button"]'
                                );
                                for (const btn of buttons) {
                                    // Skip buttons inside a nested article (expanded comment section)
                                    let p = btn.parentElement, inNested = false;
                                    while (p && p !== el) {
                                        if (p.getAttribute('role') === 'article') { inNested = true; break; }
                                        p = p.parentElement;
                                    }
                                    if (inNested) continue;
                                    // Check both textContent and aria-label with includes for robustness
                                    const text = (btn.textContent || '').trim().toLowerCase();
                                    const label = (btn.getAttribute('aria-label') || '').trim().toLowerCase();
                                    const combined = text + ' ' + label;
                                    if (text.length > 0 && text.length < 30) found.push(text || label);
                                    if (combined.includes('reply') || combined.includes('phản hồi')) hasReply = true;
                                    if (combined.includes('comment') || combined.includes('bình luận')) hasComment = true;
                                }
                                return { hasReply, hasComment, found };
                            }
                        """)
                        _log.debug("Comment filter [%s]: hasReply=%s hasComment=%s buttons=%s",
                                   p.get("post_id","?")[:12],
                                   action_info.get("hasReply"), action_info.get("hasComment"),
                                   action_info.get("found", [])[:6])
                        if action_info.get("hasReply") and not action_info.get("hasComment"):
                            skipped_low_q += 1
                            continue
                    except Exception:
                        pass

                    # QC: skip low-quality posts
                    if self.skip_low_quality:
                        has_content = bool((p.get("content") or "").strip())
                        has_ts = bool((p.get("timestamp") or "").strip())
                        is_fallback_id = (p.get("post_id") or "").startswith("unknown_")
                        if is_fallback_id and not has_content:
                            skipped_unknown += 1
                            continue
                        if not has_content and not has_ts:
                            skipped_low_q += 1
                            continue

                    # Date filter
                    if p["timestamp"]:
                        try:
                            ts = datetime.fromisoformat(p["timestamp"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                reached_cutoff = True
                                continue
                        except ValueError:
                            pass

                    if run_id:
                        p["scrape_run_id"] = run_id
                    posts[p["post_id"]] = p
                    _log.info("[%4d] %s | %s | r:%s", len(posts), p["author"][:30], p["timestamp"][:10] if p["timestamp"] else "", p["reactions"]["total"])

                    # Incremental stop: we've seen the last known post → no older posts needed
                    if stop_at_post_id and p["post_id"] == stop_at_post_id:
                        _log.info("Reached cursor post_id=%s — stopping incremental scrape.", stop_at_post_id)
                        reached_cursor = True
                        break

                if skipped_unknown or skipped_low_q:
                    _log.debug("Skipped this round: %s unknown_id, %s low_quality", skipped_unknown, skipped_low_q)

                if reached_cursor:
                    _log.info("Incremental scrape complete: %s new posts collected.", len(posts))
                    break

                if reached_cutoff:
                    _log.info("Reached date cutoff. Stopping.")
                    break

                if len(posts) >= self.max_posts:
                    _log.info("Reached max_posts=%s. Stopping.", self.max_posts)
                    break

                # Scroll down — multiple methods for Facebook lazy load
                try:
                    page.evaluate("""
                        (() => {
                            const feed = document.querySelector('[role="feed"]');
                            if (feed) {
                                feed.scrollTop = feed.scrollHeight;
                            }
                            window.scrollTo(0, document.body.scrollHeight);
                        })()
                    """)
                except Exception:
                    page.keyboard.press("End")
                page.wait_for_timeout(self.scroll_delay)
                # Second micro-scroll to trigger additional lazy load
                try:
                    page.mouse.wheel(0, 800)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                # Stall detection (tolerate 4 stalls before giving up)
                if len(posts) == prev_count:
                    stall_count += 1
                    if stall_count >= 4:
                        _log.info("No new posts after %s scrolls. Stopping.", stall_count)
                        break
                    _log.debug("Stall %s/4 (still at %s posts)", stall_count, len(posts))
                else:
                    stall_count = 0
                prev_count = len(posts)

            browser.close()

        result = list(posts.values())
        _log.info("Done. Collected %s posts from %s.", len(result), group_id)
        return result

    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_group_id(group_url: str) -> str:
        """Extract a safe group identifier string from URL."""
        m = re.search(r"groups/([^/?#]+)", group_url)
        if m:
            return m.group(1)
        m = re.search(r"facebook\.com/([^/?#]+)", group_url)
        if m:
            return m.group(1)
        return re.sub(r"[^a-zA-Z0-9_-]", "_", group_url)[-40:]
