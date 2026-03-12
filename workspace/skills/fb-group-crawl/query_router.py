"""
query_router.py — Simple intent router for fb-group-crawl.

Given a natural language question about a Facebook group, decide which
subcommand is most appropriate:
- market      → fast keyword-based marketplace search (no LLM)
- rag-query   → RAG search (FTS over chunks with small crawl fallback)
- ask         → full AI analysis over posts

This router is intentionally lightweight and rule-based so that the
Telegram/webchat agent can either:
- call it directly from code, OR
- mirror the rules in prompts when deciding which command to run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


RouteKind = Literal["market", "rag-query", "ask"]


@dataclass
class RouteDecision:
    kind: RouteKind
    reason: str


_PRICE_PAT = re.compile(r"\b(\d{2,3})\s*(k|tr|triệu|m)\b", re.I)
_MONEY_WORDS = {
    "rẻ",
    "giá",
    "bao nhiêu",
    "dưới",
    "trên",
    "budget",
    "đắt",
    "sale",
}
_ACTION_SELL = {"bán", "pass", "thanh lý", "thanh ly", "sell"}
_ACTION_BUY = {"mua", "cần mua", "need", "tìm mua"}
_TREND_WORDS = {"trend", "xu hướng", "đang hot", "đang bàn", "thảo luận"}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def decide_route(question: str) -> RouteDecision:
    """Decide which fb-group-crawl subcommand to use.

    Heuristics:
    - If câu hỏi rõ ràng là *mua/bán + giá* → `market`
    - Nếu nhấn mạnh "tìm X" / "liệt kê bài" / lọc keyword cụ thể → `rag-query`
    - Nếu nói về *trend, insight, tổng kết, so sánh theo thời gian* → `ask`
    """
    qnorm = _normalize(question)

    # Very short / vague → default to ask (AI summary)
    if len(qnorm) < 8:
        return RouteDecision(kind="ask", reason="very short/vague question")

    has_price = bool(_PRICE_PAT.search(qnorm)) or any(w in qnorm for w in _MONEY_WORDS)
    has_sell_buy = any(w in qnorm for w in _ACTION_SELL | _ACTION_BUY)
    has_trend = any(w in qnorm for w in _TREND_WORDS)
    has_list_words = any(w in qnorm for w in ["liệt kê", "list", "danh sách", "tìm bài", "tìm post", "tìm bài viết"])

    # 1) Marketplace-style: tìm deal, giá, mua/bán, thường quan tâm <= N bài
    if has_price and has_sell_buy:
        return RouteDecision(kind="market", reason="price + buy/sell intent detected")

    # 2) Explicit search / listing → prefer RAG query (structured listing)
    if has_list_words or "tìm" in qnorm:
        return RouteDecision(kind="rag-query", reason="search/listing style question")

    # 3) Trend / tổng quan / insight → full AI ask
    if has_trend or "insight" in qnorm or "tổng kết" in qnorm or "tổng quan" in qnorm:
        return RouteDecision(kind="ask", reason="trend/insight style question")

    # Fallback: if it mentions cụ thể model/sản phẩm + không rõ trend → rag-query
    if any(tok in qnorm for tok in ["iphone", "xe ", "laptop", "son ", "kem "]):
        return RouteDecision(kind="rag-query", reason="product-specific search")

    # Default: ask (AI summary)
    return RouteDecision(kind="ask", reason="default fallback")


def explain_route_for_agent(question: str) -> str:
    """Small helper for prompts: return 1-line explanation."""
    d = decide_route(question)
    return f"Route='{d.kind}' because {d.reason}"

