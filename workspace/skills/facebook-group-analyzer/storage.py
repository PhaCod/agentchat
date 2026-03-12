"""
storage.py — Production-grade JSON/CSV persistence for posts and analysis results.

Architecture features:
  - Atomic writes  : tmp file + os.replace() — no partial/corrupt writes
  - Concurrency    : .lock file per resource — safe for parallel processes
  - Partitioning   : data/posts/{group_id}/YYYY-MM.json — bounded file sizes
  - Run log        : data/runs/{run_id}.json — full audit trail per scrape run
  - Incremental    : manifest cursor tracks latest post_id + timestamp
  - Backward compat: legacy flat data/posts/{group_id}.json still readable
"""
from __future__ import annotations

import csv
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from log_config import get_logger
from schemas import (
    csv_fieldnames,
    group_manifest_entry,
    manifest_skeleton,
    posts_container,
    post_to_row,
    report_with_schema,
    unwrap_posts,
)

_HERE = Path(__file__).parent
_log = get_logger("storage")

_DATA_DIR   = _HERE / "data"
_POSTS_DIR  = _DATA_DIR / "posts"
_REPORTS_DIR = _DATA_DIR / "reports"
_EXPORTS_DIR = _DATA_DIR / "exports"
_RUNS_DIR   = _DATA_DIR / "runs"
_MANIFEST_PATH = _DATA_DIR / "manifest.json"

_LOCK_TIMEOUT = 15   # seconds before giving up on lock
_LOCK_RETRY   = 0.05  # sleep between retries


