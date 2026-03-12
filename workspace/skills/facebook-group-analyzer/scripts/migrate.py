"""
migrate.py — Schema migration utility.

Migrations:
  v1.0-flat → v1.1-partitioned
      Reads legacy data/posts/{group_id}.json flat files and redistributes
      posts into data/posts/{group_id}/YYYY-MM.json partitions.
      Backs up the original file to data/posts/{group_id}.json.bak before migrating.

Usage:
    python scripts/migrate.py                    # migrate all groups
    python scripts/migrate.py --group riviu.official
    python scripts/migrate.py --dry-run          # preview only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from schemas import posts_container, unwrap_posts, POSTS_SCHEMA_VERSION

_POSTS_DIR = _HERE / "data" / "posts"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _partition_key(post: dict) -> str:
    ts = (post.get("timestamp") or "")[:7]
    if ts and len(ts) == 7 and ts[4] == "-":
        return ts
    return "_unknown"


def migrate_group(group_id: str, dry_run: bool = False) -> dict:
    """Migrate a single group from flat file to partitioned format.
    Returns a summary dict.
    """
    flat_file = _POSTS_DIR / f"{group_id}.json"
    if not flat_file.exists():
        return {"group_id": group_id, "status": "skipped", "reason": "no flat file"}

    # Check if already migrated
    group_dir = _POSTS_DIR / group_id
    if group_dir.is_dir() and any(group_dir.glob("*.json")):
        return {"group_id": group_id, "status": "skipped", "reason": "already partitioned"}

    raw = json.loads(flat_file.read_text(encoding="utf-8"))
    posts = unwrap_posts(raw)
    schema_ver = raw.get("schema_version", "unknown") if isinstance(raw, dict) else "legacy-array"

    if not posts:
        return {"group_id": group_id, "status": "skipped", "reason": "no posts in file"}

    # Group posts by partition
    by_partition: dict[str, list[dict]] = {}
    for p in posts:
        by_partition.setdefault(_partition_key(p), []).append(p)

    summary = {
        "group_id":       group_id,
        "status":         "dry-run" if dry_run else "migrated",
        "source_schema":  schema_ver,
        "total_posts":    len(posts),
        "partitions":     {},
    }

    for partition, part_posts in by_partition.items():
        summary["partitions"][partition] = len(part_posts)

    if dry_run:
        return summary

    # Backup original
    backup = flat_file.with_suffix(".json.bak")
    shutil.copy2(flat_file, backup)
    print(f"  Backed up {flat_file.name} -> {backup.name}")

    # Write partitions
    group_dir.mkdir(parents=True, exist_ok=True)
    for partition, part_posts in by_partition.items():
        part_path = group_dir / f"{partition}.json"
        container = posts_container(group_id, part_posts)
        _atomic_write(part_path, json.dumps(container, ensure_ascii=False, indent=2))
        print(f"  Written {partition}.json ({len(part_posts)} posts)")

    # Remove original flat file after successful migration
    flat_file.unlink()
    print(f"  Removed flat file {flat_file.name}")

    summary["status"] = "migrated"
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate flat posts files to partitioned format")
    parser.add_argument("--group", help="Migrate a specific group only")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    _POSTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.group:
        groups = [args.group]
    else:
        groups = [f.stem for f in _POSTS_DIR.glob("*.json") if not f.name.endswith(".bak")]

    if not groups:
        print("No groups to migrate.")
        return

    print(f"{'DRY RUN — ' if args.dry_run else ''}Migrating {len(groups)} group(s)...\n")
    results = []
    for group_id in groups:
        print(f"Group: {group_id}")
        result = migrate_group(group_id, dry_run=args.dry_run)
        print(f"  Status: {result['status']}")
        if "total_posts" in result:
            print(f"  Posts:  {result['total_posts']}")
        if "partitions" in result:
            for part, count in result["partitions"].items():
                print(f"    {part}: {count} posts")
        print()
        results.append(result)

    migrated = sum(1 for r in results if r["status"] == "migrated")
    skipped  = sum(1 for r in results if r["status"] == "skipped")
    print(f"Done. Migrated: {migrated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
