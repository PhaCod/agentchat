"""
competitor_tracker.py — Objective 4: Competitor monitoring.

Tracks brand mentions, Share of Voice (SOV), and per-brand sentiment
from scraped posts. Config-driven: brands defined in config.json.

Config schema (config.json):
  "competitors": [
    {
      "name": "BrandA",
      "keywords": ["branda", "brand a", "tên thương hiệu a"],
      "aliases": ["alias1", "alias2"]   (optional)
    }
  ]
"""
from __future__ import annotations

from collections import Counter, defaultdict

# Reuse sentiment scorer from analyzer
def _score_sentiment(text: str) -> str:
    """Simple positive/negative/neutral — re-uses logic from analyzer."""
    t = text.lower()
    pos_signals = [
        "tốt", "hay", "đỉnh", "xuất sắc", "tuyệt", "chất lượng", "ổn", "ok", "ngon",
        "thích", "yêu", "hài lòng", "hợp lý", "rẻ", "nhanh", "đẹp", "pro",
        "recommend", "ủng hộ", "uy tín", "hiệu quả", "chuẩn",
        "good", "great", "love", "amazing", "excellent", "perfect",
        "helpful", "nice", "best", "fantastic", "awesome",
    ]
    neg_signals = [
        "tệ", "xấu", "dỏm", "kém", "chậm", "sai", "lỗi", "bug", "vỡ", "hỏng",
        "thất vọng", "không hài lòng", "đắt", "chặt chém", "lừa đảo",
        "scam", "giả", "fake", "kém chất lượng", "tránh", "cẩn thận",
        "bad", "terrible", "awful", "horrible", "poor", "worst", "useless", "broken",
        "disappointing", "fraud", "avoid", "waste",
    ]
    pos = sum(1 for w in pos_signals if w in t)
    neg = sum(1 for w in neg_signals if w in t)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


class CompetitorTracker:
    """Track brand mentions and sentiment from post content."""

    def __init__(self, cfg: dict):
        self.brands = cfg.get("competitors", [])

    def _get_keywords(self, brand: dict) -> list[str]:
        kws = list(brand.get("keywords", []))
        kws.extend(brand.get("aliases", []))
        return [k.lower() for k in kws]

    def analyze(self, posts: list[dict]) -> dict:
        """Return Share of Voice and per-brand sentiment/post analysis."""
        if not self.brands:
            return {
                "_note": "No competitors configured. Add 'competitors' array to config.json."
            }

        brand_mentions: dict[str, int] = {}
        brand_sentiment: dict[str, Counter] = {}
        brand_posts: dict[str, list[dict]] = defaultdict(list)

        for brand in self.brands:
            name = brand["name"]
            kws = self._get_keywords(brand)
            brand_mentions[name] = 0
            brand_sentiment[name] = Counter()

            for p in posts:
                text = (p.get("content") or "").lower()
                if not text.strip():
                    continue
                if any(kw in text for kw in kws):
                    brand_mentions[name] += 1
                    sentiment = _score_sentiment(text)
                    brand_sentiment[name][sentiment] += 1
                    brand_posts[name].append({
                        "post_id": p.get("post_id"),
                        "post_url": p.get("post_url", ""),
                        "preview": (p.get("content") or "")[:120].replace("\n", " "),
                        "sentiment": sentiment,
                        "reactions": (p.get("reactions") or {}).get("total", 0)
                            if isinstance(p.get("reactions"), dict) else 0,
                    })

        total_mentions = sum(brand_mentions.values()) or 1

        brand_analysis = {}
        for brand in self.brands:
            name = brand["name"]
            mentions = brand_mentions[name]
            sov = round(mentions / total_mentions * 100, 1)
            sent = brand_sentiment[name]
            total_brand = sum(sent.values()) or 1
            top_posts = sorted(
                brand_posts[name],
                key=lambda x: x["reactions"],
                reverse=True,
            )[:5]

            brand_analysis[name] = {
                "mentions": mentions,
                "share_of_voice_pct": sov,
                "sentiment": {
                    "positive": sent.get("positive", 0),
                    "neutral": sent.get("neutral", 0),
                    "negative": sent.get("negative", 0),
                    "positive_pct": round(sent.get("positive", 0) / total_brand * 100, 1),
                    "negative_pct": round(sent.get("negative", 0) / total_brand * 100, 1),
                },
                "top_posts": top_posts,
            }

        # Overall SOV ranking
        sov_ranking = sorted(
            [{"brand": n, "sov_pct": d["share_of_voice_pct"], "mentions": d["mentions"]}
             for n, d in brand_analysis.items()],
            key=lambda x: x["sov_pct"],
            reverse=True,
        )

        return {
            "total_brand_mentions": total_mentions,
            "share_of_voice": sov_ranking,
            "brand_details": brand_analysis,
        }
