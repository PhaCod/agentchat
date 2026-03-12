"""
query.py — Interactive CLI để khám phá và tương tác với dữ liệu đã scrape.

Dùng:
    python query.py                    # menu tương tác
    python query.py --group mygroup   # trực tiếp vào group
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import storage

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hdr(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def _post_line(p: dict, idx: int | None = None):
    prefix = f"[{idx}] " if idx is not None else ""
    ts   = p.get("timestamp", "")[:10]
    r    = p.get("reactions", {}).get("total", 0)
    c    = p.get("comments_count", 0)
    s    = p.get("shares_count", 0)
    auth = p.get("author", "?")[:22]
    text = p.get("content", "")[:70].replace("\n", " ")
    spam = " 🚩SPAM" if p.get("spam_score", 0) >= 0.7 else ""
    print(f"{prefix}{ts} | {auth:<22} | 👍{r:>5} 💬{c:>4} 🔁{s:>3}{spam}")
    if text:
        print(f"{'':>4}{text}")

def _input(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Menu actions
# ─────────────────────────────────────────────────────────────────────────────

def action_list_posts(posts: list[dict]):
    _hdr(f"TẤT CẢ BÀI ĐĂNG ({len(posts)} bài)")
    page_size = 10
    start = 0
    while True:
        chunk = posts[start:start + page_size]
        for i, p in enumerate(chunk, start + 1):
            _post_line(p, i)
        print(f"\nHiển thị {start+1}–{start+len(chunk)}/{len(posts)}")
        if start + page_size >= len(posts):
            break
        cmd = _input("\n[Enter] trang tiếp | [q] quay lại: ")
        if cmd.lower() == "q":
            break
        start += page_size


def action_search(posts: list[dict]):
    _hdr("TÌM KIẾM BÀI ĐĂNG")
    keyword = _input("Nhập từ khoá tìm kiếm: ").lower()
    if not keyword:
        return
    results = [p for p in posts if keyword in p.get("content", "").lower()
               or keyword in p.get("author", "").lower()]
    if not results:
        print(f"  Không tìm thấy bài nào chứa '{keyword}'")
        return
    print(f"\n  Tìm thấy {len(results)} bài:\n")
    for i, p in enumerate(results, 1):
        _post_line(p, i)


def action_top_posts(posts: list[dict]):
    _hdr("TOP 10 BÀI TƯƠNG TÁC CAO NHẤT")
    top = sorted(posts, key=lambda p: p.get("reactions", {}).get("total", 0), reverse=True)[:10]
    for i, p in enumerate(top, 1):
        _post_line(p, i)
        print()


def action_spam(posts: list[dict]):
    _hdr("BÀI ĐĂNG BỊ ĐÁNH DẤU SPAM")
    spam = [p for p in posts if p.get("spam_score", 0) >= 0.7]
    if not spam:
        print("  Không phát hiện bài spam (hoặc chưa chạy analyze).")
        print("  Chạy: python main.py analyze --group <group_id>")
        return
    print(f"  {len(spam)} bài spam:\n")
    for i, p in enumerate(spam, 1):
        _post_line(p, i)


def action_by_author(posts: list[dict]):
    _hdr("TÌM BÀI THEO TÁC GIẢ")
    name = _input("Nhập tên tác giả (hoặc một phần tên): ").lower()
    if not name:
        return
    results = [p for p in posts if name in p.get("author", "").lower()]
    if not results:
        print(f"  Không tìm thấy bài nào của '{name}'")
        return
    print(f"\n  {len(results)} bài của tác giả khớp '{name}':\n")
    for i, p in enumerate(results, 1):
        _post_line(p, i)


def action_by_date(posts: list[dict]):
    _hdr("LỌC BÀI THEO NGÀY")
    print("  Định dạng: YYYY-MM-DD  (ví dụ: 2026-02-15)")
    from_d = _input("Từ ngày (Enter để bỏ qua): ")
    to_d   = _input("Đến ngày (Enter để bỏ qua): ")

    results = []
    for p in posts:
        ts = p.get("timestamp", "")[:10]
        if not ts:
            continue
        if from_d and ts < from_d:
            continue
        if to_d and ts > to_d:
            continue
        results.append(p)

    if not results:
        print("  Không có bài nào trong khoảng ngày đó.")
        return
    print(f"\n  {len(results)} bài:\n")
    for i, p in enumerate(results, 1):
        _post_line(p, i)


def action_stats(posts: list[dict]):
    _hdr("THỐNG KÊ NHANH")
    total = len(posts)
    total_r = sum(p.get("reactions", {}).get("total", 0) for p in posts)
    total_c = sum(p.get("comments_count", 0) for p in posts)
    total_s = sum(p.get("shares_count", 0) for p in posts)

    ct: dict = {}
    for p in posts:
        t = p.get("content_type", "text")
        ct[t] = ct.get(t, 0) + 1

    authors: dict = {}
    for p in posts:
        a = p.get("author", "?")
        authors[a] = authors.get(a, 0) + 1
    top_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)[:5]

    dates = [p.get("timestamp", "")[:10] for p in posts if p.get("timestamp")]
    date_range = f"{min(dates)} → {max(dates)}" if dates else "N/A"

    print(f"  Tổng bài      : {total}")
    print(f"  Khoảng thời gian: {date_range}")
    print(f"  Tổng reactions: {total_r:,}  (avg: {total_r/total:.1f})")
    print(f"  Tổng comments : {total_c:,}  (avg: {total_c/total:.1f})")
    print(f"  Tổng shares   : {total_s:,}  (avg: {total_s/total:.1f})")
    print(f"\n  Loại nội dung:")
    for t, n in sorted(ct.items(), key=lambda x: x[1], reverse=True):
        print(f"    {t:<10} : {n} bài")
    print(f"\n  Top 5 tác giả đăng nhiều nhất:")
    for name, count in top_authors:
        print(f"    {name:<30} : {count} bài")


def action_report(group_id: str):
    _hdr("BÁO CÁO PHÂN TÍCH")
    report = storage.load_report(group_id)
    if not report:
        print(f"  Chưa có báo cáo cho '{group_id}'.")
        print(f"  Chạy: python main.py analyze --group {group_id}")
        return

    sen = report.get("sentiment", {})
    dp  = sen.get("distribution_pct", {})
    eng = report.get("engagement", {})
    topics = report.get("topics", [])
    kws    = report.get("top_keywords", [])
    trends = report.get("trends", {})

    print(f"  Đã phân tích lúc : {report.get('analyzed_at','')[:19]}")
    print(f"  Tổng bài         : {report.get('total_posts')}")
    dr = report.get("date_range", {})
    print(f"  Khoảng ngày      : {dr.get('from')} → {dr.get('to')}")

    print(f"\n  Sentiment:")
    print(f"    Tích cực : {sen.get('positive')} bài ({dp.get('positive')}%)")
    print(f"    Trung lập: {sen.get('neutral')} bài ({dp.get('neutral')}%)")
    print(f"    Tiêu cực : {sen.get('negative')} bài ({dp.get('negative')}%)")

    print(f"\n  Chủ đề:")
    for t in topics[:6]:
        print(f"    {t['topic']:<35} {t['post_count']:>4} bài ({t['pct']}%)")

    print(f"\n  Từ khoá nổi bật:")
    kw_line = ", ".join(f"{k['keyword']}({k['count']})" for k in kws[:10])
    print(f"    {kw_line}")

    print(f"\n  Engagement:")
    print(f"    Avg reactions : {eng.get('avg_reactions')}")
    print(f"    Avg comments  : {eng.get('avg_comments')}")
    print(f"    Giờ đăng tốt  : {eng.get('best_hours')}")

    spam_n = report.get("spam_posts_count", 0)
    print(f"\n  Spam phát hiện : {spam_n} bài")

    print(f"\n  Từ khoá đang tăng : {trends.get('rising_keywords', [])[:8]}")
    print(f"  Bài viral          : {trends.get('viral_posts', [])[:5]}")


def action_view_post(posts: list[dict]):
    _hdr("XEM CHI TIẾT BÀI ĐĂNG")
    idx_s = _input("Nhập số thứ tự bài (1 → tìm, hoặc nhập post_id): ")
    p = None
    if idx_s.isdigit():
        idx = int(idx_s) - 1
        if 0 <= idx < len(posts):
            p = posts[idx]
    else:
        matches = [x for x in posts if x.get("post_id") == idx_s]
        if matches:
            p = matches[0]

    if not p:
        print("  Không tìm thấy bài.")
        return

    print(f"\n  post_id   : {p.get('post_id')}")
    print(f"  Tác giả   : {p.get('author')} ({p.get('author_id')})")
    print(f"  Thời gian : {p.get('timestamp')}")
    print(f"  Loại      : {p.get('content_type')}")
    print(f"  URL       : {p.get('post_url')}")
    r = p.get("reactions", {})
    print(f"  Reactions : 👍{r.get('total')} (like:{r.get('like')} love:{r.get('love')})")
    print(f"  Comments  : {p.get('comments_count')}")
    print(f"  Shares    : {p.get('shares_count')}")
    if p.get("spam_score") is not None:
        print(f"  Spam score: {p.get('spam_score')}")
    print(f"\n  Nội dung:\n")
    content = p.get("content", "")
    for line in content.split("\n"):
        print(f"    {line}")


def action_leads(group_id: str):
    _hdr("LEAD GENERATION — Purchase Intent Posts")
    report = storage.load_report(group_id)
    if not report:
        print("  No analysis report found. Run: python main.py analyze --group " + group_id)
        return
    leads_data = report.get("leads", {})
    if not leads_data:
        print("  No lead data. Re-run analyze to generate.")
        return
    tb = leads_data.get("tier_breakdown", {})
    print(f"\n  Total leads  : {leads_data.get('total_leads', 0)}")
    print(f"  Hot          : {tb.get('Hot', 0)}")
    print(f"  Warm         : {tb.get('Warm', 0)}")
    print(f"  Cold         : {tb.get('Cold', 0)}")

    cats = leads_data.get("top_product_categories", [])
    if cats:
        print(f"\n  Top product categories:")
        for c in cats:
            print(f"    {c['category']:<20} {c['count']} posts")

    hot = leads_data.get("hot_leads", [])
    if hot:
        print(f"\n  Hot Leads (top {min(10, len(hot))}):")
        for i, l in enumerate(hot[:10], 1):
            print(f"  [{i}] [{l['tier']}] {l.get('author','?'):<25} score={l['lead_score']:.1f}")
            print(f"      {l.get('preview','')[:80]}")
            print(f"      reactions={l.get('reactions',0)} | {l.get('post_url','')}")


def action_pain_points(group_id: str):
    _hdr("PAIN POINTS — Member Frustrations & Unmet Needs")
    report = storage.load_report(group_id)
    if not report:
        print("  No analysis report found. Run: python main.py analyze --group " + group_id)
        return
    pain_data = report.get("pain_points", {})
    if not pain_data:
        print("  No pain point data. Re-run analyze to generate.")
        return

    print(f"\n  Total pain posts : {pain_data.get('total_pain_posts', 0)}")
    breakdown = pain_data.get("category_breakdown", {})
    if breakdown:
        print(f"\n  Category breakdown:")
        for cat, v in breakdown.items():
            print(f"    {cat:<20} {v.get('count',0):>4} posts ({v.get('pct',0)}%)")

    top = pain_data.get("top_pain_posts", [])
    if top:
        print(f"\n  Top Pain Posts (top {min(10, len(top))}):")
        for i, p in enumerate(top[:10], 1):
            cats = ", ".join(p.get("pain_categories", []))
            print(f"  [{i}] score={p['pain_score']:.2f} [{cats}] reactions={p.get('reactions',0)}")
            print(f"      {p.get('preview','')[:90]}")
            print(f"      {p.get('post_url','')}")


def action_competitors(group_id: str):
    _hdr("COMPETITOR MONITORING — Share of Voice")
    report = storage.load_report(group_id)
    if not report:
        print("  No analysis report found. Run: python main.py analyze --group " + group_id)
        return
    comp_data = report.get("competitors", {})
    if not comp_data or "_note" in comp_data:
        note = comp_data.get("_note", "No competitors configured.")
        print(f"  {note}")
        print("  Add competitors to config/config.json under key 'competitors'.")
        return

    print(f"\n  Total brand mentions: {comp_data.get('total_brand_mentions', 0)}")
    sov = comp_data.get("share_of_voice", [])
    if sov:
        print(f"\n  Share of Voice:")
        for b in sov:
            print(f"    {b['brand']:<25} {b['sov_pct']:>6.1f}%  ({b['mentions']} mentions)")

    details = comp_data.get("brand_details", {})
    for brand, d in details.items():
        if d.get("mentions", 0) == 0:
            continue
        print(f"\n  {brand}:")
        s = d.get("sentiment", {})
        print(f"    Sentiment: +{s.get('positive',0)} ={s.get('neutral',0)} -{s.get('negative',0)} "
              f"(neg {s.get('negative_pct',0)}%)")
        for tp in d.get("top_posts", [])[:3]:
            print(f"    [{tp.get('sentiment','?')}] reactions={tp.get('reactions',0)} "
                  f"{tp.get('preview','')[:60]}")


def action_nl_query(group_id: str):
    _hdr("NL QUERY — Natural Language Preset Queries")
    from scheduler import NL_PRESETS, run_nl_query
    print("\n  Available presets:")
    for i, (name, preset) in enumerate(NL_PRESETS.items(), 1):
        print(f"  {i}. {name:<20} — {preset['description']}")
    query = _input("\n  Enter query name (or number): ").strip()
    if query.isdigit():
        keys = list(NL_PRESETS.keys())
        idx = int(query) - 1
        if 0 <= idx < len(keys):
            query = keys[idx]
    result = run_nl_query(group_id, query)
    if "error" in result:
        print(f"  {result['error']}")
        if "available_queries" in result:
            print(f"  Available: {result['available_queries']}")
        return
    print(f"\n  Query: {result.get('query')}")
    data = result.get("results", {})
    if isinstance(data, list):
        for i, item in enumerate(data[:10], 1):
            if isinstance(item, dict):
                preview = item.get("content_preview") or item.get("preview", "")
                reactions = item.get("reactions", 0)
                print(f"  [{i}] reactions={reactions} | {str(preview)[:80]}")
            else:
                print(f"  [{i}] {item}")
    elif isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")
    else:
        print(f"  {data}")


def action_export(posts: list[dict], group_id: str):
    _hdr("EXPORT DỮ LIỆU")
    print("  1. Export CSV")
    print("  2. Export JSON (tất cả posts)")
    print("  3. Export JSON (chỉ bài có reaction cao)")
    choice = _input("\nChọn (1/2/3): ", "1")
    if choice == "1":
        path = storage.export_csv(group_id, posts)
        print(f"\n  ✅ Đã export CSV: {path}")
    elif choice == "2":
        from datetime import datetime, timezone
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = Path(__file__).parent / "data" / "exports" / f"{group_id}_{ts}_all.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  ✅ Đã export JSON: {out_path}")
    elif choice == "3":
        threshold = _input("  Số reactions tối thiểu (mặc định 100): ", "100")
        filtered = [p for p in posts if p.get("reactions", {}).get("total", 0) >= int(threshold)]
        from datetime import datetime, timezone
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = Path(__file__).parent / "data" / "exports" / f"{group_id}_{ts}_top.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  ✅ Đã export {len(filtered)} bài → {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def select_group() -> str | None:
    groups = storage.list_groups()
    if not groups:
        print("\n  ❌ Chưa có dữ liệu nào. Chạy scrape trước:")
        print('     python main.py scrape --group "https://facebook.com/groups/..." --days 7')
        return None
    if len(groups) == 1:
        return groups[0]
    _hdr("CHỌN GROUP")
    for i, g in enumerate(groups, 1):
        st = storage.group_stats(g)
        print(f"  {i}. {g:<40} ({st['post_count']} bài, {st['date_range']['from']} → {st['date_range']['to']})")
    choice = _input(f"\nChọn group (1–{len(groups)}): ", "1")
    try:
        return groups[int(choice) - 1]
    except (ValueError, IndexError):
        return groups[0]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", help="group_id để vào thẳng không cần chọn")
    args = parser.parse_args()

    print("\n🦞 Facebook Group Post Analyzer — Interactive Query")

    group_id = args.group or select_group()
    if not group_id:
        sys.exit(1)

    posts = storage.load_posts(group_id)
    if not posts:
        print(f"\n  ❌ Không có bài nào cho group '{group_id}'.")
        sys.exit(1)

    print(f"\n  ✅ Đã tải {len(posts)} bài từ group: {group_id}")

    MENU = {
        "1": ("View all posts",          lambda: action_list_posts(posts)),
        "2": ("Search by keyword",       lambda: action_search(posts)),
        "3": ("Top engaged posts",       lambda: action_top_posts(posts)),
        "4": ("Filter by author",        lambda: action_by_author(posts)),
        "5": ("Filter by date",          lambda: action_by_date(posts)),
        "6": ("Spam/ads",                lambda: action_spam(posts)),
        "7": ("Quick stats",             lambda: action_stats(posts)),
        "8": ("Full analysis report",    lambda: action_report(group_id)),
        "9": ("View post details",       lambda: action_view_post(posts)),
        "l": ("Lead generation",         lambda: action_leads(group_id)),
        "p": ("Pain points",             lambda: action_pain_points(group_id)),
        "c": ("Competitor monitoring",   lambda: action_competitors(group_id)),
        "n": ("NL query presets",        lambda: action_nl_query(group_id)),
        "e": ("Export data",             lambda: action_export(posts, group_id)),
        "g": ("Change group",            None),
        "q": ("Exit",                    None),
    }

    while True:
        _hdr(f"MENU — {group_id} ({len(posts)} bài)")
        for key, (label, _) in MENU.items():
            print(f"  {key}. {label}")

        choice = _input("\nChọn: ").lower()

        if choice == "q":
            print("\n  Tạm biệt!\n")
            break
        elif choice == "g":
            group_id = select_group() or group_id
            posts = storage.load_posts(group_id)
            print(f"\n  ✅ Đã tải {len(posts)} bài từ group: {group_id}")
        elif choice in MENU and MENU[choice][1]:
            try:
                MENU[choice][1]()
            except KeyboardInterrupt:
                print("\n  (đã huỷ)")
        else:
            print("  Lựa chọn không hợp lệ.")

        _input("\n[Enter] để tiếp tục...")


if __name__ == "__main__":
    main()
