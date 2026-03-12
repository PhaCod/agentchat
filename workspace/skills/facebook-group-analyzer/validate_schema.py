"""
validate_schema.py — Runtime JSON schema validation for posts, reports, and containers.

Validates data at ingestion and export boundaries without external dependencies.
All validators return a list of ValidationError; empty list = valid.

Usage:
    from validate_schema import validate_post, validate_report, validate_posts_container
    errors = validate_post(post_dict)
    if errors:
        for e in errors: print(e)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ValidationError:
    field: str
    message: str
    value: Any = None

    def __str__(self) -> str:
        return f"[{self.field}] {self.message} (got: {self.value!r})"


# ---------------------------------------------------------------------------
# Post validator
# ---------------------------------------------------------------------------

_POST_REQUIRED_FIELDS = {
    "post_id":       str,
    "group_id":      str,
    "author":        str,
    "content":       str,
    "reactions":     dict,
    "comments_count": int,
    "shares_count":  int,
    "post_url":      str,
    "timestamp":     str,
    "content_type":  str,
    "scraped_at":    str,
}

_VALID_CONTENT_TYPES = {"text", "image", "video", "link", "mixed", "unknown"}
_ISO_PREFIXES = ("20", "19")  # rough check


def _is_iso(s: str) -> bool:
    if not s:
        return True  # empty timestamp is allowed (not all posts have one)
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_post(post: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(post, dict):
        return [ValidationError("post", "Must be a dict", type(post).__name__)]

    # Required fields + type check
    for field, expected_type in _POST_REQUIRED_FIELDS.items():
        if field not in post:
            errors.append(ValidationError(field, "Missing required field"))
            continue
        val = post[field]
        if not isinstance(val, expected_type):
            errors.append(ValidationError(field, f"Expected {expected_type.__name__}", type(val).__name__))

    # post_id must be non-empty
    pid = post.get("post_id", "")
    if isinstance(pid, str) and not pid.strip():
        errors.append(ValidationError("post_id", "Must not be empty"))

    # post_url should not be a user profile link
    purl = post.get("post_url", "")
    if isinstance(purl, str) and "/user/" in purl and "/posts/" not in purl:
        errors.append(ValidationError("post_url", "Looks like a comment/user link, not a post", purl))

    # ISO datetime fields
    for tf in ("timestamp", "scraped_at"):
        v = post.get(tf, "")
        if isinstance(v, str) and not _is_iso(v):
            errors.append(ValidationError(tf, "Not a valid ISO datetime", v))

    # content_type
    ct = post.get("content_type", "")
    if isinstance(ct, str) and ct and ct not in _VALID_CONTENT_TYPES:
        errors.append(ValidationError("content_type", f"Unknown type; expected one of {_VALID_CONTENT_TYPES}", ct))

    # reactions dict
    reactions = post.get("reactions")
    if isinstance(reactions, dict):
        if "total" not in reactions:
            errors.append(ValidationError("reactions.total", "Missing 'total' key"))

    # media list
    media = post.get("media")
    if media is not None and not isinstance(media, list):
        errors.append(ValidationError("media", "Must be a list", type(media).__name__))

    return errors


# ---------------------------------------------------------------------------
# Posts container validator
# ---------------------------------------------------------------------------

def validate_posts_container(container: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(container, dict):
        return [ValidationError("container", "Must be a dict")]

    for field in ("schema_version", "group_id", "posts"):
        if field not in container:
            errors.append(ValidationError(field, "Missing required container field"))

    posts = container.get("posts")
    if not isinstance(posts, list):
        errors.append(ValidationError("posts", "Must be a list"))
        return errors

    count = container.get("post_count")
    if count is not None and count != len(posts):
        errors.append(ValidationError(
            "post_count", f"Mismatch: declared {count}, actual {len(posts)}"
        ))

    post_errors: list[ValidationError] = []
    for i, p in enumerate(posts):
        for e in validate_post(p):
            post_errors.append(ValidationError(f"posts[{i}].{e.field}", e.message, e.value))
    errors.extend(post_errors)
    return errors


# ---------------------------------------------------------------------------
# Report validator
# ---------------------------------------------------------------------------

_REPORT_REQUIRED_FIELDS = {
    "group_id":       str,
    "analyzed_at":    str,
    "total_posts":    int,
    "sentiment":      dict,
    "engagement":     dict,
}


def validate_report(report: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(report, dict):
        return [ValidationError("report", "Must be a dict")]

    for field, expected_type in _REPORT_REQUIRED_FIELDS.items():
        if field not in report:
            errors.append(ValidationError(field, "Missing required field"))
        elif not isinstance(report[field], expected_type):
            errors.append(ValidationError(field, f"Expected {expected_type.__name__}", type(report[field]).__name__))

    if not _is_iso(report.get("analyzed_at", "")):
        errors.append(ValidationError("analyzed_at", "Not a valid ISO datetime"))

    sentiment = report.get("sentiment", {})
    if isinstance(sentiment, dict):
        for key in ("positive", "neutral", "negative"):
            if key not in sentiment:
                errors.append(ValidationError(f"sentiment.{key}", "Missing"))

    return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_cli() -> None:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Validate posts/reports JSON against schema")
    parser.add_argument("file", help="Path to JSON file to validate")
    parser.add_argument("--type", choices=["post", "container", "report"], default="container",
                        help="Schema type to validate against (default: container)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    validators = {
        "post":      validate_post,
        "container": validate_posts_container,
        "report":    validate_report,
    }
    errors = validators[args.type](data)

    if not errors:
        print(f"OK: {path.name} is valid ({args.type})")
        sys.exit(0)
    else:
        print(f"INVALID ({len(errors)} error(s)) in {path.name}:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)


if __name__ == "__main__":
    _run_cli()
