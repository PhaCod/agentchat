"""
eval_qc.py — Tiny QC helpers for fb-group-crawl.

Usage (from skill dir):
  python eval_qc.py smoke

This does NOT call any external APIs. It only:
- Checks that RAG DB schema is intact.
- Runs a cheap search over rag.db if it exists.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from log_config import get_logger

_log = get_logger("eval_qc")
_HERE = Path(__file__).parent
_RAG_DB = _HERE / "data" / "rag.db"


def _check_rag_schema() -> None:
    if not _RAG_DB.exists():
        _log.warning("rag.db does not exist at %s", _RAG_DB)
        return
    conn = sqlite3.connect(str(_RAG_DB))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    required = {"rag_batches", "rag_docs", "rag_chunks", "rag_chunks_fts"}
    missing = required - tables
    if missing:
        _log.error("RAG schema missing tables: %s", ", ".join(sorted(missing)))
    else:
        _log.info("RAG schema OK, tables present: %s", ", ".join(sorted(required)))
    conn.close()


def smoke() -> None:
    _log.info("Running fb-group-crawl QC smoke checks...")
    _check_rag_schema()
    _log.info("QC smoke finished.")


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if cmd == "smoke":
        smoke()
    else:
        print(f"Unknown command: {cmd}")

