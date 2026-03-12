"""
pain_extractor.py — Objective 1: Market Insight pain point extraction.

Detects posts where members express frustration, confusion, unmet needs,
or seek solutions — key signals for market research and product gaps.

Pain categories:
  - Frustration / complaint
  - Question / need help
  - Comparison / searching for alternatives
  - Price sensitivity
"""
from __future__ import annotations

import re
from collections import Counter

# ---------------------------------------------------------------------------
# Signal dictionaries
# ---------------------------------------------------------------------------

# Frustration / complaint signals
_FRUSTRATION = [
    "bực", "bực mình", "khó chịu", "chán", "thất vọng", "tức", "tức quá",
    "phiền", "phiền quá", "tệ", "tệ quá", "kém", "dở", "dở tệ", "dở quá",
    "xấu", "xấu quá", "lừa đảo", "scam", "giả mạo", "fake", "ảo",
    "chậm", "chậm quá", "trễ", "trề", "không giao", "không ship",
    "đắt", "đắt quá", "chặt chém", "móc túi", "cắt cổ",
    "vỡ", "hỏng", "hư", "lỗi", "bug", "sai", "nhầm",
    "không hài lòng", "không ổn", "không được", "không dùng được",
    "cảnh báo", "cẩn thận", "tránh xa", "đừng mua", "đừng dùng",
    "phàn nàn", "khiếu nại", "bức xúc", "ức chế",
]

# Need / seeking help signals
_NEED_HELP = [
    "ai biết", "ai biết không", "cần giúp", "help me", "giúp mình",
    "tư vấn giúp", "cho hỏi", "hỏi chút", "hỏi ngu",
    "làm sao", "làm thế nào", "cách nào", "bí cách",
    "không biết", "chưa biết", "mù tịt", "mù quờ",
    "kinh nghiệm không", "ai có kinh nghiệm",
    "recommend", "gợi ý", "đề xuất", "tư vấn',",
    "hướng dẫn", "chỉ mình", "chỉ với",
]

# Comparison / search for alternative signals
_COMPARISON = [
    "so sánh", "cái nào tốt hơn", "cái nào ngon hơn", "nên chọn",
    "nên mua cái nào", "thay thế", "thay bằng", "thay cho",
    "tương đương", "tương tự", "giống như", "như vậy",
    "brand nào", "hãng nào", "loại nào", "cửa hàng nào",
    "chỗ nào bán", "mua ở đâu", "mua chỗ nào",
    "không thích", "không phù hợp", "không hợp",
    "đổi sang", "chuyển sang",
]

# Price sensitivity signals
_PRICE = [
    "giá bao nhiêu", "bao nhiêu tiền", "tầm bao nhiêu", "khoảng bao nhiêu",
    "giá rẻ hơn", "rẻ hơn không", "có giá tốt không",
    "tiết kiệm", "budget", "hạn hẹp", "eo hẹp",
    "không đủ tiền", "hết tiền", "nghèo quá", "túi rỗng",
    "đắt quá mua không được", "vượt ngân sách",
]

# Pain category mapping
_CATEGORIES: dict[str, list[str]] = {
    "frustration": _FRUSTRATION,
    "need_help": _NEED_HELP,
    "comparison": _COMPARISON,
    "price_sensitivity": _PRICE,
}


def _detect_pain_category(text: str) -> list[str]:
    """Return list of matched pain categories for a post."""
    t = text.lower()
    matched = []
    for cat, signals in _CATEGORIES.items():
        if any(sig in t for sig in signals):
            matched.append(cat)
    return matched


def _pain_score(text: str) -> float:
    """0.0–1.0 pain signal score based on category hits."""
    if not text:
        return 0.0
    cats = _detect_pain_category(text)
    return min(1.0, len(cats) / 3)


class PainExtractor:
    """Extract posts expressing pain points, frustration, or unmet needs."""

    def __init__(self, min_score: float = 0.3):
        self.min_score = min_score

    def extract(self, posts: list[dict]) -> list[dict]:
        """Return posts with pain signals, enriched with pain metadata.

        Each returned post has:
          pain_score   : float 0–1
          pain_categories: list of matched categories
        """
        results = []
        for p in posts:
            text = p.get("content", "")
            categories = _detect_pain_category(text)
            if not categories:
                continue
            score = min(1.0, len(categories) / 3)
            if score < self.min_score:
                continue
            results.append({
                "post_id": p.get("post_id"),
                "author": p.get("author", "Unknown"),
                "post_url": p.get("post_url", ""),
                "preview": text[:150].replace("\n", " "),
                "pain_score": round(score, 2),
                "pain_categories": categories,
                "reactions": p.get("reactions", {}).get("total", 0)
                    if isinstance(p.get("reactions"), dict) else 0,
                "comments_count": p.get("comments_count", 0),
            })

        # Sort by pain_score × reactions for highest-impact pain points
        results.sort(
            key=lambda x: (x["pain_score"] * 3 + x["reactions"] * 0.01),
            reverse=True,
        )
        return results

    def summarize(self, posts: list[dict]) -> dict:
        """Category breakdown summary for the report."""
        cat_counter: Counter = Counter()
        for p in posts:
            for cat in _detect_pain_category(p.get("content", "")):
                cat_counter[cat] += 1

        total = len(posts) or 1
        top_pain = self.extract(posts)[:10]

        return {
            "total_pain_posts": len(top_pain),
            "category_breakdown": {
                cat: {"count": cnt, "pct": round(cnt / total * 100, 1)}
                for cat, cnt in cat_counter.most_common()
            },
            "top_pain_posts": top_pain,
        }
