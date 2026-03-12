"""
gemini_analyzer.py — AI-powered analysis using Google Gemini API.

Uses google-genai SDK. Called by GroupAnalyzer.analyze_with_ai() when
GOOGLE_API_KEY is configured.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re

_log = logging.getLogger(__name__)

# Models tried in order — falls back if quota/model not available
_MODEL_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-latest",
]


def _extract_reactions(post: dict) -> int:
    r = post.get("reactions", 0)
    if isinstance(r, dict):
        return r.get("total", 0)
    return r or 0


def _posts_hash(posts: list[dict]) -> str:
    """Deterministic hash of the full post list for Gemini cache invalidation.
    Hash changes only when the set of post IDs changes (new posts scraped).
    """
    ids = sorted(p["post_id"] for p in posts if p.get("post_id"))
    return hashlib.md5("|".join(ids).encode("utf-8")).hexdigest()


def _build_prompt(posts: list[dict], group_id: str, rule_analysis: dict) -> str:
    # Top 30 by reactions + 20 random sample for diversity
    sorted_posts = sorted(posts, key=_extract_reactions, reverse=True)
    top_posts = sorted_posts[:30]
    others = [p for p in posts if p not in top_posts]
    sample = random.sample(others, min(20, len(others))) if others else []
    selected = top_posts + sample

    posts_text = ""
    for i, p in enumerate(selected[:50], 1):
        content = (p.get("content") or "").strip()[:300]
        if not content:
            continue
        posts_text += f"\n[{i}] (reactions={_extract_reactions(p)}) {content}\n"

    sentiment = rule_analysis.get("sentiment", {})
    topics = rule_analysis.get("topics", [])[:5]
    keywords = [k["keyword"] for k in rule_analysis.get("top_keywords", [])[:15]]

    return f"""Bạn là chuyên gia phân tích cộng đồng mạng xã hội Việt Nam.
Hãy phân tích nhóm Facebook ID: {group_id}

THỐNG KÊ:
- Tổng bài: {rule_analysis.get('total_posts', len(posts))}
- Sentiment: {sentiment.get('positive', 0)} tích cực / {sentiment.get('neutral', 0)} trung lập / {sentiment.get('negative', 0)} tiêu cực
- Chủ đề: {', '.join(t['topic'] for t in topics)}
- Từ khóa nổi bật: {', '.join(keywords)}

MẪU BÀI VIẾT ({len(selected)} bài - reactions cao nhất và ngẫu nhiên):
{posts_text}

Trả về JSON THUẦN (không markdown, không ```json) với cấu trúc:
{{
  "group_summary": "Nhóm về chủ đề gì, đối tượng thành viên ra sao (2-3 câu)",
  "key_themes": ["chủ đề chính 1", "2", "3", "4", "5"],
  "community_vibe": "Tone giọng, văn hóa, tính chất cộng đồng (2-3 câu)",
  "sentiment_insight": "Phân tích sâu cảm xúc thành viên — tại sao positive/negative/neutral (2-3 câu)",
  "top_concerns": ["vấn đề được quan tâm nhất 1", "2", "3"],
  "content_quality": "Tỉ lệ nội dung hữu ích vs giải trí vs spam (1-2 câu)",
  "recommendations": ["Gợi ý cho admin/marketer 1", "2", "3"],
  "notable_patterns": "Pattern đặc biệt hoặc insight thú vị (1-2 câu)"
}}"""


def analyze_with_gemini(
    posts: list[dict],
    group_id: str,
    rule_analysis: dict,
    cfg: dict,
    cached_insights: dict | None = None,
) -> dict | None:
    """Call Gemini API to generate AI insights.

    Returns a dict with AI insights, or None if API key not configured / all models fail.

    If cached_insights is provided and its _input_hash matches the current post list,
    the cached result is returned immediately without calling the API.
    """
    # Cache hit: same post set as last Gemini call → reuse cached insights
    current_hash = _posts_hash(posts)
    if cached_insights and cached_insights.get("_input_hash") == current_hash:
        _log.info("Gemini cache hit for group %s — reusing cached ai_insights.", group_id)
        return cached_insights

    gemini_cfg = cfg.get("gemini", {})
    api_key = gemini_cfg.get("api_key", "")
    if not api_key:
        _log.info("Gemini API key not configured — skipping AI analysis.")
        return None

    try:
        from google import genai
    except ImportError:
        _log.warning("google-genai not installed — skipping AI analysis.")
        return None

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(posts, group_id, rule_analysis)

    # Try configured model first, then fallbacks
    configured_model = gemini_cfg.get("model", "")
    models_to_try = ([configured_model] if configured_model else []) + [
        m for m in _MODEL_FALLBACKS if m != configured_model
    ]

    last_error = None
    for model_name in models_to_try:
        _log.info("Calling Gemini (%s) for AI analysis of group %s ...", model_name, group_id)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = response.text.strip()
            # Strip markdown code fences if Gemini wraps with them
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```\s*$", "", text.rstrip())
            result = json.loads(text)
            _log.info("Gemini AI analysis complete (model=%s).", model_name)
            result["_model_used"] = model_name
            result["_input_hash"] = current_hash
            return result
        except json.JSONDecodeError as exc:
            _log.warning("Gemini (%s) response not valid JSON (%s) — storing raw text.", model_name, exc)
            return {"raw_insight": response.text, "_model_used": model_name}
        except Exception as exc:
            err_str = str(exc)
            _log.warning("Gemini (%s) failed: %s", model_name, err_str[:200])
            last_error = err_str
            # Only try fallback on quota/availability errors
            if "429" in err_str or "quota" in err_str.lower() or "not found" in err_str.lower():
                continue
            break

    _log.warning("All Gemini models failed. Last error: %s", (last_error or "")[:200])
    return None
