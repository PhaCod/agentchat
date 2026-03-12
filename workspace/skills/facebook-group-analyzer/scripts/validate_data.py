#!/usr/bin/env python3
"""
QC: Validate posts and reports against schema; report data quality issues.
Run from skill root: python scripts/validate_data.py [--group GROUP_ID] [--output json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from schemas import POST_REQUIRED_FIELDS, REPORT_TOP_LEVEL_KEYS, unwrap_posts


def validate_post(p: dict, index: int) -> list[str]:
    """Return list of issue messages for this post."""
    issues = []
    for field in POST_REQUIRED_FIELDS:
        if field not in p:
            issues.append(f"missing field '{field}'")
            continue
        val = p[field]
        if field == "reactions":
            if not isinstance(val, dict) or "total" not in val:
                issues.append("reactions must be dict with 'total'")
        elif field == "media":
            if not isinstance(val, list):
                issues.append("media must be list")
        elif field in ("timestamp", "content", "author", "post_url"):
            if not val and isinstance(val, str):
                pass  # empty string allowed but will be flagged in quality
        elif field in ("comments_count", "shares_count"):
            if not isinstance(val, (int, float)) and val is not None:
                issues.append(f"{field} must be number")
    # Data quality (not schema) flags
    if not (p.get("timestamp") or "").strip():
        issues.append("empty timestamp")
    if (p.get("author") or "").strip() in ("", "Unknown"):
        issues.append("author unknown/empty")
    if not (p.get("content") or "").strip():
        issues.append("empty content")
    if (p.get("post_id") or "").startswith("unknown_"):
        issues.append("fallback post_id (parse failed)")
    return issues


def validate_report(report: dict) -> list[str]:
    """Return list of issue messages for this report."""
    issues = []
    for key in ("group_id", "analyzed_at", "total_posts", "sentiment", "engagement"):
        if key not in report:
            issues.append(f"report missing key '{key}'")
    if "date_range" in report and isinstance(report["date_range"], dict):
        dr = report["date_range"]
        if not dr.get("from") and "_note" not in dr and report.get("total_posts", 0) > 0:
            issues.append("date_range empty despite having posts (likely all posts have empty timestamp)")
    if "sentiment" in report:
        s = report["sentiment"]
        if not isinstance(s, dict) or "distribution_pct" not in s:
            issues.append("sentiment must have distribution_pct")
    return issues


def run_validation(group_id: str | None = None, output_format: str = "text") -> dict:
    import storage
    groups = [group_id] if group_id else storage.list_groups()
    if not groups:
        return {"status": "ok", "groups": [], "message": "No groups to validate"}

    result = {"status": "ok", "groups": []}
    for gid in groups:
        posts_raw = None
        path_posts = root / "data" / "posts" / f"{gid}.json"
        if path_posts.exists():
            posts_raw = json.loads(path_posts.read_text(encoding="utf-8"))
        posts = unwrap_posts(posts_raw) if posts_raw else []

        post_issues = []
        quality = {"total": len(posts), "valid": 0, "with_issues": 0, "empty_timestamp": 0, "unknown_author": 0, "empty_content": 0, "fallback_id": 0}
        for i, p in enumerate(posts):
            issues = validate_post(p, i)
            if not issues:
                quality["valid"] += 1
            else:
                quality["with_issues"] += 1
                if any("empty timestamp" in iss for iss in issues):
                    quality["empty_timestamp"] += 1
                if any("author unknown" in iss for iss in issues):
                    quality["unknown_author"] += 1
                if any("empty content" in iss for iss in issues):
                    quality["empty_content"] += 1
                if any("fallback post_id" in iss for iss in issues):
                    quality["fallback_id"] += 1
                post_issues.append({"index": i, "post_id": p.get("post_id"), "issues": issues})

        report = storage.load_report(gid)
        report_issues = validate_report(report) if report else ["no report file"]

        result["groups"].append({
            "group_id": gid,
            "post_count": len(posts),
            "quality": quality,
            "post_issues_sample": post_issues[:20],
            "report_issues": report_issues,
            "report_exists": report is not None,
        })

    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description="Validate posts and reports (QC)")
    p.add_argument("--group", help="Validate only this group_id")
    p.add_argument("--output", default="text", choices=["text", "json"])
    args = p.parse_args()
    out = run_validation(group_id=args.group, output_format=args.output)
    if args.output == "json":
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for g in out.get("groups", []):
            print(f"\n--- Group: {g['group_id']} ---")
            print(f"  Posts: {g['post_count']}; quality: {g['quality']}")
            print(f"  Report exists: {g['report_exists']}; issues: {g['report_issues']}")
            if g.get("post_issues_sample"):
                print(f"  Sample post issues (first 5):")
                for s in g["post_issues_sample"][:5]:
                    print(f"    [{s['index']}] {s['post_id']}: {s['issues']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
