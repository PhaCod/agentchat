"""
test_offline.py — Kiểm tra toàn bộ pipeline phân tích mà không cần kết nối Facebook.
Tạo sample posts giả → chạy qua analyzer + storage → in kết quả.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyzer import GroupAnalyzer
from storage import save_posts, save_report, export_csv, group_stats

# ---------------------------------------------------------------------------
# 1. Tạo dữ liệu giả
# ---------------------------------------------------------------------------
_RAW = [
    ("Review sản phẩm rất tốt, chất lượng ổn, recommend cho mọi người", 320, 45, 12, "text"),
    ("Giá bao nhiêu vậy mọi người? inbox mình nhé", 15, 8, 1, "text"),
    ("FLASH SALE 50% hôm nay thôi! Link bio để mua. Zalo 0901234567", 5, 2, 0, "text"),
    ("Ai có kinh nghiệm dùng sản phẩm này chưa? Tư vấn mình với", 22, 18, 0, "text"),
    ("Clip hài hước quá, haha xem cả ngày không chán", 450, 67, 89, "video"),
    ("Chia sẻ tin tức mới nhất về sự kiện cuối tuần này tại HCM", 88, 15, 22, "image"),
    ("Mua bán order hàng Nhật, ship nhanh, giá rẻ. DM để nhận báo giá", 7, 3, 0, "text"),
    ("Tìm bạn cùng group, kết nối cộng đồng yêu thích chủ đề này", 45, 12, 5, "text"),
    ("Đánh giá shop: dịch vụ tệ, giao hàng chậm, thất vọng lắm", 210, 55, 8, "text"),
    ("Cảm ơn mọi người đã ủng hộ, chất lượng tuyệt vời, hài lòng 100%", 678, 120, 34, "image"),
    ("Giảm giá 30% khuyến mãi tháng này, mã giảm SAVE30", 12, 4, 1, "text"),
    ("Hỏi: shop nào uy tín trong group này? Cần mua gấp", 33, 28, 2, "text"),
    ("Review chi tiết sau 1 tháng dùng: ngon, đáng tiền, sẽ mua lại", 289, 41, 15, "text"),
    ("Ai biết cách fix lỗi này không? Help mình với", 19, 22, 1, "text"),
    ("Video hướng dẫn sử dụng, xem và follow fanpage để cập nhật", 156, 30, 18, "video"),
] * 4  # 60 posts

SAMPLE_POSTS = [
    {
        "post_id": f"post_{i:04d}",
        "group_id": "test_group",
        "author": f"User {i % 10}",
        "author_id": f"uid_{i % 10}",
        "content": content,
        "media": [],
        "reactions": {"total": reactions, "like": reactions, "love": 0, "haha": 0, "wow": 0, "sad": 0, "angry": 0},
        "comments_count": comments,
        "shares_count": shares,
        "post_url": f"https://facebook.com/groups/test_group/posts/post_{i:04d}",
        "timestamp": f"2026-02-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00+00:00",
        "content_type": ctype,
        "scraped_at": "2026-03-03T08:00:00+00:00",
    }
    for i, (content, reactions, comments, shares, ctype) in enumerate(_RAW)
]

print(f"[test] Generated {len(SAMPLE_POSTS)} sample posts")

# ---------------------------------------------------------------------------
# 2. Lưu vào storage
# ---------------------------------------------------------------------------
path = save_posts("test_group", SAMPLE_POSTS)
stats = group_stats("test_group")
print(f"[test] Storage stats: {stats}\n")

# ---------------------------------------------------------------------------
# 3. Phân tích
# ---------------------------------------------------------------------------
analyzer = GroupAnalyzer()
report = analyzer.analyze(SAMPLE_POSTS, "test_group")
save_report("test_group", report)

# ---------------------------------------------------------------------------
# 4. In kết quả
# ---------------------------------------------------------------------------
print("=" * 60)
print("SENTIMENT:")
print(json.dumps(report["sentiment"], ensure_ascii=False, indent=2))

print("\nTOP KEYWORDS (top 5):")
for kw in report["top_keywords"][:5]:
    print(f"  - {kw['keyword']}: {kw['count']}")

print("\nTOPICS:")
for t in report["topics"]:
    print(f"  - {t['topic']}: {t['post_count']} posts ({t['pct']}%)")

print(f"\nSPAM DETECTED: {report['spam_posts_count']} posts")

eng = report["engagement"]
print(f"\nENGAGEMENT:")
print(f"  Avg reactions : {eng['avg_reactions']}")
print(f"  Avg comments  : {eng['avg_comments']}")
print(f"  Best hours    : {eng['best_hours']}")
print(f"  Top post      : {eng['top_posts'][0]['content_preview'][:80]}")

print(f"\nTRENDS:")
print(f"  Rising   : {report['trends']['rising_keywords'][:5]}")
print(f"  Viral    : {report['trends']['viral_posts']}")

# ---------------------------------------------------------------------------
# 5. Export CSV
# ---------------------------------------------------------------------------
csv_path = export_csv("test_group", SAMPLE_POSTS)
print(f"\n[test] CSV exported: {csv_path}")
print("\n✅ All tests passed!")
