"""
text_analysis.py — Sentiment, keyword extraction, topic clustering, hashtag/mention parsing.

All rule-based (no LLM required). Vietnamese + English support.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from log_config import get_logger

_log = get_logger("text_analysis")

# ---------------------------------------------------------------------------
# Sentiment analysis (rule-based VI/EN)
# ---------------------------------------------------------------------------

_POSITIVE_VI = {
    "tốt", "đẹp", "thích", "yêu", "hay", "chất lượng", "xuất sắc", "tuyệt vời",
    "ưng", "ok", "ổn", "nên mua", "recommend", "đáng tiền", "hài lòng", "mê",
    "xịn", "phê", "ngon", "chuẩn", "perfect", "amazing", "great", "good",
    "love", "best", "worth", "sạch", "nhanh", "đúng hẹn", "giao nhanh",
    "đóng gói cẩn thận", "chăm sóc tốt", "dễ thương", "cute",
}

_NEGATIVE_VI = {
    "tệ", "xấu", "chán", "kém", "dở", "tốn", "đắt", "lỗi", "hỏng", "gãy",
    "chậm", "trễ", "sai", "nhầm", "rách", "thất vọng", "bực", "tức",
    "không nên", "đừng mua", "scam", "lừa", "fake", "giả", "mỏng",
    "bong tróc", "phai màu", "co rút", "rách", "hôi", "bad", "worst",
    "terrible", "hate", "ugly", "poor", "broken", "damaged", "disappointed",
    "ship chậm", "hàng lỗi", "không giống", "sai size", "size không chuẩn",
    "không đáng", "phí tiền", "giao sai", "thiếu hàng",
}

_INTENSIFIERS = {"rất", "cực", "quá", "siêu", "vô cùng", "hết sức", "very", "so", "extremely"}
_NEGATORS = {"không", "chẳng", "chả", "đừng", "ko", "k", "not", "no", "never", "don't"}


def analyze_sentiment(text: str) -> dict:
    words = text.lower().split()
    word_set = set(words)
    text_lower = text.lower()

    pos_score = sum(1 for w in _POSITIVE_VI if w in text_lower)
    neg_score = sum(1 for w in _NEGATIVE_VI if w in text_lower)

    has_negator = bool(word_set & _NEGATORS)
    has_intensifier = bool(word_set & _INTENSIFIERS)

    if has_negator:
        pos_score, neg_score = neg_score, pos_score

    if has_intensifier:
        if pos_score > neg_score:
            pos_score *= 1.5
        elif neg_score > pos_score:
            neg_score *= 1.5

    total = pos_score + neg_score
    if total == 0:
        return {"label": "neutral", "score": 0.0, "positive": 0, "negative": 0}

    score = (pos_score - neg_score) / total
    label = "positive" if score > 0.15 else ("negative" if score < -0.15 else "neutral")
    return {"label": label, "score": round(score, 3), "positive": pos_score, "negative": neg_score}


def analyze_sentiment_batch(texts: list[str]) -> dict:
    results = [analyze_sentiment(t) for t in texts]
    counts = Counter(r["label"] for r in results)
    total = len(results) or 1
    avg_score = sum(r["score"] for r in results) / total

    return {
        "total_analyzed": len(results),
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
        "positive_pct": round(counts.get("positive", 0) / total * 100, 1),
        "negative_pct": round(counts.get("negative", 0) / total * 100, 1),
        "avg_score": round(avg_score, 3),
    }


# ---------------------------------------------------------------------------
# Keyword extraction (TF-based)
# ---------------------------------------------------------------------------

_STOPWORDS_VI = {
    "là", "và", "của", "có", "được", "cho", "này", "với", "các", "trong",
    "để", "đã", "khi", "từ", "một", "không", "người", "nên", "thì", "cũng",
    "bạn", "mình", "tôi", "ạ", "nhé", "nha", "đi", "rồi", "lại", "ra",
    "vào", "lên", "xuống", "nữa", "hay", "mà", "thì", "vẫn", "sẽ", "đang",
    "bị", "do", "về", "theo", "nào", "gì", "ai", "đâu", "sao", "như", "thế",
    "the", "is", "and", "of", "to", "in", "for", "on", "it", "at", "by",
    "this", "that", "with", "from", "are", "was", "be", "have", "has",
    "you", "your", "they", "their", "he", "she", "his", "her", "we", "our",
}


def extract_keywords(texts: list[str], min_freq: int = 3, top_n: int = 30) -> list[dict]:
    word_counter: Counter = Counter()
    for text in texts:
        words = re.findall(r"[\w]+", text.lower())
        words = [w for w in words if len(w) > 1 and w not in _STOPWORDS_VI and not w.isdigit()]
        word_counter.update(words)

    return [
        {"keyword": word, "count": count}
        for word, count in word_counter.most_common(top_n)
        if count >= min_freq
    ]


# ---------------------------------------------------------------------------
# Topic clustering (frequency-based buckets)
# ---------------------------------------------------------------------------

_TOPIC_PATTERNS = {
    "Mua bán / Giá cả": ["bán", "mua", "giá", "pass", "inbox", "ship", "còn hàng", "order", "deal"],
    "Review / Đánh giá": ["review", "đánh giá", "trải nghiệm", "dùng thử", "nhận xét", "feedback"],
    "Hỏi đáp": ["hỏi", "ai biết", "cho mình hỏi", "giúp", "tư vấn", "recommend", "suggest"],
    "Khiếu nại / Phàn nàn": ["lỗi", "hỏng", "sai", "tệ", "chậm", "scam", "lừa", "thất vọng"],
    "Thời trang": ["áo", "quần", "váy", "giày", "túi", "phụ kiện", "outfit", "fashion"],
    "Làm đẹp": ["son", "kem", "serum", "skincare", "makeup", "trang điểm", "dưỡng"],
    "Ẩm thực": ["ăn", "uống", "quán", "nhà hàng", "đồ ăn", "food", "recipe"],
    "Công nghệ": ["điện thoại", "laptop", "iphone", "samsung", "app", "phần mềm"],
    "Tin tức / Sự kiện": ["tin", "nóng", "hot", "drama", "beef", "trend"],
}


def cluster_topics(texts: list[str], top_n: int = 10) -> list[dict]:
    topic_counts: Counter = Counter()
    combined = " ".join(texts).lower()

    for topic, keywords in _TOPIC_PATTERNS.items():
        count = sum(combined.count(kw) for kw in keywords)
        if count > 0:
            topic_counts[topic] = count

    total = sum(topic_counts.values()) or 1
    return [
        {"topic": topic, "mentions": count, "share_pct": round(count / total * 100, 1)}
        for topic, count in topic_counts.most_common(top_n)
    ]


# ---------------------------------------------------------------------------
# Hashtag & Mention extraction
# ---------------------------------------------------------------------------

_HASHTAG_RE = re.compile(r"#([\w\u00C0-\u024F\u1E00-\u1EFF]+)", re.UNICODE)
_MENTION_RE = re.compile(r"@([\w.\-]+)", re.UNICODE)


def _normalize_tag(tag: str) -> str:
    nfkd = unicodedata.normalize("NFKD", tag.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def extract_hashtags(text: str, *, post_id: str | None = None,
                     comment_id: str | None = None,
                     source_id: str = "", posted_at: str = "") -> list[dict]:
    tags = _HASHTAG_RE.findall(text)
    return [
        {
            "tag_raw": f"#{t}",
            "tag_normalized": _normalize_tag(t),
            "post_id": post_id,
            "comment_id": comment_id,
            "source_id": source_id,
            "posted_at": posted_at,
        }
        for t in tags
    ]


def extract_mentions(text: str, *, brands: list[dict] | None = None,
                     post_id: str | None = None, comment_id: str | None = None,
                     source_id: str = "", posted_at: str = "") -> list[dict]:
    raw_mentions = _MENTION_RE.findall(text)
    brand_keywords = {}
    for b in (brands or []):
        for kw in b.get("keywords", []) + [b["name"].lower()] + [a.lower() for a in b.get("aliases", [])]:
            brand_keywords[kw] = b["name"]

    results = []
    for m in raw_mentions:
        m_lower = m.lower()
        mention_type = "brand" if m_lower in brand_keywords else "user"
        norm = brand_keywords.get(m_lower, m_lower)
        sentiment = analyze_sentiment(text)["label"]
        results.append({
            "mention_raw": f"@{m}",
            "mention_normalized": norm,
            "mention_type": mention_type,
            "post_id": post_id,
            "comment_id": comment_id,
            "sentiment": sentiment,
            "source_id": source_id,
            "posted_at": posted_at,
        })

    # Also detect brand keywords in plain text (without @)
    text_lower = text.lower()
    for kw, brand_name in brand_keywords.items():
        if kw in text_lower and not any(r["mention_normalized"] == brand_name for r in results):
            sentiment = analyze_sentiment(text)["label"]
            results.append({
                "mention_raw": kw,
                "mention_normalized": brand_name,
                "mention_type": "brand",
                "post_id": post_id,
                "comment_id": comment_id,
                "sentiment": sentiment,
                "source_id": source_id,
                "posted_at": posted_at,
            })

    return results
