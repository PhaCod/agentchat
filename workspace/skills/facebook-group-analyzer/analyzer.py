"""
analyzer.py — Content, engagement, and trend analysis for Facebook group posts.

Modules:
  - SentimentAnalyzer   : rule-based Vietnamese/English sentiment
  - KeywordExtractor    : TF-based keyword frequency
  - TopicClusterer      : simple topic grouping by keyword buckets
  - SpamDetector        : heuristic spam/ad detection
  - EngagementAnalyzer  : top posts, best hours, content-type breakdown
  - TrendDetector       : rising/declining keywords, viral posts, weekly shifts
  - GroupAnalyzer       : orchestrates all modules → final analysis schema
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Sentiment (rule-based, Vietnamese + English)
# ---------------------------------------------------------------------------

_POS_VI = [
    "tốt", "hay", "đỉnh", "xuất sắc", "tuyệt", "chất lượng", "ổn", "ok", "ngon",
    "thích", "yêu", "hài lòng", "hợp lý", "rẻ", "nhanh", "nét", "đẹp", "pro",
    "recommend", "gợi ý", "ủng hộ", "uy tín", "đáng tin", "hiệu quả", "chuẩn",
    "good", "great", "love", "amazing", "excellent", "perfect", "recommend",
    "helpful", "nice", "best", "fantastic", "awesome", "wonderful",
]
_NEG_VI = [
    "tệ", "xấu", "dỏm", "kém", "chậm", "sai", "lỗi", "bug", "vỡ", "hỏng",
    "thất vọng", "không hài lòng", "đắt", "đắt quá", "chặt chém", "lừa đảo",
    "scam", "giả", "fake", "kém chất lượng", "ăn không ngon", "tránh", "cẩn thận",
    "bad", "terrible", "awful", "horrible", "poor", "worst", "useless", "broken",
    "disappointing", "fraud", "scam", "avoid", "waste",
]


def _score_sentiment(text: str) -> str:
    t = text.lower()
    pos = sum(1 for w in _POS_VI if w in t)
    neg = sum(1 for w in _NEG_VI if w in t)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


class SentimentAnalyzer:
    def analyze(self, posts: list[dict]) -> dict:
        counts: Counter = Counter()
        for p in posts:
            counts[_score_sentiment(p.get("content", ""))] += 1
        total = len(posts) or 1
        return {
            "positive": counts["positive"],
            "neutral": counts["neutral"],
            "negative": counts["negative"],
            "distribution_pct": {
                "positive": round(counts["positive"] / total * 100, 1),
                "neutral": round(counts["neutral"] / total * 100, 1),
                "negative": round(counts["negative"] / total * 100, 1),
            },
        }


# ---------------------------------------------------------------------------
# Keyword Extractor
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "và", "là", "của", "có", "cho", "với", "từ", "các", "một", "để", "không",
    "trong", "này", "đã", "được", "bạn", "ở", "tôi", "về", "cũng", "khi", "như",
    "the", "a", "an", "is", "in", "it", "of", "and", "to", "for", "on", "at",
    "be", "this", "that", "are", "was", "were", "with", "by", "or", "but",
    "i", "you", "he", "she", "we", "they", "do", "not", "have", "has",
}


class KeywordExtractor:
    def __init__(self, min_freq: int = 3, top_n: int = 30):
        self.min_freq = min_freq
        self.top_n = top_n

    def extract(self, posts: list[dict]) -> list[dict]:
        all_words: list[str] = []
        for p in posts:
            raw = re.sub(r"https?://\S+", "", p.get("content", ""))
            raw = re.sub(r"[^\w\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", " ", raw, flags=re.U)
            words = [w.lower() for w in raw.split() if len(w) >= 3 and w.lower() not in _STOPWORDS]
            all_words.extend(words)

        counts = Counter(all_words)
        result = [
            {"keyword": w, "count": c}
            for w, c in counts.most_common(self.top_n)
            if c >= self.min_freq
        ]
        return result


# ---------------------------------------------------------------------------
# Topic Clusterer (keyword bucket approach)
# ---------------------------------------------------------------------------

_TOPIC_BUCKETS: dict[str, list[str]] = {
    "Hỏi giá / Mua bán": ["giá", "bao nhiêu", "mua", "bán", "order", "ship", "giao hàng", "inbox", "dm"],
    "Review / Feedback": ["review", "đánh giá", "cảm nhận", "dùng thử", "test", "như thế nào", "chia sẻ"],
    "Hỏi đáp / Tư vấn": ["hỏi", "ai biết", "tư vấn", "giúp", "help", "cần", "kinh nghiệm"],
    "Quảng cáo / Spam": ["sale", "khuyến mãi", "deal", "flash sale", "giảm giá", "mã giảm", "voucher", "link bio", "dm để nhận"],
    "Tin tức / Chia sẻ": ["tin tức", "cập nhật", "thông báo", "sự kiện", "event", "mới nhất", "breaking"],
    "Giải trí / Hài hước": ["haha", "lol", "buồn cười", "vui", "meme", "clip hài", "troll"],
    "Cộng đồng / Kết nối": ["tìm bạn", "kết nối", "cộng đồng", "meet", "group", "fanpage", "follow"],
}


class TopicClusterer:
    def cluster(self, posts: list[dict]) -> list[dict]:
        bucket_counts: Counter = Counter()
        for p in posts:
            text = p.get("content", "").lower()
            matched = False
            for topic, kws in _TOPIC_BUCKETS.items():
                if any(kw in text for kw in kws):
                    bucket_counts[topic] += 1
                    matched = True
                    break
            if not matched:
                bucket_counts["Khác"] += 1

        total = len(posts) or 1
        return [
            {"topic": t, "post_count": c, "pct": round(c / total * 100, 1)}
            for t, c in bucket_counts.most_common()
        ]


# ---------------------------------------------------------------------------
# Spam Detector
# ---------------------------------------------------------------------------

_SPAM_SIGNALS = [
    r"dm\s*(để|đi|mình|tôi|ngay)",
    r"inbox\s*(mình|tôi|ngay)",
    r"link\s*(bio|profile|nhé)",
    r"(flash\s*sale|giảm\s*\d+%|khuyến\s*mãi|mã\s*giảm)",
    r"(zalo|telegram|whatsapp)\s*\d{9,11}",
    r"(click|bấm)\s*(vào|here|link)",
    r"free\s*(ship|giao|tặng)",
    r"\d{3,4}k\b",
]
_SPAM_REs = [re.compile(p, re.I | re.U) for p in _SPAM_SIGNALS]


def _spam_score(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(1 for r in _SPAM_REs if r.search(text))
    return min(1.0, hits / 3)


class SpamDetector:
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def detect(self, posts: list[dict]) -> list[dict]:
        """Tag each post with spam_score; return spam posts."""
        spam = []
        for p in posts:
            score = _spam_score(p.get("content", ""))
            p["spam_score"] = round(score, 2)
            if score >= self.threshold:
                spam.append(p)
        return spam


# ---------------------------------------------------------------------------
# Engagement Analyzer
# ---------------------------------------------------------------------------

class EngagementAnalyzer:
    def analyze(self, posts: list[dict]) -> dict:
        if not posts:
            return {}

        total = len(posts)
        total_reactions = sum(p.get("reactions", {}).get("total", 0) for p in posts)
        total_comments = sum(p.get("comments_count", 0) for p in posts)
        total_shares = sum(p.get("shares_count", 0) for p in posts)

        # Top posts by reactions
        top_posts = sorted(posts, key=lambda p: p.get("reactions", {}).get("total", 0), reverse=True)[:10]
        top_posts_out = [
            {
                "post_id": p["post_id"],
                "author": p.get("author", ""),
                "content_preview": p.get("content", "")[:120],
                "reactions": p.get("reactions", {}).get("total", 0),
                "comments_count": p.get("comments_count", 0),
                "shares_count": p.get("shares_count", 0),
                "timestamp": p.get("timestamp", ""),
                "post_url": p.get("post_url", ""),
            }
            for p in top_posts
        ]

        # Best hours (UTC)
        hour_counter: Counter = Counter()
        for p in posts:
            ts = p.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    hour_counter[dt.hour] += p.get("reactions", {}).get("total", 0)
                except ValueError:
                    pass
        best_hours = [h for h, _ in hour_counter.most_common(5)]

        # Content type breakdown
        ct_counter: dict[str, dict] = defaultdict(lambda: {"count": 0, "reactions": 0})
        for p in posts:
            ct = p.get("content_type", "text")
            ct_counter[ct]["count"] += 1
            ct_counter[ct]["reactions"] += p.get("reactions", {}).get("total", 0)

        ct_breakdown = {
            ct: {
                "count": v["count"],
                "avg_reactions": round(v["reactions"] / v["count"], 1) if v["count"] else 0,
            }
            for ct, v in ct_counter.items()
        }

        return {
            "avg_reactions": round(total_reactions / total, 1),
            "avg_comments": round(total_comments / total, 1),
            "avg_shares": round(total_shares / total, 1),
            "top_posts": top_posts_out,
            "best_hours": best_hours,
            "content_type_breakdown": ct_breakdown,
        }


# ---------------------------------------------------------------------------
# Trend Detector
# ---------------------------------------------------------------------------

class TrendDetector:
    def detect(self, posts: list[dict]) -> dict:
        """Compare keyword frequency across time windows."""
        if not posts:
            return {}

        # Sort by timestamp
        dated = []
        for p in posts:
            ts = p.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dated.append((dt, p))
                except ValueError:
                    pass
        if not dated:
            return {}

        dated.sort(key=lambda x: x[0])
        cutoff_mid = dated[len(dated) // 2][0]

        early = [p for dt, p in dated if dt < cutoff_mid]
        late = [p for dt, p in dated if dt >= cutoff_mid]

        def keyword_freq(group: list[dict]) -> Counter:
            c: Counter = Counter()
            for p in group:
                raw = re.sub(r"https?://\S+", "", p.get("content", ""))
                raw = re.sub(r"[^\w\s]", " ", raw, flags=re.U)
                for w in raw.lower().split():
                    if len(w) >= 4 and w not in _STOPWORDS:
                        c[w] += 1
            return c

        early_freq = keyword_freq(early)
        late_freq = keyword_freq(late)

        all_words = set(early_freq) | set(late_freq)
        rising, declining = [], []
        for w in all_words:
            if early_freq[w] == 0 and late_freq[w] >= 3:
                rising.append(w)
            elif early_freq[w] >= 3 and late_freq[w] == 0:
                declining.append(w)
            elif early_freq[w] >= 2:
                ratio = late_freq[w] / early_freq[w]
                if ratio >= 2.5:
                    rising.append(w)
                elif ratio <= 0.3:
                    declining.append(w)

        # Viral posts: reactions > mean + 2*stdev
        reactions = [p.get("reactions", {}).get("total", 0) for _, p in dated]
        mean_r = sum(reactions) / len(reactions) if reactions else 0
        var_r = sum((r - mean_r) ** 2 for r in reactions) / len(reactions) if reactions else 0
        std_r = var_r ** 0.5
        viral_threshold = mean_r + 2 * std_r
        viral_posts = [p["post_id"] for _, p in dated if p.get("reactions", {}).get("total", 0) >= viral_threshold]

        # Weekly topic shift
        weekly_topics: dict[str, Counter] = defaultdict(Counter)
        for dt, p in dated:
            week_label = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
            text = p.get("content", "").lower()
            for topic, kws in _TOPIC_BUCKETS.items():
                if any(kw in text for kw in kws):
                    weekly_topics[week_label][topic] += 1
                    break

        weekly_summary = {
            week: max(counts, key=counts.get) if counts else "N/A"
            for week, counts in sorted(weekly_topics.items())
        }

        return {
            "rising_keywords": rising[:20],
            "declining_keywords": declining[:20],
            "viral_posts": viral_posts[:10],
            "weekly_dominant_topic": weekly_summary,
        }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

class GroupAnalyzer:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        acfg = cfg.get("analysis", {})
        self.sentiment = SentimentAnalyzer()
        self.keywords = KeywordExtractor(
            min_freq=acfg.get("min_keyword_freq", 3),
            top_n=30,
        )
        self.topics = TopicClusterer()
        self.spam = SpamDetector(threshold=acfg.get("spam_min_score", 0.7))
        self.engagement = EngagementAnalyzer()
        self.trends = TrendDetector()

    def analyze(self, posts: list[dict], group_id: str) -> dict:
        if not posts:
            return {"error": "No posts to analyze"}

        # Posts with non-empty content (for sentiment, keywords, topics)
        posts_with_content = [p for p in posts if (p.get("content") or "").strip()]
        excluded_text = len(posts) - len(posts_with_content)

        # Date range
        timestamps = [p.get("timestamp", "") for p in posts if p.get("timestamp")]
        date_range: dict[str, Any] = {}
        if timestamps:
            parsed = []
            for t in timestamps:
                try:
                    parsed.append(datetime.fromisoformat(t))
                except ValueError:
                    pass
            if parsed:
                date_range = {
                    "from": min(parsed).date().isoformat(),
                    "to": max(parsed).date().isoformat(),
                }

        if not date_range and posts:
            date_range = {"_note": "Most or all posts have empty timestamp; range unavailable."}

        # Run modules
        spam_posts = self.spam.detect(posts)  # mutates posts with spam_score

        # Sentiment & keywords & topics only on posts with content
        sentiment = self.sentiment.analyze(posts_with_content) if posts_with_content else {
            "positive": 0, "neutral": 0, "negative": 0,
            "distribution_pct": {"positive": 0, "neutral": 100, "negative": 0},
        }
        top_keywords = self.keywords.extract(posts_with_content) if posts_with_content else []
        topics = self.topics.cluster(posts_with_content) if posts_with_content else []

        return {
            "group_id": group_id,
            "analyzed_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_posts": len(posts),
            "posts_with_content": len(posts_with_content),
            "posts_excluded_from_text_analysis": excluded_text,
            "date_range": date_range,
            "sentiment": sentiment,
            "top_keywords": top_keywords,
            "topics": topics,
            "spam_posts_count": len(spam_posts),
            "spam_post_ids": [p["post_id"] for p in spam_posts],
            "engagement": self.engagement.analyze(posts),
            "trends": self.trends.detect(posts),
        }
