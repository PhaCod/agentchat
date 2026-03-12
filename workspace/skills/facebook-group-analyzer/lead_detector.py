"""
lead_detector.py — Objective 2: Lead generation / social selling.

Scores posts by purchase intent and assigns Hot / Warm / Cold tiers.

Hot  : Immediate intent — ready to buy NOW (0.8–1.0)
Warm : Researching — considering a purchase (0.5–0.79)
Cold : Casual interest — awareness stage (0.3–0.49)

Also extracts author info for outreach (when available).
"""
from __future__ import annotations

from collections import Counter

# ---------------------------------------------------------------------------
# Intent signal libraries
# ---------------------------------------------------------------------------

_INTENT_HOT = [
    # Direct purchase intent — Vietnamese Facebook commerce colloquials
    "mua ngay", "chốt ngay", "đặt hàng ngay", "order ngay",
    "inbox giá", "dm giá", "nhắn tin giá", "ib giá",
    "inbox ạ", "inbox đi", "ib ạ", "ib đi", "ib nha",
    "mua ở đâu ngay", "cần mua gấp", "mua gấp",
    "chỗ nào bán ngay", "ship ngay", "muốn mua luôn",
    "mua liền", "chốt liền", "lấy liền", "lấy ngay",
    "báo giá", "báo giá đi", "cho mình giá", "cho t giá",
    "link mua đi", "link đặt đi", "send link",
    "mua luôn", "order luôn", "chốt luôn",
    "lấy hàng", "lấy hàng ở đâu",
    "thanh toán như thế nào", "thanh toán qua",
    # Strong availability checks
    "ai bán không", "ai ship không", "ai có hàng không",
    "có sẵn không", "còn hàng không", "còn không", "còn hàng chưa",
    "in stock không", "hàng có sẵn",
    # Immediate booking/service intent
    "đặt lịch", "book lịch", "đặt chỗ ngay",
]

_INTENT_WARM = [
    # Price research
    "giá bao nhiêu", "bao nhiêu tiền", "khoảng bao nhiêu", "tầm bao nhiêu",
    "bao nhiêu 1 cái", "giá mấy", "giá như thế nào",
    "giá tầm", "trong tầm giá", "budget",
    # Location research
    "mua đâu", "mua ở đâu", "chỗ nào bán", "mua chỗ nào", "bán ở đâu",
    "shop nào", "store nào", "địa chỉ shop", "ở đâu bán",
    # Quality/trust validation before buying
    "có đáng không", "có tốt không", "có nên mua không", "nên mua không",
    "uy tín không", "tin tưởng không", "đáng tin không",
    "review đi", "ai dùng rồi", "ai dùng chưa", "dùng thấy sao",
    "ai mua rồi", "mua thấy sao", "có ai mua chưa",
    "recommend không", "gợi ý", "tư vấn", "tư vấn giúp",
    # Comparison shopping
    "so sánh", "so với", "nên chọn", "loại nào tốt hơn",
    "cái nào ngon hơn", "cái nào đáng mua",
    # Active shopping indicators
    "định mua", "đang tìm", "đang cần", "đang muốn mua",
    "link mua", "link shop", "link product", "link order",
    "phí ship", "ship bao nhiêu", "có ship không",
    "combo giá", "có combo không", "deal ngon",
    "mình muốn mua", "có bán không", "inbox để hỏi",
    # Service booking research
    "giá dịch vụ", "bảng giá", "có voucher không",
    "gợi ý chỗ nào", "chỗ nào ok", "chỗ nào ngon",
]

_INTENT_COLD = [
    # Awareness / casual discovery
    "nghe nói", "thấy bảo", "nghe có vẻ", "nghe nói hay",
    "hỏi chút", "cho hỏi", "hỏi ngu chút", "hỏi ngu",
    "ai biết", "ai xài chưa", "ai thử chưa", "có ai xài",
    "đã thử", "xài thử", "thử coi", "dùng thử",
    "nói về", "nói đến", "đề cập đến",
    "thú vị", "hay đấy", "có vẻ ngon", "trông hay đó",
    "để ý", "đang để mắt", "đang cân nhắc",
    "nghe review", "xem review", "đọc review",
    "xem thử", "tìm hiểu", "tham khảo",
]

