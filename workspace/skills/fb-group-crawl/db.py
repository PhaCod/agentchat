"""
db.py — SQLite storage with FTS5 full-text search and time-series indexes.

Design:
  - Single file database at data/fb_posts.db
  - WAL mode for concurrent read/write
  - FTS5 virtual table for Vietnamese full-text search
  - Incremental cursor per group (last_post_id)
  - All timestamps stored as ISO-8601 strings for portability
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from log_config import get_logger

_log = get_logger("db")
_HERE = Path(__file__).parent
_DB_PATH = _HERE / "data" / "fb_posts.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT    UNIQUE NOT NULL,
    group_id        TEXT    NOT NULL,
    author          TEXT    DEFAULT '',
    author_id       TEXT    DEFAULT '',
    content         TEXT    DEFAULT '',
    media           TEXT    DEFAULT '[]',
    reactions_total INTEGER DEFAULT 0,
    reactions_like  INTEGER DEFAULT 0,
    reactions_love  INTEGER DEFAULT 0,
    reactions_haha  INTEGER DEFAULT 0,
    reactions_wow   INTEGER DEFAULT 0,
    reactions_sad   INTEGER DEFAULT 0,
    reactions_angry INTEGER DEFAULT 0,
    comments_count  INTEGER DEFAULT 0,
    shares_count    INTEGER DEFAULT 0,
    post_url        TEXT    DEFAULT '',
    content_type    TEXT    DEFAULT 'text',
    posted_at       TEXT,
    scraped_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_group_time
    ON posts(group_id, posted_at DESC);

CREATE INDEX IF NOT EXISTS idx_posts_group_scraped
    ON posts(group_id, scraped_at DESC);

CREATE TABLE IF NOT EXISTS groups (
    group_id        TEXT PRIMARY KEY,
    group_url       TEXT NOT NULL,
    added_at        TEXT NOT NULL,
    last_scraped_at TEXT,
    last_post_id    TEXT,
    total_posts     INTEGER DEFAULT 0
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    content,
    content='posts',
    content_rowid='id',
    tokenize='unicode61'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO posts_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _ensure_dir() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    """Return a connection with WAL mode and row_factory."""
    _ensure_dir()
    conn = sqlite3.connect(str(_DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db() -> None:
    """Create tables, indexes, FTS, and triggers if not exist."""
    conn = get_conn()
    conn.executescript(_SCHEMA)
    try:
        conn.executescript(_FTS_SCHEMA)
        conn.executescript(_FTS_TRIGGERS)
    except sqlite3.OperationalError as e:
        _log.warning("FTS5 setup warning (may already exist): %s", e)
    conn.close()
    _log.info("Database initialized at %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Posts CRUD
# ---------------------------------------------------------------------------

def upsert_posts(posts: list[dict]) -> dict[str, int]:
    """Insert or ignore posts. Returns {inserted, skipped}."""
    if not posts:
        return {"inserted": 0, "skipped": 0}

    conn = get_conn()
    inserted = 0
    skipped = 0

    for p in posts:
        reactions = p.get("reactions", {})
        try:
            conn.execute("""
                INSERT OR IGNORE INTO posts (
                    post_id, group_id, author, author_id, content, media,
                    reactions_total, reactions_like, reactions_love,
                    reactions_haha, reactions_wow, reactions_sad, reactions_angry,
                    comments_count, shares_count, post_url, content_type,
                    posted_at, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p.get("post_id", ""),
                p.get("group_id", ""),
                p.get("author", ""),
                p.get("author_id", ""),
                p.get("content", ""),
                json.dumps(p.get("media", []), ensure_ascii=False),
                reactions.get("total", 0),
                reactions.get("like", 0),
                reactions.get("love", 0),
                reactions.get("haha", 0),
                reactions.get("wow", 0),
                reactions.get("sad", 0),
                reactions.get("angry", 0),
                p.get("comments_count", 0),
                p.get("shares_count", 0),
                p.get("post_url", ""),
                p.get("content_type", "text"),
                p.get("timestamp", ""),
                p.get("scraped_at", datetime.now(tz=timezone.utc).isoformat()),
            ))
            if conn.total_changes:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    conn.close()
    _log.info("Upsert: %d inserted, %d skipped (duplicates)", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict with nested reactions."""
    d = dict(row)
    d["reactions"] = {
        "total": d.pop("reactions_total", 0),
        "like": d.pop("reactions_like", 0),
        "love": d.pop("reactions_love", 0),
        "haha": d.pop("reactions_haha", 0),
        "wow": d.pop("reactions_wow", 0),
        "sad": d.pop("reactions_sad", 0),
        "angry": d.pop("reactions_angry", 0),
    }
    try:
        d["media"] = json.loads(d.get("media", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["media"] = []
    return d


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_posts(
    group_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Get posts for a group, ordered by posted_at DESC (time-series)."""
    conn = get_conn()
    clauses = ["group_id = ?"]
    params: list[Any] = [group_id]

    if from_date:
        clauses.append("posted_at >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("posted_at <= ?")
        params.append(to_date)

    where = " AND ".join(clauses)
    sql = f"""
        SELECT * FROM posts
        WHERE {where}
        ORDER BY COALESCE(NULLIF(posted_at, ''), scraped_at) DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def search_posts(
    group_id: str,
    keyword: str,
    limit: int = 50,
) -> list[dict]:
    """Full-text search using FTS5."""
    conn = get_conn()
    sql = """
        SELECT p.* FROM posts p
        JOIN posts_fts fts ON fts.rowid = p.id
        WHERE fts.content MATCH ? AND p.group_id = ?
        ORDER BY COALESCE(NULLIF(p.posted_at, ''), p.scraped_at) DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (keyword, group_id, limit)).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def count_posts(group_id: str) -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM posts WHERE group_id = ?", (group_id,)).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def count_posts_window(
    group_id: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> int:
    """Count posts within a time window for a group.

    Uses COALESCE(posted_at, scraped_at) so posts missing posted_at still count.
    """
    conn = get_conn()
    clauses = ["group_id = ?"]
    params: list[Any] = [group_id]
    time_expr = "COALESCE(NULLIF(posted_at, ''), scraped_at)"
    if from_date:
        clauses.append(f"{time_expr} >= ?")
        params.append(from_date)
    if to_date:
        clauses.append(f"{time_expr} <= ?")
        params.append(to_date)
    where = " AND ".join(clauses)
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM posts WHERE {where}", params).fetchone()
    conn.close()
    return int(row["cnt"] if row else 0)


def get_stats(group_id: str) -> dict[str, Any]:
    """Get aggregated statistics for a group."""
    conn = get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*)                                    as total_posts,
            SUM(reactions_total)                        as total_reactions,
            AVG(reactions_total)                        as avg_reactions,
            SUM(comments_count)                         as total_comments,
            AVG(comments_count)                         as avg_comments,
            SUM(shares_count)                           as total_shares,
            MIN(COALESCE(NULLIF(posted_at,''), scraped_at)) as earliest_post,
            MAX(COALESCE(NULLIF(posted_at,''), scraped_at)) as latest_post
        FROM posts
        WHERE group_id = ?
    """, (group_id,)).fetchone()

    if not row or row["total_posts"] == 0:
        conn.close()
        return {"group_id": group_id, "total_posts": 0}

    # Content type breakdown
    ct_rows = conn.execute("""
        SELECT content_type, COUNT(*) as cnt
        FROM posts WHERE group_id = ?
        GROUP BY content_type ORDER BY cnt DESC
    """, (group_id,)).fetchall()

    # Top posts by reactions
    top_rows = conn.execute("""
        SELECT post_id, author, content, reactions_total, comments_count,
               shares_count, post_url, posted_at
        FROM posts WHERE group_id = ?
        ORDER BY reactions_total DESC LIMIT 10
    """, (group_id,)).fetchall()

    conn.close()

    return {
        "group_id": group_id,
        "total_posts": row["total_posts"],
        "total_reactions": row["total_reactions"] or 0,
        "avg_reactions": round(row["avg_reactions"] or 0, 1),
        "total_comments": row["total_comments"] or 0,
        "avg_comments": round(row["avg_comments"] or 0, 1),
        "total_shares": row["total_shares"] or 0,
        "date_range": {
            "from": row["earliest_post"] or "",
            "to": row["latest_post"] or "",
        },
        "content_types": {r["content_type"]: r["cnt"] for r in ct_rows},
        "top_posts": [
            {
                "post_id": r["post_id"],
                "author": r["author"],
                "preview": (r["content"] or "")[:120],
                "reactions": r["reactions_total"],
                "comments": r["comments_count"],
                "shares": r["shares_count"],
                "post_url": r["post_url"],
                "posted_at": r["posted_at"],
            }
            for r in top_rows
        ],
    }


# ---------------------------------------------------------------------------
# Groups tracking
# ---------------------------------------------------------------------------

def upsert_group(group_id: str, group_url: str) -> None:
    conn = get_conn()
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO groups (group_id, group_url, added_at)
        VALUES (?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET group_url = excluded.group_url
    """, (group_id, group_url, now))
    conn.commit()
    conn.close()


