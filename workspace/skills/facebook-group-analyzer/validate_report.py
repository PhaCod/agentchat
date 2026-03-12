"""
Validate FB group report consistency:
- total_posts == posts_with_content + posts_excluded_from_text_analysis
- sentiment counts sum to posts_with_content; distribution_pct sums to 100
- engagement averages are non-negative
"""
import json
import sys
from pathlib import Path

def validate_report(report: dict) -> list[str]:
    errs = []
    total = report.get("total_posts")
    with_content = report.get("posts_with_content")
    excluded = report.get("posts_excluded_from_text_analysis")
    if total is not None and with_content is not None and excluded is not None:
        if with_content + excluded != total:
            errs.append(f"posts_with_content ({with_content}) + excluded ({excluded}) != total_posts ({total})")
    sen = report.get("sentiment", {})
    pos = sen.get("positive", 0)
    neu = sen.get("neutral", 0)
    neg = sen.get("negative", 0)
    if with_content is not None and (pos + neu + neg) != with_content:
        errs.append(f"sentiment counts ({pos}+{neu}+{neg}) != posts_with_content ({with_content})")
    pct = sen.get("distribution_pct", {})
    pct_sum = sum(pct.values())
    if pct and abs(pct_sum - 100) > 0.5:
        errs.append(f"distribution_pct sum = {pct_sum}, expected ~100")
    eng = report.get("engagement", {})
    for k in ("avg_reactions", "avg_comments", "avg_shares"):
        v = eng.get(k)
        if v is not None and v < 0:
            errs.append(f"engagement.{k} is negative: {v}")
    return errs

def main():
    group_id = sys.argv[1] if len(sys.argv) > 1 else "1125804114216204"
    root = Path(__file__).parent
    path = root / "data" / "reports" / f"{group_id}_analysis.json"
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"Report not found: {path}"}, indent=2))
        sys.exit(1)
    report = json.loads(path.read_text(encoding="utf-8"))
    errs = validate_report(report)
    if errs:
        print(json.dumps({"ok": False, "errors": errs, "report_keys": list(report.keys())}, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True, "message": "Report validation passed", "total_posts": report.get("total_posts")}, indent=2))

if __name__ == "__main__":
    main()