def _ensure_dirs() -> None:
    for d in (_POSTS_DIR, _REPORTS_DIR, _EXPORTS_DIR, _RUNS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Atomic writes
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """Write text to path atomically: write tmp, then os.replace (rename).
    os.replace() is atomic on both POSIX and Windows (same filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# 2. Concurrency lock  (cross-platform .lock file)
# ---------------------------------------------------------------------------

@contextmanager
def _lock(path: Path, timeout: float = _LOCK_TIMEOUT) -> Generator:
    """Acquire an exclusive lock for `path` via a companion .lock file.
    Uses O_CREAT|O_EXCL which is atomic on all major OS/filesystems.
    Raises TimeoutError if lock not acquired within timeout seconds.
    """
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Could not acquire lock on {path} within {timeout}s. "
                    f"Delete {lock_path} manually if no other process is running."
                )
            time.sleep(_LOCK_RETRY)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 3. Time-based partitioning helpers
# ---------------------------------------------------------------------------

def _partition_key(post: dict) -> str:
    """Return YYYY-MM partition key from post timestamp, '_unknown' if missing."""
    ts = (post.get("timestamp") or "")[:7]
    if ts and len(ts) == 7 and ts[4] == "-":
        return ts
    return "_unknown"


def _partition_path(group_id: str, partition: str) -> Path:
    return _POSTS_DIR / group_id / f"{partition}.json"


def _list_partition_paths(group_id: str) -> list[Path]:
    group_dir = _POSTS_DIR / group_id
    if not group_dir.is_dir():
        return []
    return sorted(p for p in group_dir.glob("*.json") if not p.name.endswith(".tmp"))


# ---------------------------------------------------------------------------
# Posts storage (partitioned + backward-compat legacy)
# ---------------------------------------------------------------------------

def load_posts(group_id: str) -> list[dict]:
    """Load all posts for a group.
    Supports legacy flat file (data/posts/{id}.json) and
    partitioned format (data/posts/{id}/YYYY-MM.json).
    """
    _ensure_dirs()
    legacy = _POSTS_DIR / f"{group_id}.json"
    if legacy.exists():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            return unwrap_posts(raw)
        except Exception as e:
            _log.warning("Failed to read legacy posts file %s: %s", legacy, e)

    all_posts: list[dict] = []
    for part_path in _list_partition_paths(group_id):
        try:
            raw = json.loads(part_path.read_text(encoding="utf-8"))
            all_posts.extend(unwrap_posts(raw))
        except Exception as e:
            _log.warning("Failed to load partition %s: %s", part_path, e)
    return all_posts


def _valid_post(p: dict, group_id: str) -> bool:
    pid = p.get("post_id")
    gid = p.get("group_id")
    return bool(pid and str(pid).strip() and (gid or group_id))


def save_posts(group_id: str, posts: list[dict], run_id: str | None = None) -> Path:
    """Save posts with:
    - Atomic writes per partition file
    - Exclusive lock per partition (safe for concurrent processes)
    - Time-based partitioning by YYYY-MM
    - run_id stamped on each post for lineage
    Returns the group partition directory.
    """
    _ensure_dirs()

    for p in posts:
        if not p.get("group_id"):
            p["group_id"] = group_id
        if run_id and not p.get("scrape_run_id"):
            p["scrape_run_id"] = run_id

    valid_posts = [p for p in posts if _valid_post(p, group_id)]
    dropped = len(posts) - len(valid_posts)
    if dropped:
        _log.warning("Dropped %s posts missing post_id or group_id", dropped)

    # Group by partition key (YYYY-MM or _unknown)
    by_partition: dict[str, list[dict]] = {}
    for p in valid_posts:
        by_partition.setdefault(_partition_key(p), []).append(p)

    group_dir = _POSTS_DIR / group_id
    group_dir.mkdir(parents=True, exist_ok=True)
    total_new = 0

    for partition, new_posts in by_partition.items():
        part_path = _partition_path(group_id, partition)
        with _lock(part_path):
            existing: list[dict] = []
            if part_path.exists():
                try:
                    raw = json.loads(part_path.read_text(encoding="utf-8"))
                    existing = unwrap_posts(raw)
                except Exception:
                    pass
            existing_ids = {p["post_id"] for p in existing}
            truly_new = [p for p in new_posts if p["post_id"] not in existing_ids]
            merged = existing + truly_new
            container = posts_container(group_id, merged)
            _atomic_write(part_path, json.dumps(container, ensure_ascii=False, indent=2))
            total_new += len(truly_new)
            _log.info(
                "Partition %s/%s: +%s new (%s total)",
                group_id, partition, len(truly_new), len(merged),
            )

    all_posts = load_posts(group_id)
    _log.info(
        "Saved %s new posts (%s total across all partitions) for %s",
        total_new, len(all_posts), group_id,
    )
    _update_manifest_after_posts(group_id, all_posts, run_id=run_id)
    return group_dir


def delete_posts(group_id: str) -> None:
    legacy = _POSTS_DIR / f"{group_id}.json"
    if legacy.exists():
        legacy.unlink()
    group_dir = _POSTS_DIR / group_id
    if group_dir.is_dir():
        for f in group_dir.glob("*.json"):
            f.unlink(missing_ok=True)
        try:
            group_dir.rmdir()
        except OSError:
            pass
    _update_manifest_after_posts(group_id, [])
    _log.info("Deleted posts for %s", group_id)


# ---------------------------------------------------------------------------
# Report storage
# ---------------------------------------------------------------------------

def load_report(group_id: str) -> dict | None:
    _ensure_dirs()
    path = _REPORTS_DIR / f"{group_id}_analysis.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_report(group_id: str, report: dict) -> Path:
    _ensure_dirs()
    path = _REPORTS_DIR / f"{group_id}_analysis.json"
    with _lock(path):
        payload = report_with_schema(report)
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    _log.info("Report saved -> %s", path)
    _update_manifest_after_report(group_id, report)
    return path


# ---------------------------------------------------------------------------
# 4. Scrape Run Log  (data/runs/{run_id}.json)
# ---------------------------------------------------------------------------

def start_run(
    group_id: str,
    group_url: str,
    trigger: str = "manual",
    settings: dict | None = None,
) -> str:
    """Create a run log entry. Returns run_id.
    Call this before scraping; call finish_run() when done.
    """
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{ts}_{group_id}"
    path = _RUNS_DIR / f"{run_id}.json"
    entry = {
        "run_id": run_id,
        "group_id": group_id,
        "group_url": group_url,
        "trigger": trigger,
        "settings": settings or {},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "running",
        "posts_scraped": 0,
        "posts_saved": 0,
        "errors": [],
    }
    _atomic_write(path, json.dumps(entry, ensure_ascii=False, indent=2))
    _log.info("Run started: %s", run_id)
    return run_id


def finish_run(
    run_id: str,
    posts_scraped: int = 0,
    posts_saved: int = 0,
    status: str = "success",
    errors: list | None = None,
) -> None:
    """Update run log with completion status and stats."""
    _ensure_dirs()
    path = _RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        entry["status"] = status
        entry["posts_scraped"] = posts_scraped
        entry["posts_saved"] = posts_saved
        entry["errors"] = errors or []
        _atomic_write(path, json.dumps(entry, ensure_ascii=False, indent=2))
        _log.info("Run finished: %s (%s) — %s posts", run_id, status, posts_saved)
    except Exception as e:
        _log.warning("Could not update run log %s: %s", run_id, e)


def load_run(run_id: str) -> dict | None:
    path = _RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_runs(group_id: str | None = None, limit: int = 20) -> list[dict]:
    """Return recent run logs sorted newest-first, optionally filtered by group."""
    _ensure_dirs()
    runs: list[dict] = []
    for f in sorted(_RUNS_DIR.glob("*.json"), reverse=True):
        if len(runs) >= limit:
            break
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            if group_id is None or r.get("group_id") == group_id:
                runs.append(r)
        except Exception:
            continue
    return runs


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(group_id: str, posts: list[dict]) -> Path:
    _ensure_dirs()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = _EXPORTS_DIR / f"{group_id}_{ts}.csv"
    fields = csv_fieldnames()
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in posts:
            writer.writerow(post_to_row(p))
    _log.info("CSV exported -> %s", path)
    return path


# ---------------------------------------------------------------------------
# 5. Manifest + Incremental cursor
# ---------------------------------------------------------------------------

def load_manifest() -> dict[str, Any]:
    _ensure_dirs()
    if not _MANIFEST_PATH.exists():
        return manifest_skeleton()
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return manifest_skeleton()


def save_manifest(manifest: dict) -> Path:
    _ensure_dirs()
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock(_MANIFEST_PATH):
        _atomic_write(_MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False, indent=2))
    return _MANIFEST_PATH


def _update_manifest_after_posts(
    group_id: str, posts: list[dict], run_id: str | None = None
) -> None:
    manifest = load_manifest()
    groups = {g["group_id"]: g for g in manifest.get("groups", [])}
    if not posts:
        groups.pop(group_id, None)
        manifest["groups"] = list(groups.values())
        save_manifest(manifest)
        return

    dates = [
        p.get("timestamp", "")[:10]
        for p in posts
        if len(p.get("timestamp", "")) >= 10
    ]
    date_from = min(dates) if dates else None
    date_to   = max(dates) if dates else None
    now_iso   = datetime.now(tz=timezone.utc).isoformat()

    # Incremental cursor: latest post by timestamp for next incremental scrape
    cursor: dict | None = None
    timestamped = [p for p in posts if p.get("timestamp")]
    if timestamped:
        latest = max(timestamped, key=lambda p: p.get("timestamp", ""))
        cursor = {
            "last_post_id":        latest.get("post_id"),
            "last_post_timestamp": latest.get("timestamp"),
            "last_run_id":         run_id,
            "updated_at":          now_iso,
        }

    existing = groups.get(group_id, {})
    new_entry = group_manifest_entry(
        group_id, len(posts), date_from, date_to,
        last_scraped_at=now_iso,
        last_analyzed_at=existing.get("last_analyzed_at"),
    )
    if cursor:
        new_entry["cursor"] = cursor
    groups[group_id] = new_entry
    manifest["groups"] = list(groups.values())
    save_manifest(manifest)


def _update_manifest_after_report(group_id: str, report: dict) -> None:
    manifest = load_manifest()
    groups = {g["group_id"]: g for g in manifest.get("groups", [])}
    total = report.get("total_posts", 0)
    dr = report.get("date_range", {}) or {}
    analyzed_at = report.get("analyzed_at")

    if group_id not in groups:
        groups[group_id] = group_manifest_entry(
            group_id, total, dr.get("from"), dr.get("to"),
            last_analyzed_at=analyzed_at,
        )
    else:
        groups[group_id]["post_count"] = total
        groups[group_id]["date_range"] = {"from": dr.get("from"), "to": dr.get("to")}
        groups[group_id]["last_analyzed_at"] = analyzed_at

    manifest["groups"] = list(groups.values())
    save_manifest(manifest)


# ---------------------------------------------------------------------------
# List / stats
# ---------------------------------------------------------------------------

def list_groups() -> list[str]:
    _ensure_dirs()
    groups: set[str] = set()
    for f in _POSTS_DIR.glob("*.json"):
        if not f.name.endswith(".tmp"):
            groups.add(f.stem)
    for d in _POSTS_DIR.iterdir():
        if d.is_dir():
            groups.add(d.name)
    return sorted(groups)


def group_stats(group_id: str) -> dict[str, Any]:
    posts = load_posts(group_id)
    if not posts:
        return {"group_id": group_id, "post_count": 0}
    dates = []
    for p in posts:
        t = p.get("timestamp", "")
        if t:
            try:
                dates.append(datetime.fromisoformat(t).date().isoformat())
            except ValueError:
                pass
    return {
        "group_id": group_id,
        "post_count": len(posts),
        "date_range": {"from": min(dates) if dates else None, "to": max(dates) if dates else None},
    }