# Product/service category signals to enrich lead context
_PRODUCT_CATEGORIES: dict[str, list[str]] = {
    "fashion": ["quần", "áo", "giày", "túi", "phụ kiện", "thời trang", "outfit"],
    "beauty": ["son", "kem", "serum", "mỹ phẩm", "làm đẹp", "skincare", "spa"],
    "food_beverage": ["ăn", "uống", "cafe", "trà", "đồ ăn", "thức ăn", "nhậu"],
    "electronics": ["điện thoại", "laptop", "máy tính", "tai nghe", "loa", "iphone", "samsung"],
    "real_estate": ["nhà", "đất", "căn hộ", "phòng trọ", "thuê nhà", "mua nhà"],
    "finance": ["đầu tư", "chứng khoán", "tiết kiệm", "vay", "bảo hiểm", "crypto"],
    "services": ["dịch vụ", "freelance", "thuê", "booking", "đặt lịch"],
}


def _detect_product_category(text: str) -> str:
    """Detect what product/service category the post is about."""
    t = text.lower()
    for cat, keywords in _PRODUCT_CATEGORIES.items():
        if any(kw in t for kw in keywords):
            return cat
    return "general"


def _score_post(post: dict) -> dict | None:
    """Score a single post for purchase intent. Returns None if no intent."""
    text = (post.get("content") or "").lower()
    if not text.strip():
        return None

    # Determine tier
    if any(kw in text for kw in _INTENT_HOT):
        tier, score = "Hot", 0.9
    elif any(kw in text for kw in _INTENT_WARM):
        tier, score = "Warm", 0.6
    elif any(kw in text for kw in _INTENT_COLD):
        tier, score = "Cold", 0.3
    else:
        return None

    reactions = post.get("reactions", {})
    if isinstance(reactions, dict):
        reactions_total = reactions.get("total", 0)
    else:
        reactions_total = int(reactions or 0)

    return {
        "post_id": post.get("post_id"),
        "author": post.get("author", "Unknown"),
        "author_id": post.get("author_id", ""),
        "post_url": post.get("post_url", ""),
        "timestamp": post.get("timestamp", ""),
        "tier": tier,
        "lead_score": score,
        "product_category": _detect_product_category(post.get("content", "")),
        "preview": (post.get("content") or "")[:150].replace("\n", " "),
        "reactions": reactions_total,
        "comments_count": post.get("comments_count", 0),
    }


class LeadDetector:
    """Score and classify posts by purchase intent for lead generation."""

    def __init__(self, min_tier: str = "Cold"):
        """
        min_tier: minimum tier to include — 'Hot', 'Warm', or 'Cold'
        """
        self.min_tier = min_tier
        self._tier_order = {"Hot": 3, "Warm": 2, "Cold": 1}

    def detect(self, posts: list[dict]) -> list[dict]:
        """Return scored posts filtered by min_tier, sorted Hot→Warm→Cold."""
        min_level = self._tier_order.get(self.min_tier, 1)
        leads = []
        for p in posts:
            result = _score_post(p)
            if result and self._tier_order.get(result["tier"], 0) >= min_level:
                leads.append(result)

        # Sort: tier desc, then reactions desc
        leads.sort(
            key=lambda x: (self._tier_order.get(x["tier"], 0), x["reactions"]),
            reverse=True,
        )
        return leads

    def summarize(self, posts: list[dict]) -> dict:
        """Return lead generation summary with tier breakdown."""
        all_leads = self.detect(posts)
        tier_counts: Counter = Counter(l["tier"] for l in all_leads)
        category_counts: Counter = Counter(l["product_category"] for l in all_leads)

        return {
            "total_leads": len(all_leads),
            "tier_breakdown": {
                "Hot": tier_counts.get("Hot", 0),
                "Warm": tier_counts.get("Warm", 0),
                "Cold": tier_counts.get("Cold", 0),
            },
            "top_product_categories": [
                {"category": cat, "count": cnt}
                for cat, cnt in category_counts.most_common(5)
            ],
            "hot_leads": [l for l in all_leads if l["tier"] == "Hot"][:20],
            "warm_leads": [l for l in all_leads if l["tier"] == "Warm"][:20],
            "cold_leads": [l for l in all_leads if l["tier"] == "Cold"][:10],
        }
