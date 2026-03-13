"""
pain_detector.py — Extract pain points from user-generated text.

Categories: quality, shipping, pricing, service, sizing, counterfeit, other.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from log_config import get_logger

_log = get_logger("pain_detector")

_PAIN_CATEGORIES = {
    "quality": {
        "keywords": ["chất lượng kém", "mỏng", "bong tróc", "phai màu", "co rút", "rách",
                      "hỏng", "gãy", "vỡ", "nứt", "tróc", "poor quality", "defective",
                      "chất vải mỏng", "vải xấu", "đường may lỗi", "chỉ lỏng"],
        "label": "Chất lượng sản phẩm",
    },
    "shipping": {
        "keywords": ["ship chậm", "giao chậm", "giao trễ", "chưa nhận được", "mất hàng",
                      "đóng gói tệ", "giao sai", "thiếu hàng", "slow delivery", "late",
                      "giao lâu", "chờ lâu", "shipping"],
        "label": "Vận chuyển / Giao hàng",
    },
    "pricing": {
        "keywords": ["đắt", "mắc", "không đáng", "phí tiền", "overpriced", "expensive",
                      "giá cao", "chênh lệch giá", "tính sai giá", "hidden fee"],
        "label": "Giá cả",
    },
    "service": {
        "keywords": ["thái độ", "không hỗ trợ", "phản hồi chậm", "không trả lời",
                      "customer service", "rude", "unhelpful", "bảo hành",
                      "không đổi trả", "khó liên lạc", "inbox không rep"],
        "label": "Dịch vụ / CSKH",
    },
    "sizing": {
        "keywords": ["sai size", "size không chuẩn", "rộng quá", "chật quá",
                      "không đúng size", "wrong size", "doesn't fit",
                      "form xấu", "không vừa", "lệch size"],
        "label": "Size / Kích thước",
    },
    "counterfeit": {
        "keywords": ["giả", "fake", "nhái", "scam", "lừa đảo", "hàng giả",
                      "không giống hình", "khác hình", "không giống ảnh",
                      "hàng dỏm", "đồ nhái"],
        "label": "Hàng giả / Lừa đảo",
    },
}


def detect_pain_points(texts: list[str], top_n: int = 20) -> list[dict]:
    category_counts: Counter = Counter()
    category_examples: dict[str, list[str]] = {k: [] for k in _PAIN_CATEGORIES}

    for text in texts:
        text_lower = text.lower()
        for cat_id, cat_info in _PAIN_CATEGORIES.items():
            for kw in cat_info["keywords"]:
                if kw in text_lower:
                    category_counts[cat_id] += 1
                    if len(category_examples[cat_id]) < 3:
                        category_examples[cat_id].append(text[:200])
                    break

    results = []
    for cat_id, count in category_counts.most_common(top_n):
        cat_info = _PAIN_CATEGORIES[cat_id]
        results.append({
            "category": cat_id,
            "label": cat_info["label"],
            "mentions": count,
            "severity_pct": round(count / max(len(texts), 1) * 100, 1),
            "examples": category_examples[cat_id],
        })

    return results
