"""
ai_query.py — Gemini-powered natural language query over the post database.

Flow:
  1. Parse question → detect time hints + keywords
  2. Fetch relevant posts from SQLite (FTS + time filter)
  3. Build system prompt + posts context
  4. Call Gemini API → return synthesized answer
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from log_config import get_logger
from llm_client import call_gemini

_log = get_logger("ai_query")

_CACHE_DIR = Path(__file__).parent / "data" / "cache"
_CIRCUIT_PATH = _CACHE_DIR / "llm_circuit.json"
_CACHE_TTL_MIN = 180
_CIRCUIT_MIN = 20

# ---------------------------------------------------------------------------
# Time hint detection
# ---------------------------------------------------------------------------

_TIME_PATTERNS: list[tuple[str, int]] = [
    # Vietnamese
    (r"hôm nay|today", 1),
    (r"hôm qua|yesterday", 2),
    (r"tuần (?:này|qua|trước)|this week|last week", 7),
    (r"tháng (?:này|qua|trước)|this month|last month", 30),
    (r"(\d+)\s*ngày|(\d+)\s*days?", 0),  # dynamic
    (r"(\d+)\s*tuần|(\d+)\s*weeks?", 0),  # dynamic
    (r"(\d+)\s*tháng|(\d+)\s*months?", 0),  # dynamic
]


def _detect_time_window(question: str) -> int | None:
    """Return number of days to look back, or None for all time."""
    q = question.lower()

    # Dynamic patterns: "3 ngày", "2 tuần", "1 tháng"
    m = re.search(r"(\d+)\s*(?:ngày|days?)", q)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:tuần|weeks?)", q)
    if m:
        return int(m.group(1)) * 7
    m = re.search(r"(\d+)\s*(?:tháng|months?)", q)
    if m:
        return int(m.group(1)) * 30

    # Static patterns
    for pattern, days in _TIME_PATTERNS:
        if days > 0 and re.search(pattern, q):
            return days

    return None


def _extract_search_terms(question: str) -> str | None:
    """Extract key search terms from question for FTS pre-filter."""
    # Remove Vietnamese stop words and question markers
    stops = {
        "gì", "nào", "nào", "như", "thế", "đó", "này", "là", "có",
        "được", "không", "cho", "của", "và", "với", "trong", "về",
        "từ", "đến", "tôi", "bạn", "mình", "ai", "sao", "the",
        "what", "how", "why", "when", "which", "who", "group",
        "bài", "đăng", "post", "posts", "top", "nhất", "hỏi",
        "xem", "liệt", "kê", "tất", "cả", "những", "các",
        "đang", "đã", "sẽ", "rồi", "chưa", "nhé",
    }
    words = re.findall(r"[\w]+", question.lower())
    terms = [w for w in words if w not in stops and len(w) > 1 and not w.isdigit()]
    return " ".join(terms[:5]) if terms else None


# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------

_MODEL_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
]


def _circuit_is_open() -> bool:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not _CIRCUIT_PATH.exists():
        return False
    try:
        data = json.loads(_CIRCUIT_PATH.read_text(encoding="utf-8"))
        until = data.get("open_until")
        if not until:
            return False
        return datetime.now(tz=timezone.utc) < datetime.fromisoformat(until)
    except Exception:
        return False


def _circuit_open(reason: str, minutes: int = _CIRCUIT_MIN) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CIRCUIT_PATH.write_text(
        json.dumps({
            "open_until": (datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)).isoformat(),
            "reason": reason[:300],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(group_id: str, question: str, days: int | None, model: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"[^\w\s]", " ", q, flags=re.U)
    q = re.sub(r"\s+", " ", q).strip()
    h = sha256()
    h.update((group_id or "").strip().lower().encode("utf-8"))
    h.update(q.encode("utf-8"))
    h.update(str(days or "").encode("utf-8"))
    h.update((model or "").strip().lower().encode("utf-8"))
    return h.hexdigest()[:24]


def _cache_load(key: str, ttl_minutes: int) -> dict[str, Any] | None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _CACHE_DIR / f"ask_{key}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = data.get("_cached_at")
        if not ts:
            return None
        if datetime.now(tz=timezone.utc) - datetime.fromisoformat(ts) > timedelta(minutes=ttl_minutes):
            return None
        return data
    except Exception:
        return None


def _cache_save(key: str, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = dict(payload)
    out["_cached_at"] = datetime.now(tz=timezone.utc).isoformat()
    (_CACHE_DIR / f"ask_{key}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _call_gemini(prompt: str, context: str, cfg: dict) -> str:
    """Call Gemini API with structured prompt. Circuit breaker on 429."""
    if _circuit_is_open():
        return "[LLM tạm tắt do rate limit. Thử lại sau hoặc dùng lệnh search/market/rag-query.]"

    full_prompt = f"{prompt}\n\n--- DỮ LIỆU ---\n{context}"

    def _truncate(p: str) -> str:
        marker = "\n\n--- DỮ LIỆU ---\n"
        if marker not in p:
            return p
        head, tail = p.split(marker, 1)
        return head + marker + tail[:8000]

    out = call_gemini(full_prompt, cfg=cfg, context_truncate_fn=_truncate)
    if out and ("rate limit" in out.lower() or "429" in out or "quota" in out.lower()):
        _circuit_open(out[:200])
    return out


# ---------------------------------------------------------------------------
# Main query function
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_VI = """Bạn là trợ lý phân tích dữ liệu Facebook Group. Bạn nhận được dữ liệu bài đăng từ database và câu hỏi từ người dùng.

