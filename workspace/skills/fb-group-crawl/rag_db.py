"""
rag_db.py — SQLite RAG store (Option A): batches + docs + chunks + FTS.

This store is designed for production:
- deterministic retrieval (FTS + metadata filters)
- per-question batch isolation (batch_id)
- fast re-ask without re-crawling
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from log_config import get_logger

_log = get_logger("rag_db")
_HERE = Path(__file__).parent
_RAG_DB_PATH = _HERE / "data" / "rag.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_batches (
  batch_id      TEXT PRIMARY KEY,
  group_id      TEXT NOT NULL,
  query_text    TEXT NOT NULL,
  days          INTEGER NOT NULL,
  created_at    TEXT NOT NULL,
  source        TEXT NOT NULL DEFAULT 'facebook',
  settings_json TEXT NOT NULL DEFAULT '{}',
  stats_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rag_docs (
  doc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      TEXT NOT NULL,
  post_id       TEXT NOT NULL,
  post_url      TEXT DEFAULT '',
  author        TEXT DEFAULT '',
  posted_at     TEXT DEFAULT '',
  scraped_at    TEXT DEFAULT '',
  content       TEXT NOT NULL DEFAULT '',
  meta_json     TEXT NOT NULL DEFAULT '{}',
  UNIQUE(batch_id, post_id),
  FOREIGN KEY(batch_id) REFERENCES rag_batches(batch_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  chunk_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      TEXT NOT NULL,
  doc_id        INTEGER NOT NULL,
  chunk_index   INTEGER NOT NULL,
  chunk_text    TEXT NOT NULL,
  chunk_meta_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(batch_id) REFERENCES rag_batches(batch_id) ON DELETE CASCADE,
  FOREIGN KEY(doc_id) REFERENCES rag_docs(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rag_docs_batch ON rag_docs(batch_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_batch ON rag_chunks(batch_id);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
  chunk_text,
  content='rag_chunks',
  content_rowid='chunk_id',
  tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rowid, chunk_text) VALUES (new.chunk_id, new.chunk_text);
END;
CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, chunk_text) VALUES ('delete', old.chunk_id, old.chunk_text);
END;
CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, chunk_text) VALUES ('delete', old.chunk_id, old.chunk_text);
  INSERT INTO rag_chunks_fts(rowid, chunk_text) VALUES (new.chunk_id, new.chunk_text);
END;
"""


def _ensure_dir() -> None:
    _RAG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(str(_RAG_DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_rag_db() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.close()
    _log.info("RAG DB initialized at %s", _RAG_DB_PATH)


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def create_batch(
    batch_id: str,
    group_id: str,
    query_text: str,
    days: int,
    *,
    settings: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    init_rag_db()
    conn = get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO rag_batches(batch_id, group_id, query_text, days, created_at, settings_json, stats_json)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            group_id,
            query_text,
            int(days),
            now_iso(),
            json.dumps(settings or {}, ensure_ascii=False),
            json.dumps(stats or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def add_docs(batch_id: str, docs: list[dict[str, Any]]) -> int:
    """Insert docs; returns number inserted."""
    if not docs:
        return 0
    conn = get_conn()
    inserted = 0
    for d in docs:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO rag_docs(
                  batch_id, post_id, post_url, author, posted_at, scraped_at, content, meta_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    d.get("post_id", ""),
                    d.get("post_url", ""),
                    d.get("author", ""),
                    d.get("posted_at", ""),
                    d.get("scraped_at", ""),
                    d.get("content", "") or "",
                    json.dumps(d.get("meta", {}) or {}, ensure_ascii=False),
                ),
            )
            if conn.total_changes:
                inserted += 1
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    conn.close()
    return inserted


def _doc_id_map(batch_id: str) -> dict[str, int]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT doc_id, post_id FROM rag_docs WHERE batch_id = ?",
        (batch_id,),
    ).fetchall()
    conn.close()
    return {r["post_id"]: r["doc_id"] for r in rows}


def doc_id_map(batch_id: str) -> dict[str, int]:
    """Public wrapper for mapping post_id -> doc_id within a batch."""
    return _doc_id_map(batch_id)


def add_chunks(batch_id: str, chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    conn = get_conn()
    inserted = 0
    for c in chunks:
        try:
            conn.execute(
                """
                INSERT INTO rag_chunks(batch_id, doc_id, chunk_index, chunk_text, chunk_meta_json)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    int(c["doc_id"]),
                    int(c["chunk_index"]),
                    c["chunk_text"],
                    json.dumps(c.get("meta", {}) or {}, ensure_ascii=False),
                ),
            )
            inserted += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    return inserted


def latest_batch(group_id: str) -> dict[str, Any] | None:
    init_rag_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM rag_batches WHERE group_id = ? ORDER BY created_at DESC LIMIT 1",
        (group_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["settings"] = json.loads(d.pop("settings_json") or "{}")
    d["stats"] = json.loads(d.pop("stats_json") or "{}")
    return d


def search_chunks(batch_id: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """FTS search within a batch. Returns chunk + joined doc fields."""
    init_rag_db()
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
          c.chunk_id, c.doc_id, c.chunk_index, c.chunk_text, c.chunk_meta_json,
          d.post_id, d.post_url, d.author, d.posted_at, d.scraped_at, d.content, d.meta_json,
          bm25(rag_chunks_fts) as score
        FROM rag_chunks_fts
        JOIN rag_chunks c ON c.chunk_id = rag_chunks_fts.rowid
        JOIN rag_docs d ON d.doc_id = c.doc_id
        WHERE c.batch_id = ?
          AND rag_chunks_fts.chunk_text MATCH ?
        ORDER BY score ASC
        LIMIT ?
        """,
        (batch_id, query, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        rr = dict(r)
        rr["chunk_meta"] = json.loads(rr.pop("chunk_meta_json") or "{}")
        rr["doc_meta"] = json.loads(rr.pop("meta_json") or "{}")
        out.append(rr)
    return out


def list_batches(group_id: str, limit: int = 20) -> list[dict[str, Any]]:
    init_rag_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rag_batches WHERE group_id = ? ORDER BY created_at DESC LIMIT ?",
        (group_id, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["settings"] = json.loads(d.pop("settings_json") or "{}")
        d["stats"] = json.loads(d.pop("stats_json") or "{}")
        out.append(d)
    return out


def _norm_query(q: str) -> str:
    q = (q or "").strip().lower()
    q = re.sub(r"[^\w\s]", " ", q, flags=re.U)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def find_matching_batch(
    group_id: str,
    query_text: str,
    *,
    ttl_hours: int = 72,
    scan_limit: int = 50,
) -> dict[str, Any] | None:
    """Find most recent batch for group matching normalized query within TTL."""
    from datetime import datetime, timedelta, timezone

    init_rag_db()
    qn = _norm_query(query_text)
    if not qn:
        return None

    batches = list_batches(group_id, limit=scan_limit)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=ttl_hours)
    for b in batches:
        try:
            created = datetime.fromisoformat(b.get("created_at") or "")
        except Exception:
            created = None
        if created and created < cutoff:
            continue
        if _norm_query(b.get("query_text") or "") == qn:
            return b
    return None

