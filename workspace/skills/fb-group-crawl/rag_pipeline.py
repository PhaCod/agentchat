"""
rag_pipeline.py — Build and query RAG batches (Option A: FTS + metadata).
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import re
import db
import rag_db
from market_reasoner import build_market_query, extract_price_vnd


def _is_iso_dt(s: str) -> bool:
    return bool(s and re.match(r"^\d{4}-\d{2}-\d{2}T", s))


def _chunk_text(text: str, max_chars: int = 450) -> list[str]:
    """Simple chunking: sentence-ish split, then pack into <= max_chars."""
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?。…])\s+|\n+", t)
    out: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 1 <= max_chars:
            buf = (buf + " " + p).strip()
        else:
            if buf:
                out.append(buf)
            buf = p[: max_chars * 2]  # guard against ultra-long
            if len(buf) > max_chars:
                out.append(buf[:max_chars])
                buf = buf[max_chars:]
    if buf:
        out.append(buf)
    return out[:20]  # cap chunks per doc


def build_batch(
    *,
    group_id: str,
    query: str,
    days: int = 7,
    max_posts: int = 500,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Create a RAG batch from existing DB posts (no crawling here)."""
    rag_db.init_rag_db()
    db.init_db()

    if not batch_id:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w]+", "_", query.lower()).strip("_")[:32] or "query"
        batch_id = f"rag_{ts}_{group_id}_{safe}"

    from_date = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    posts = db.get_posts(group_id, from_date=from_date, limit=max_posts)
    if not posts:
        return {
            "status": "error",
            "message": f"No posts for group '{group_id}'. Run scrape first.",
            "group_id": group_id,
        }

    mq = build_market_query(group_id=group_id, query=query, days=days)

    docs = []
    for p in posts:
        content = p.get("content") or ""
        price = extract_price_vnd(content)
        posted_raw = p.get("posted_at") or ""
        posted_at = posted_raw if _is_iso_dt(posted_raw) else ""
        docs.append({
            "post_id": p.get("post_id", ""),
            "post_url": p.get("post_url", ""),
            "author": p.get("author", ""),
            "posted_at": posted_at,
            "scraped_at": p.get("scraped_at", ""),
            "content": content,
            "meta": {
                "group_id": group_id,
                "price_vnd": price,
                "reactions": (p.get("reactions") or {}).get("total", 0),
                "comments_count": p.get("comments_count", 0),
                "shares_count": p.get("shares_count", 0),
                "content_type": p.get("content_type", "text"),
            },
        })

    stats = {
        "posts_in_db_window": len(posts),
        "docs_added": len(docs),
    }
    settings = {
        "days": days,
        "max_posts": max_posts,
        "market_query": asdict(mq),
    }
    rag_db.create_batch(batch_id, group_id, query, days, settings=settings, stats=stats)
    rag_db.add_docs(batch_id, docs)

    # Build chunk rows: need doc_id mapping
    doc_map = rag_db.doc_id_map(batch_id)
    chunk_rows = []
    for d in docs:
        pid = d["post_id"]
        doc_id = doc_map.get(pid)
        if not doc_id:
            continue
        chunks = _chunk_text(d.get("content") or "")
        for i, c in enumerate(chunks):
            chunk_rows.append({
                "doc_id": doc_id,
                "chunk_index": i,
                "chunk_text": c,
                "meta": {
                    "price_vnd": d["meta"].get("price_vnd"),
                    "reactions": d["meta"].get("reactions"),
                },
            })

    chunks_added = rag_db.add_chunks(batch_id, chunk_rows)

    return {
        "status": "ok",
        "batch_id": batch_id,
        "group_id": group_id,
        "query": query,
        "days": days,
        "posts_used": len(posts),
        "docs_added": len(docs),
        "chunks_added": chunks_added,
    }


def ask_batch(
    *,
    group_id: str,
    query: str,
    batch_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    rag_db.init_rag_db()
    if not batch_id:
        latest = rag_db.latest_batch(group_id)
        if not latest:
            return {"status": "error", "message": f"No RAG batch for group '{group_id}'. Run rag-build first."}
        batch_id = latest["batch_id"]

    mq = build_market_query(group_id=group_id, query=query, days=7)
    # Build a compact OR query for FTS
    def _fts_safe(t: str) -> str:
        # FTS5 query syntax is picky; strip special chars like /, :, quotes.
        # Keep letters/digits and spaces only.
        s = re.sub(r"[^\w\s]", " ", (t or ""), flags=re.U)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    terms = [_fts_safe(t) for t in mq.keywords if _fts_safe(t)]
    # Prefer phrase queries for multi-word terms.
    fts_parts = []
    for t in terms[:12]:
        if " " in t:
            fts_parts.append(f"\"{t}\"")
        else:
            fts_parts.append(t)
    fts_query = " OR ".join(fts_parts) or _fts_safe(query) or query

    hits = rag_db.search_chunks(batch_id, fts_query, limit=50)

    # Collapse by post_id with best (lowest) bm25 score
    by_post: dict[str, dict[str, Any]] = {}
    for h in hits:
        pid = h.get("post_id") or ""
        if not pid:
            continue
        prev = by_post.get(pid)
        if not prev or (h.get("score") or 0) < (prev.get("score") or 0):
            by_post[pid] = h

    results = []
    for h in by_post.values():
        meta = h.get("doc_meta") or {}
        price = meta.get("price_vnd")
        results.append({
            "post_id": h.get("post_id"),
            "posted_at": h.get("posted_at") or h.get("scraped_at") or "",
            "author": h.get("author") or "",
            "price_vnd": price,
            "reactions": meta.get("reactions"),
            "comments_count": meta.get("comments_count"),
            "post_url": h.get("post_url") or "",
            "preview": (h.get("content") or "")[:200],
            "rag_score": h.get("score"),
        })

    # Rank: price first (known), then score
    def _rk(r: dict):
        price = r.get("price_vnd")
        return (
            0 if price is not None else 1,
            price if price is not None else 10**18,
            r.get("rag_score") or 10**9,
        )

    results.sort(key=_rk)
    results = results[:limit]

    return {
        "status": "ok",
        "group_id": group_id,
        "batch_id": batch_id,
        "query": query,
        "fts_query": fts_query,
        "matches": results,
        "note": "RAG (FTS+metadata). Use rag-build to refresh batch if data is stale.",
    }