def update_group_after_scrape(group_id: str, last_post_id: str | None = None) -> None:
    conn = get_conn()
    now = datetime.now(tz=timezone.utc).isoformat()
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE group_id = ?", (group_id,)
    ).fetchone()["cnt"]
    conn.execute("""
        UPDATE groups
        SET last_scraped_at = ?, last_post_id = COALESCE(?, last_post_id), total_posts = ?
        WHERE group_id = ?
    """, (now, last_post_id, total, group_id))
    conn.commit()
    conn.close()


def get_group_cursor(group_id: str) -> str | None:
    """Return last_post_id for incremental scraping."""
    conn = get_conn()
    row = conn.execute(
        "SELECT last_post_id FROM groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    conn.close()
    return row["last_post_id"] if row else None


def list_groups() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT group_id, group_url, added_at, last_scraped_at, last_post_id, total_posts
        FROM groups ORDER BY last_scraped_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(group_id: str, from_date: str | None = None, to_date: str | None = None) -> Path:
    """Export posts to CSV file, return path."""
    import csv

    posts = get_posts(group_id, from_date, to_date, limit=100_000)
    if not posts:
        raise ValueError(f"No posts found for group '{group_id}'")

    _ensure_dir()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = _HERE / "data" / f"{group_id}_{ts}.csv"

    fields = [
        "post_id", "group_id", "author", "author_id", "content",
        "content_type", "posted_at", "scraped_at",
        "reactions_total", "comments_count", "shares_count",
        "post_url",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in posts:
            row = dict(p)
            row["reactions_total"] = p.get("reactions", {}).get("total", 0)
            writer.writerow(row)

    _log.info("Exported %d posts to %s", len(posts), path)
    return path
