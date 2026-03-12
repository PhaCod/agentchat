"""
db_index.py — SQLite-backed query index for fast post lookups.

Problem: loading 500+ posts from JSON files into memory just to filter
by date/author/keyword is slow and doesn't scale. This module maintains
a lightweight SQLite index (data/index.db) that allows fast queries.

Index is rebuilt from JSON partition files and stays in sync via sync_group().

Schema:
    posts (
        post_id TEXT PRIMARY KEY,
        group_id TEXT NOT NULL,
        author TEXT,
        author_id TEXT,
        content TEXT,
        content_type TEXT,
        timestamp TEXT,
        scraped_at TEXT,
        scrape_run_id TEXT,
        reactions_total INTEGER,
        comments_count INTEGER,
        shares_count INTEGER,
        post_url TEXT,
        partition TEXT   -- YYYY-MM partition key
    )

Usage:
    from db_index import PostIndex

    idx = PostIndex()
    idx.sync_group("riviu.official")          # rebuild index for group

    # Query examples
    posts = idx.query(group_id="riviu.official", date_from="2026-03-01")
    posts = idx.query(group_id="riviu.official", keyword="son môi")
    posts = idx.query(group_id="riviu.official", author="Nguyễn Hồng Phương")
    stats = idx.stats("riviu.official")
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent
_INDEX_PATH = _HERE / "data" / "index.db"
_POSTS_DIR  = _HERE / "data" / "posts"


def _unwrap(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "posts" in raw:
        return raw["posts"]
    return []


class PostIndex:
    def __init__(self, index_path: Path = _INDEX_PATH):
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.index_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                post_id        TEXT PRIMARY KEY,
                group_id       TEXT NOT NULL,
                author         TEXT,
                author_id      TEXT,
                content        TEXT,
                content_type   TEXT,
                timestamp      TEXT,
                scraped_at     TEXT,
                scrape_run_id  TEXT,
                reactions_total INTEGER DEFAULT 0,
                comments_count  INTEGER DEFAULT 0,
                shares_count    INTEGER DEFAULT 0,
                post_url       TEXT,
                partition      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_group_id  ON posts(group_id);
            CREATE INDEX IF NOT EXISTS idx_timestamp  ON posts(timestamp);
            CREATE INDEX IF NOT EXISTS idx_author     ON posts(author);
            CREATE INDEX IF NOT EXISTS idx_run_id     ON posts(scrape_run_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts
                USING fts5(post_id UNINDEXED, group_id UNINDEXED, content, author,
                           content=posts, content_rowid=rowid);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Index sync
    # ------------------------------------------------------------------

    def _partition_key(self, post: dict) -> str:
        ts = (post.get("timestamp") or "")[:7]
        return ts if (len(ts) == 7 and ts[4] == "-") else "_unknown"

    def _post_to_row(self, post: dict) -> tuple:
        reactions = post.get("reactions") or {}
        return (
            post.get("post_id"),
            post.get("group_id"),
            post.get("author"),
            post.get("author_id"),
            post.get("content"),
            post.get("content_type"),
            post.get("timestamp"),
            post.get("scraped_at"),
            post.get("scrape_run_id"),
            reactions.get("total", 0) if isinstance(reactions, dict) else 0,
            post.get("comments_count", 0),
            post.get("shares_count", 0),
            post.get("post_url"),
            self._partition_key(post),
        )

    def sync_group(self, group_id: str) -> int:
        """Rebuild index for a group from its JSON partition files.
        Returns number of posts indexed.
        """
        posts: list[dict] = []

        # Legacy flat file
        legacy = _POSTS_DIR / f"{group_id}.json"
        if legacy.exists():
            try:
                posts = _unwrap(json.loads(legacy.read_text(encoding="utf-8")))
            except Exception:
                pass

        # Partitioned
        group_dir = _POSTS_DIR / group_id
        if group_dir.is_dir():
            for part_file in sorted(group_dir.glob("*.json")):
                if part_file.name.endswith(".tmp"):
                    continue
                try:
                    posts.extend(_unwrap(json.loads(part_file.read_text(encoding="utf-8"))))
                except Exception:
                    pass

        if not posts:
            return 0

        # Delete existing entries for this group, re-insert
        cur = self._conn.cursor()
        cur.execute("DELETE FROM posts WHERE group_id = ?", (group_id,))
        cur.execute("DELETE FROM posts_fts WHERE group_id = ?", (group_id,))

        rows = [self._post_to_row(p) for p in posts if p.get("post_id")]
        cur.executemany(
            "INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        # Rebuild FTS
        cur.executemany(
            "INSERT INTO posts_fts(post_id, group_id, content, author) VALUES (?,?,?,?)",
            [(r[0], r[1], r[4] or "", r[2] or "") for r in rows],
        )
        self._conn.commit()
        return len(rows)

    def sync_all(self) -> dict[str, int]:
        """Sync all groups. Returns {group_id: post_count}."""
        groups: set[str] = set()
        for f in _POSTS_DIR.glob("*.json"):
            if not f.name.endswith((".tmp", ".bak")):
                groups.add(f.stem)
        for d in _POSTS_DIR.iterdir():
            if d.is_dir():
                groups.add(d.name)
        return {g: self.sync_group(g) for g in sorted(groups)}

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def query(
        self,
        group_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        author: str | None = None,
        keyword: str | None = None,
        content_type: str | None = None,
        min_reactions: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Query posts with optional filters. Returns list of post dicts."""
        clauses = ["group_id = ?"]
        params: list[Any] = [group_id]

        if date_from:
            clauses.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("timestamp <= ?")
            params.append(date_to + "T23:59:59")
        if author:
            clauses.append("author LIKE ?")
            params.append(f"%{author}%")
        if content_type:
            clauses.append("content_type = ?")
            params.append(content_type)
        if min_reactions is not None:
            clauses.append("reactions_total >= ?")
            params.append(min_reactions)

        if keyword:
            # FTS search — get matching post_ids first
            fts_rows = self._conn.execute(
                "SELECT post_id FROM posts_fts WHERE posts_fts MATCH ? AND group_id = ?",
                (keyword, group_id),
            ).fetchall()
            if not fts_rows:
                return []
            pids = [r["post_id"] for r in fts_rows]
            placeholders = ",".join("?" * len(pids))
            clauses.append(f"post_id IN ({placeholders})")
            params.extend(pids)

        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM posts WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        params += [limit, offset]

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self, group_id: str) -> dict[str, Any]:
        """Quick stats for a group from the index."""
        row = self._conn.execute(
            """SELECT
                COUNT(*)            AS post_count,
                MIN(timestamp)      AS oldest,
                MAX(timestamp)      AS newest,
                AVG(reactions_total) AS avg_reactions,
                AVG(comments_count)  AS avg_comments,
                SUM(CASE WHEN timestamp = '' OR timestamp IS NULL THEN 1 ELSE 0 END) AS missing_ts,
                SUM(CASE WHEN author = 'Unknown' OR author IS NULL THEN 1 ELSE 0 END) AS unknown_author
            FROM posts WHERE group_id = ?""",
            (group_id,),
        ).fetchone()
        if not row or row["post_count"] == 0:
            return {"group_id": group_id, "indexed_posts": 0}
        return {
            "group_id":       group_id,
            "indexed_posts":  row["post_count"],
            "date_range":     {"from": row["oldest"], "to": row["newest"]},
            "avg_reactions":  round(row["avg_reactions"] or 0, 2),
            "avg_comments":   round(row["avg_comments"] or 0, 2),
            "missing_timestamp": row["missing_ts"],
            "unknown_author": row["unknown_author"],
        }

    def drop_group(self, group_id: str) -> None:
        self._conn.execute("DELETE FROM posts WHERE group_id = ?", (group_id,))
        self._conn.execute("DELETE FROM posts_fts WHERE group_id = ?", (group_id,))
        self._conn.commit()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SQLite post index manager")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("sync", help="Sync all groups to index")
    p_q = sub.add_parser("query", help="Query posts")
    p_q.add_argument("--group",         required=True)
    p_q.add_argument("--date-from")
    p_q.add_argument("--date-to")
    p_q.add_argument("--author")
    p_q.add_argument("--keyword")
    p_q.add_argument("--content-type")
    p_q.add_argument("--min-reactions",  type=int)
    p_q.add_argument("--limit",          type=int, default=20)

    p_s = sub.add_parser("stats", help="Show index stats for a group")
    p_s.add_argument("--group", required=True)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    with PostIndex() as idx:
        if args.cmd == "sync":
            results = idx.sync_all()
            for g, n in results.items():
                print(f"  {g}: {n} posts indexed")
            print(f"\nTotal: {sum(results.values())} posts across {len(results)} groups")

        elif args.cmd == "stats":
            s = idx.stats(args.group)
            print(json.dumps(s, ensure_ascii=False, indent=2))

        elif args.cmd == "query":
            posts = idx.query(
                group_id=args.group,
                date_from=args.date_from,
                date_to=args.date_to,
                author=args.author,
                keyword=args.keyword,
                content_type=args.content_type,
                min_reactions=args.min_reactions,
                limit=args.limit,
            )
            print(json.dumps(posts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _run_cli()
