"""
db.py — SQLite schema and CRUD for social-brand-tracker.

Tables: posts, comments, users, hashtags, mentions, analysis_runs
+ FTS5 on posts.content and comments.content
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
_DB_PATH = _HERE / "data" / "brand_tracker.db"
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db() -> None:
    conn = _get_conn()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS posts (
        post_id       TEXT PRIMARY KEY,
        source_id     TEXT NOT NULL,
        source_type   TEXT NOT NULL DEFAULT 'group',
        author_id     TEXT DEFAULT '',
        author_name   TEXT DEFAULT '',
        content       TEXT DEFAULT '',
        post_url      TEXT DEFAULT '',
        media_type    TEXT DEFAULT 'text',
        reactions_total  INTEGER DEFAULT 0,
        comments_count   INTEGER DEFAULT 0,
        shares_count     INTEGER DEFAULT 0,
        views_count      INTEGER DEFAULT 0,
        posted_at     TEXT DEFAULT '',
        scraped_at    TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS comments (
        comment_id        TEXT PRIMARY KEY,
        post_id           TEXT NOT NULL,
        parent_comment_id TEXT DEFAULT NULL,
        commenter_id      TEXT DEFAULT '',
        commenter_name    TEXT DEFAULT '',
        is_verified       INTEGER DEFAULT 0,
        content           TEXT DEFAULT '',
        likes_count       INTEGER DEFAULT 0,
        replies_count     INTEGER DEFAULT 0,
        posted_at         TEXT DEFAULT '',
        scraped_at        TEXT DEFAULT '',
        FOREIGN KEY (post_id) REFERENCES posts(post_id)
    );

    CREATE TABLE IF NOT EXISTS users (
        user_id         TEXT PRIMARY KEY,
        username        TEXT DEFAULT '',
        display_name    TEXT DEFAULT '',
        follower_count  INTEGER DEFAULT 0,
        is_influencer   INTEGER DEFAULT 0,
        is_verified     INTEGER DEFAULT 0,
        location        TEXT DEFAULT '',
        bio_keywords    TEXT DEFAULT '',
        first_seen      TEXT DEFAULT '',
        last_seen       TEXT DEFAULT '',
        total_posts     INTEGER DEFAULT 0,
        total_comments  INTEGER DEFAULT 0,
        avg_engagement  REAL DEFAULT 0.0
    );

    CREATE TABLE IF NOT EXISTS hashtags (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_raw        TEXT NOT NULL,
        tag_normalized TEXT NOT NULL,
        post_id        TEXT,
        comment_id     TEXT,
        source_id      TEXT DEFAULT '',
        posted_at      TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS mentions (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        mention_raw        TEXT NOT NULL,
        mention_normalized TEXT NOT NULL,
        mention_type       TEXT DEFAULT 'user',
        post_id            TEXT,
        comment_id         TEXT,
        sentiment          TEXT DEFAULT 'neutral',
        source_id          TEXT DEFAULT '',
        posted_at          TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS analysis_runs (
        run_id          TEXT PRIMARY KEY,
        source_id       TEXT NOT NULL,
        run_type        TEXT NOT NULL,
        config_snapshot TEXT DEFAULT '{}',
        results         TEXT DEFAULT '{}',
        created_at      TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source_id);
    CREATE INDEX IF NOT EXISTS idx_posts_posted ON posts(posted_at);
    CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
    CREATE INDEX IF NOT EXISTS idx_comments_posted ON comments(posted_at);
    CREATE INDEX IF NOT EXISTS idx_hashtags_tag ON hashtags(tag_normalized);
    CREATE INDEX IF NOT EXISTS idx_hashtags_post ON hashtags(post_id);
    CREATE INDEX IF NOT EXISTS idx_mentions_norm ON mentions(mention_normalized);
    CREATE INDEX IF NOT EXISTS idx_mentions_post ON mentions(post_id);
    """)

    # FTS5 virtual tables
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
                content, post_id UNINDEXED, source_id UNINDEXED,
                content='posts', content_rowid='rowid'
            )
        """)
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS comments_fts USING fts5(
                content, comment_id UNINDEXED, post_id UNINDEXED,
                content='comments', content_rowid='rowid'
            )
        """)
    except sqlite3.OperationalError:
        pass

    conn.commit()
    _log.info("Database initialized at %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Posts CRUD
# ---------------------------------------------------------------------------

def upsert_post(post: dict) -> bool:
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO posts (post_id, source_id, source_type, author_id, author_name,
                               content, post_url, media_type, reactions_total,
                               comments_count, shares_count, views_count,
                               posted_at, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
                content=excluded.content, reactions_total=excluded.reactions_total,
                comments_count=excluded.comments_count, shares_count=excluded.shares_count,
                views_count=excluded.views_count, scraped_at=excluded.scraped_at
        """, (
            post["post_id"], post["source_id"], post.get("source_type", "group"),
            post.get("author_id", ""), post.get("author_name", ""),
            post.get("content", ""), post.get("post_url", ""),
            post.get("media_type", "text"), post.get("reactions_total", 0),
            post.get("comments_count", 0), post.get("shares_count", 0),
            post.get("views_count", 0), post.get("posted_at", ""),
            post.get("scraped_at", datetime.now(tz=timezone.utc).isoformat()),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def upsert_posts(posts: list[dict]) -> dict:
    inserted, skipped = 0, 0
    for p in posts:
        if upsert_post(p):
            inserted += 1
        else:
            skipped += 1
    _rebuild_fts("posts")
    return {"inserted": inserted, "skipped": skipped}


def get_posts(source_id: str, days: int = 7, limit: int = 500) -> list[dict]:
    conn = _get_conn()
    from datetime import timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM posts
        WHERE source_id = ? AND COALESCE(posted_at, scraped_at) >= ?
        ORDER BY COALESCE(posted_at, scraped_at) DESC
        LIMIT ?
    """, (source_id, cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


def count_posts(source_id: str) -> int:
    conn = _get_conn()
    return conn.execute(
        "SELECT COUNT(*) FROM posts WHERE source_id = ?", (source_id,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Comments CRUD
# ---------------------------------------------------------------------------

def upsert_comment(comment: dict) -> bool:
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO comments (comment_id, post_id, parent_comment_id,
                                  commenter_id, commenter_name, is_verified,
                                  content, likes_count, replies_count,
                                  posted_at, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(comment_id) DO UPDATE SET
                content=excluded.content, likes_count=excluded.likes_count,
                replies_count=excluded.replies_count, scraped_at=excluded.scraped_at
        """, (
            comment["comment_id"], comment["post_id"],
            comment.get("parent_comment_id"),
            comment.get("commenter_id", ""), comment.get("commenter_name", ""),
            1 if comment.get("is_verified") else 0,
            comment.get("content", ""),
            comment.get("likes_count", 0), comment.get("replies_count", 0),
            comment.get("posted_at", ""),
            comment.get("scraped_at", datetime.now(tz=timezone.utc).isoformat()),
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def upsert_comments(comments: list[dict]) -> dict:
    inserted, skipped = 0, 0
    for c in comments:
        if upsert_comment(c):
            inserted += 1
        else:
            skipped += 1
    _rebuild_fts("comments")
    return {"inserted": inserted, "skipped": skipped}


def get_comments(post_id: str | None = None, source_id: str | None = None,
                 days: int = 7, limit: int = 1000) -> list[dict]:
    conn = _get_conn()
    from datetime import timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()

    if post_id:
        rows = conn.execute("""
            SELECT * FROM comments WHERE post_id = ?
            ORDER BY posted_at ASC LIMIT ?
        """, (post_id, limit)).fetchall()
    elif source_id:
        rows = conn.execute("""
            SELECT c.* FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE p.source_id = ? AND COALESCE(c.posted_at, c.scraped_at) >= ?
            ORDER BY c.posted_at DESC LIMIT ?
        """, (source_id, cutoff, limit)).fetchall()
    else:
        rows = []
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

def upsert_user(user: dict) -> None:
    conn = _get_conn()
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO users (user_id, username, display_name, follower_count,
                           is_influencer, is_verified, location, bio_keywords,
                           first_seen, last_seen, total_posts, total_comments)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            display_name=excluded.display_name,
            follower_count=MAX(users.follower_count, excluded.follower_count),
            is_influencer=excluded.is_influencer,
            last_seen=excluded.last_seen,
            total_posts=users.total_posts + excluded.total_posts,
            total_comments=users.total_comments + excluded.total_comments
    """, (
        user["user_id"], user.get("username", ""), user.get("display_name", ""),
        user.get("follower_count", 0),
        1 if user.get("follower_count", 0) >= 10000 else 0,
        1 if user.get("is_verified") else 0,
        user.get("location", ""), user.get("bio_keywords", ""),
        now, now,
        user.get("total_posts", 0), user.get("total_comments", 0),
    ))
    conn.commit()


# ---------------------------------------------------------------------------
# Hashtags & Mentions
# ---------------------------------------------------------------------------

def insert_hashtags(tags: list[dict]) -> int:
    conn = _get_conn()
    count = 0
    for t in tags:
        conn.execute("""
            INSERT INTO hashtags (tag_raw, tag_normalized, post_id, comment_id,
                                  source_id, posted_at)
            VALUES (?,?,?,?,?,?)
        """, (
            t["tag_raw"], t["tag_normalized"],
            t.get("post_id"), t.get("comment_id"),
            t.get("source_id", ""), t.get("posted_at", ""),
        ))
        count += 1
    conn.commit()
    return count


def insert_mentions(mentions: list[dict]) -> int:
    conn = _get_conn()
    count = 0
    for m in mentions:
        conn.execute("""
            INSERT INTO mentions (mention_raw, mention_normalized, mention_type,
                                  post_id, comment_id, sentiment, source_id, posted_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            m["mention_raw"], m["mention_normalized"],
            m.get("mention_type", "user"),
            m.get("post_id"), m.get("comment_id"),
            m.get("sentiment", "neutral"),
            m.get("source_id", ""), m.get("posted_at", ""),
        ))
        count += 1
    conn.commit()
    return count


def get_hashtag_counts(source_id: str, days: int = 7, limit: int = 50) -> list[dict]:
    conn = _get_conn()
    from datetime import timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT tag_normalized, COUNT(*) as count
        FROM hashtags
        WHERE source_id = ? AND posted_at >= ?
        GROUP BY tag_normalized
        ORDER BY count DESC
        LIMIT ?
    """, (source_id, cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


def get_mention_counts(source_id: str, days: int = 7, limit: int = 50) -> list[dict]:
    conn = _get_conn()
    from datetime import timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT mention_normalized, mention_type, COUNT(*) as count,
               SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) as positive,
               SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) as negative,
               SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) as neutral
        FROM mentions
        WHERE source_id = ? AND posted_at >= ?
        GROUP BY mention_normalized
        ORDER BY count DESC
        LIMIT ?
    """, (source_id, cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Analysis Runs
# ---------------------------------------------------------------------------

def save_analysis_run(run_id: str, source_id: str, run_type: str,
                      config_snapshot: dict, results: dict) -> None:
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO analysis_runs (run_id, source_id, run_type,
                                              config_snapshot, results, created_at)
        VALUES (?,?,?,?,?,?)
    """, (
        run_id, source_id, run_type,
        json.dumps(config_snapshot, ensure_ascii=False),
        json.dumps(results, ensure_ascii=False),
        datetime.now(tz=timezone.utc).isoformat(),
    ))
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def search_posts(source_id: str, query: str, limit: int = 20) -> list[dict]:
    conn = _get_conn()
    safe_q = " ".join(
        w for w in query.split()
        if not any(c in w for c in "(){}[]*/\\")
    )
    if not safe_q:
        return []
    try:
        rows = conn.execute("""
            SELECT p.* FROM posts_fts f
            JOIN posts p ON p.rowid = f.rowid
            WHERE posts_fts MATCH ? AND p.source_id = ?
            LIMIT ?
        """, (safe_q, source_id, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _rebuild_fts(table: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(f"INSERT INTO {table}_fts({table}_fts) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError:
        pass