Quy tắc:
- Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc
- Dựa hoàn toàn trên dữ liệu được cung cấp, không bịa thông tin
- Nếu dữ liệu không đủ để trả lời, nói rõ
- Dùng số liệu cụ thể khi có
- Khi nhắc đến số tương tác: chỉ dùng đúng số nguyên đã được cung cấp trong dữ liệu (reactions_total, comments_count). **Không tự thêm đơn vị như nghìn/triệu** nếu dữ liệu không có.
- Nếu số = 0 hoặc thiếu thì ghi đúng 0/không rõ, không suy đoán.
- Format: dùng bullet points, đánh số, hoặc bảng khi phù hợp
- Nếu người dùng hỏi về trends, so sánh theo thời gian
- Nếu hỏi về người dùng cụ thể, trích dẫn nội dung bài đăng
"""

_SYSTEM_PROMPT_EN = """You are a Facebook Group data analyst assistant. You receive post data from a database and a question from the user.

Rules:
- Answer based ONLY on the provided data, never fabricate
- Be concise and structured
- Use specific numbers when available
- Format: use bullet points, numbered lists, or tables as appropriate
- If data is insufficient, say so clearly
"""


def _format_posts_context(posts: list[dict], max_chars: int = 12000) -> str:
    """Format posts into a compact text context for the LLM (reduced to save tokens)."""
    lines = []
    total = 0
    for i, p in enumerate(posts):
        content = (p.get("content") or "")[:200]
        posted = p.get("posted_at") or p.get("scraped_at") or ""
        author = p.get("author") or "?"
        reactions = p.get("reactions", {})
        rtotal = reactions.get("total", 0) if isinstance(reactions, dict) else 0
        comments = p.get("comments_count", 0)

        line = (
            f"[{i+1}] {posted[:16]} | author={author} | "
            f"reactions_total={rtotal} comments_count={comments} | {content}"
        )
        total += len(line)
        if total > max_chars:
            lines.append(f"... ({len(posts) - i} bài nữa bị cắt do giới hạn context)")
            break
        lines.append(line)
    return "\n".join(lines)


def ask(
    group_id: str,
    question: str,
    cfg: dict,
) -> dict[str, Any]:
    """Answer a natural language question using posts from the database.

    Returns:
        {"answer": str, "posts_used": int, "time_window_days": int|None}
    """
    import db as database

    lang = cfg.get("gemini", {}).get("language", "vi")
    max_posts = cfg.get("gemini", {}).get("max_posts_per_query", 30)
    cache_ttl = int(cfg.get("gemini", {}).get("cache_ttl_min", _CACHE_TTL_MIN))

    # Step 1: Detect time window
    days = _detect_time_window(question)
    from_date = None
    if days:
        from_date = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()

    # Step 2: Try FTS search first for relevance
    search_terms = _extract_search_terms(question)
    posts = []
    if search_terms:
        try:
            posts = database.search_posts(group_id, search_terms, limit=max_posts)
        except Exception as e:
            _log.warning("FTS search failed: %s, falling back to time-based", e)

    # Step 3: If FTS returned too few, supplement with time-based query
    if len(posts) < max_posts:
        remaining = max_posts - len(posts)
        existing_ids = {p["post_id"] for p in posts}
        time_posts = database.get_posts(group_id, from_date=from_date, limit=remaining)
        for p in time_posts:
            if p["post_id"] not in existing_ids:
                posts.append(p)

    if not posts:
        return {
            "answer": f"Không tìm thấy bài đăng nào cho group '{group_id}'."
                      + (f" (time window: {days} ngày)" if days else ""),
            "posts_used": 0,
            "time_window_days": days,
        }

    # Step 4: Build prompt
    sys_prompt = _SYSTEM_PROMPT_VI if lang == "vi" else _SYSTEM_PROMPT_EN
    stats = database.get_stats(group_id)

    prompt = (
        f"{sys_prompt}\n\n"
        f"Group: {group_id}\n"
        f"Tổng bài trong DB: {stats.get('total_posts', '?')}\n"
        f"Khoảng thời gian: {stats.get('date_range', {}).get('from', '?')} → {stats.get('date_range', {}).get('to', '?')}\n"
        f"Bài được đưa vào context: {len(posts)}\n"
        + (f"Time filter: {days} ngày gần nhất\n" if days else "")
        + f"\nCÂU HỎI: {question}"
    )
    context = _format_posts_context(posts)

    # Step 5: Cache check then Call Gemini
    model_name = cfg.get("gemini", {}).get("model", "gemini-2.0-flash")
    ck = _cache_key(group_id, question, days, model_name)
    cached = _cache_load(ck, ttl_minutes=cache_ttl)
    if cached and cached.get("answer"):
        cached["cache_hit"] = True
        return cached

    answer = _call_gemini(prompt, context, cfg)

    result = {
        "answer": answer,
        "posts_used": len(posts),
        "time_window_days": days,
        "group_id": group_id,
        "cache_hit": False,
    }
    if answer and "rate limit" not in answer.lower() and "tạm tắt" not in answer.lower():
        _cache_save(ck, result)
    return result
