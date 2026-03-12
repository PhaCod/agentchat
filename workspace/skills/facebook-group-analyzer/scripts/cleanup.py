"""
cleanup.py — TTL-based data retention enforcement.

Reads retention settings from config/config.json:
  retention.posts_ttl_days   (default 90)  — partition files older than N days
  retention.reports_ttl_days (default 180) — report files older than N days
  retention.runs_ttl_days    (default 30)  — run log files older than N days
  retention.exports_ttl_days (default 7)   — CSV exports older than N days

Deletion is based on file modification time (mtime).
Partitioned posts: data/posts/{group_id}/YYYY-MM.json files are checked per partition.
Legacy flat files: data/posts/{group_id}.json are also checked.

Usage:
    python scripts/cleanup.py                    # use config defaults
    python scripts/cleanup.py --dry-run          # preview only
    python scripts/cleanup.py --posts-ttl 60     # override posts TTL
    python scripts/cleanup.py --group riviu.official  # one group only
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))


def _load_cfg() -> dict:
    from load_config import load_config
    return load_config()


def _file_age_days(path: Path) -> float:
    mtime = path.stat().st_mtime
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)
    return age.total_seconds() / 86400


def _delete(path: Path, dry_run: bool) -> None:
    age = _file_age_days(path)
    if dry_run:
        print(f"  [DRY-RUN] Would delete {path.relative_to(_HERE)} (age: {age:.1f}d)")
    else:
        path.unlink(missing_ok=True)
        print(f"  Deleted {path.relative_to(_HERE)} (age: {age:.1f}d)")


def cleanup_posts(
    ttl_days: int, group_id: str | None = None, dry_run: bool = False
) -> int:
    """Delete post partition files older than ttl_days. Returns count deleted."""
    posts_dir = _HERE / "data" / "posts"
    deleted = 0

    # Partitioned format
    for group_dir in posts_dir.iterdir():
        if not group_dir.is_dir():
            continue
        if group_id and group_dir.name != group_id:
            continue
        for part_file in group_dir.glob("*.json"):
            if part_file.name.endswith(".tmp"):
                continue
            if _file_age_days(part_file) > ttl_days:
                _delete(part_file, dry_run)
                deleted += 1

    # Legacy flat files
    for flat in posts_dir.glob("*.json"):
        if flat.name.endswith(".tmp") or flat.name.endswith(".bak"):
            continue
        if group_id and flat.stem != group_id:
            continue
        if _file_age_days(flat) > ttl_days:
            _delete(flat, dry_run)
            deleted += 1

    return deleted


def cleanup_reports(ttl_days: int, group_id: str | None = None, dry_run: bool = False) -> int:
    reports_dir = _HERE / "data" / "reports"
    deleted = 0
    for f in reports_dir.glob("*_analysis.json"):
        if group_id and not f.name.startswith(f"{group_id}_"):
            continue
        if _file_age_days(f) > ttl_days:
            _delete(f, dry_run)
            deleted += 1
    return deleted


def cleanup_runs(ttl_days: int, dry_run: bool = False) -> int:
    runs_dir = _HERE / "data" / "runs"
    if not runs_dir.exists():
        return 0
    deleted = 0
    for f in runs_dir.glob("*.json"):
        if _file_age_days(f) > ttl_days:
            _delete(f, dry_run)
            deleted += 1
    return deleted


def cleanup_exports(ttl_days: int, group_id: str | None = None, dry_run: bool = False) -> int:
    exports_dir = _HERE / "data" / "exports"
    if not exports_dir.exists():
        return 0
    deleted = 0
    for f in exports_dir.glob("*.csv"):
        if group_id and not f.name.startswith(f"{group_id}_"):
            continue
        if _file_age_days(f) > ttl_days:
            _delete(f, dry_run)
            deleted += 1
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="TTL-based data retention cleanup")
    parser.add_argument("--dry-run",       action="store_true", help="Preview without deleting")
    parser.add_argument("--group",         help="Limit cleanup to one group_id")
    parser.add_argument("--posts-ttl",     type=int, help="Override posts TTL in days")
    parser.add_argument("--reports-ttl",   type=int, help="Override reports TTL in days")
    parser.add_argument("--runs-ttl",      type=int, help="Override runs TTL in days")
    parser.add_argument("--exports-ttl",   type=int, help="Override exports TTL in days")
    args = parser.parse_args()

    cfg = _load_cfg().get("retention", {})
    posts_ttl   = args.posts_ttl   or cfg.get("posts_ttl_days",   90)
    reports_ttl = args.reports_ttl or cfg.get("reports_ttl_days", 180)
    runs_ttl    = args.runs_ttl    or cfg.get("runs_ttl_days",    30)
    exports_ttl = args.exports_ttl or cfg.get("exports_ttl_days", 7)

    label = "DRY-RUN " if args.dry_run else ""
    print(f"{label}Cleanup started — TTL: posts={posts_ttl}d, reports={reports_ttl}d, "
          f"runs={runs_ttl}d, exports={exports_ttl}d")
    if args.group:
        print(f"Filtering to group: {args.group}")
    print()

    print("Posts:")
    n = cleanup_posts(posts_ttl, group_id=args.group, dry_run=args.dry_run)
    print(f"  -> {n} file(s) {'would be ' if args.dry_run else ''}deleted\n")

    print("Reports:")
    n = cleanup_reports(reports_ttl, group_id=args.group, dry_run=args.dry_run)
    print(f"  -> {n} file(s) {'would be ' if args.dry_run else ''}deleted\n")

    print("Run logs:")
    n = cleanup_runs(runs_ttl, dry_run=args.dry_run)
    print(f"  -> {n} file(s) {'would be ' if args.dry_run else ''}deleted\n")

    print("Exports:")
    n = cleanup_exports(exports_ttl, group_id=args.group, dry_run=args.dry_run)
    print(f"  -> {n} file(s) {'would be ' if args.dry_run else ''}deleted\n")

    print("Done.")


if __name__ == "__main__":
    main()
