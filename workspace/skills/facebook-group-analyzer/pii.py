"""
pii.py — PII (Personally Identifiable Information) detection and anonymization.

Capabilities:
  - Detect PII fields (author name, author_id, phone, email in content)
  - Anonymize a post: replace author with stable pseudonym, mask sensitive content
  - Erase all posts by a specific author_id (right-to-erasure / GDPR-style)
  - Audit: report which posts contain PII

Pseudonymization strategy:
  - Author names are replaced with a stable SHA-256 derived token: "user_<8hex>"
  - Same real name always maps to same pseudonym (deterministic, reversible with key)
  - author_id is hashed with the same approach

Usage:
    from pii import anonymize_post, erase_author, detect_pii

    anon = anonymize_post(post)
    erased = erase_author(posts, author_id="100077369349924")
    report = detect_pii(posts)
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# ---------------------------------------------------------------------------
# PII patterns in free text
# ---------------------------------------------------------------------------

_PHONE_RE  = re.compile(r"(?<!\d)(\+?84|0)[0-9]{8,10}(?!\d)")
_EMAIL_RE  = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_CCCD_RE   = re.compile(r"(?<!\d)\d{9}(?!\d)|(?<!\d)\d{12}(?!\d)")  # CCCD 9 or 12 digits


def _hash_token(value: str, salt: str = "fbga-pii") -> str:
    """Stable pseudonymization: SHA-256 of (salt + value), take first 8 hex chars."""
    h = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return h[:8]


def pseudonymize_author(author: str) -> str:
    """Replace real name with a stable pseudonym."""
    if not author or author in ("Unknown", ""):
        return author
    return f"user_{_hash_token(author)}"


def pseudonymize_author_id(author_id: str) -> str:
    if not author_id:
        return author_id
    return f"uid_{_hash_token(author_id)}"


def detect_pii_in_text(text: str) -> list[dict[str, str]]:
    """Return list of detected PII items in text content."""
    found: list[dict[str, str]] = []
    for m in _PHONE_RE.finditer(text):
        found.append({"type": "phone", "value": m.group(), "span": f"{m.start()}-{m.end()}"})
    for m in _EMAIL_RE.finditer(text):
        found.append({"type": "email", "value": m.group(), "span": f"{m.start()}-{m.end()}"})
    for m in _CCCD_RE.finditer(text):
        found.append({"type": "id_number", "value": m.group(), "span": f"{m.start()}-{m.end()}"})
    return found


def mask_pii_in_text(text: str) -> str:
    """Mask phone numbers, emails, and ID numbers in text with [REDACTED]."""
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _CCCD_RE.sub("[ID]", text)
    return text


# ---------------------------------------------------------------------------
# Post-level anonymization
# ---------------------------------------------------------------------------

def anonymize_post(
    post: dict,
    mask_content: bool = False,
    pseudonymize: bool = True,
) -> dict:
    """Return a copy of post with PII fields anonymized.

    Args:
        post: original post dict
        mask_content: if True, replace phone/email/ID in content text
        pseudonymize: if True, replace author name + author_id with stable pseudonyms
    """
    p = dict(post)
    if pseudonymize:
        p["author"]    = pseudonymize_author(p.get("author", ""))
        p["author_id"] = pseudonymize_author_id(p.get("author_id", ""))
    if mask_content:
        p["content"] = mask_pii_in_text(p.get("content", ""))
    return p


def anonymize_posts(
    posts: list[dict],
    mask_content: bool = False,
    pseudonymize: bool = True,
) -> list[dict]:
    return [anonymize_post(p, mask_content=mask_content, pseudonymize=pseudonymize) for p in posts]


# ---------------------------------------------------------------------------
# Right-to-erasure
# ---------------------------------------------------------------------------

def erase_author(posts: list[dict], author_id: str) -> list[dict]:
    """Remove all posts by a given author_id (GDPR right-to-erasure).
    Returns a new list with matching posts removed.
    """
    before = len(posts)
    filtered = [p for p in posts if p.get("author_id") != author_id]
    removed = before - len(filtered)
    return filtered, removed


# ---------------------------------------------------------------------------
# PII audit report
# ---------------------------------------------------------------------------

def detect_pii(posts: list[dict]) -> dict[str, Any]:
    """Scan all posts for PII in content. Returns an audit report."""
    posts_with_pii: list[dict] = []
    total_phone = 0
    total_email = 0
    total_id    = 0

    for p in posts:
        content = p.get("content", "")
        found = detect_pii_in_text(content)
        if found:
            posts_with_pii.append({
                "post_id":  p.get("post_id"),
                "author":   p.get("author"),
                "pii_items": found,
            })
            for item in found:
                if item["type"] == "phone":
                    total_phone += 1
                elif item["type"] == "email":
                    total_email += 1
                elif item["type"] == "id_number":
                    total_id += 1

    return {
        "total_posts_scanned":  len(posts),
        "posts_with_pii":       len(posts_with_pii),
        "pii_breakdown": {
            "phone_numbers": total_phone,
            "email_addresses": total_email,
            "id_numbers":   total_id,
        },
        "affected_posts": posts_with_pii,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_cli() -> None:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="PII tools for Facebook group post data")
    sub = parser.add_subparsers(dest="cmd")

    # audit
    p_audit = sub.add_parser("audit", help="Detect PII in posts file")
    p_audit.add_argument("file", help="Path to posts JSON file")

    # anonymize
    p_anon = sub.add_parser("anonymize", help="Anonymize posts file")
    p_anon.add_argument("file", help="Path to posts JSON file")
    p_anon.add_argument("--mask-content", action="store_true",
                        help="Also mask phone/email in content text")
    p_anon.add_argument("--output", help="Output file (default: overwrite)")

    # erase
    p_erase = sub.add_parser("erase", help="Erase posts by author_id")
    p_erase.add_argument("file", help="Path to posts JSON file")
    p_erase.add_argument("--author-id", required=True, help="author_id to erase")
    p_erase.add_argument("--output", help="Output file (default: overwrite)")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    skill_root = Path(__file__).parent
    sys.path.insert(0, str(skill_root))
    from schemas import unwrap_posts, posts_container

    path = Path(args.file)
    raw = json.loads(path.read_text(encoding="utf-8"))
    posts = unwrap_posts(raw)
    group_id = raw.get("group_id", path.stem) if isinstance(raw, dict) else path.stem

    if args.cmd == "audit":
        report = detect_pii(posts)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    elif args.cmd == "anonymize":
        anon = anonymize_posts(posts, mask_content=args.mask_content)
        container = posts_container(group_id, anon)
        out_path = Path(args.output) if args.output else path
        out_path.write_text(json.dumps(container, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Anonymized {len(anon)} posts -> {out_path}")

    elif args.cmd == "erase":
        remaining, removed = erase_author(posts, args.author_id)
        container = posts_container(group_id, remaining)
        out_path = Path(args.output) if args.output else path
        out_path.write_text(json.dumps(container, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Erased {removed} posts by author_id={args.author_id}. {len(remaining)} remain -> {out_path}")


if __name__ == "__main__":
    _run_cli()
