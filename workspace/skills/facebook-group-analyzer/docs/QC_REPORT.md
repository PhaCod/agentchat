# QC Report — Facebook Group Analyzer

## 0. Các lỗi đã xử lý (Fixes applied)

| Vấn đề | Cách xử lý |
|--------|------------|
| **Post ID** nhiều `unknown_*` | Parser: duyệt mọi `a[href]`, tìm `story_fbid=`, `/posts/(\d+)`, `fbid=`; thử `data-id`, `data-story-id` trên element. |
| **Author** "Unknown" | Parser: thêm nhiều selector (h2/h3/h4 a, strong a, a[role='link'], div[role='article'] a…), bỏ qua link có text "Like", "Comment", "See more". |
| **Timestamp** rỗng | Parser: giữ `abbr[data-utime]`; thêm parse thời gian tương đối: "2h", "1 giờ", "Hôm qua", "Yesterday", "2 ngày", "1 tuần" (VN + EN). |
| **Bài rác** (no content + no timestamp) | Scraper: `scraper.skip_low_quality: true` — không lưu bài vừa không content vừa không timestamp hoặc `post_id` dạng `unknown_*`. |
| **Sentiment/Keywords** chạy trên bài không content | Analyzer: chỉ chạy sentiment, top_keywords, topics trên `posts_with_content`; report thêm `posts_with_content`, `posts_excluded_from_text_analysis`. |
| **date_range** rỗng không rõ lý do | Analyzer: khi rỗng nhưng có bài → thêm `date_range._note`. |
| **Lưu bài thiếu post_id/group_id** | Storage: `_valid_post()`; trước khi save chỉ giữ bài có post_id + group_id, log số bài bị drop. |

---

## 1. Kết quả validate dữ liệu (mẫu: group 1125804114216204)

| Chỉ số | Giá trị | Ghi chú |
|--------|--------|--------|
| Tổng bài | 500 | |
| Bài hợp lệ (không lỗi QC) | 0 | Toàn bộ có ít nhất 1 lỗi chất lượng |
| Empty timestamp | 303 | Không parse được thời gian đăng |
| Author unknown/empty | 500 | Không lấy được tên tác giả |
| Empty content | 302 | Nội dung trống (có thể bài chỉ có ảnh/video) |
| Fallback post_id (unknown_*) | 302 | Không lấy được post_id thật → dùng ID tạm |

**Report**: `date_range` rỗng vì đa số bài không có `timestamp` hợp lệ → phân tích xu hướng theo thời gian không tin cậy.

---

## 2. Điểm chưa ổn (QC)

### 2.1 Scraper / Parser (post_scraper.py)

- **Author**: Nhiều bài trả về "Unknown" — selector `h2 a, h3 a, ...` có thể không khớp layout mới của Facebook; cần fallback selector hoặc đa dạng hoá selector theo DOM.
- **Timestamp**: Nhiều bài `timestamp` rỗng — selector `abbr[data-utime]` hoặc `data-store` có thể thiếu/đổi; cần thêm cách lấy thời gian (ví dụ từ aria-label, text "x giờ trước").
- **Post ID**: 302 bài có `post_id` dạng `unknown_*` — link bài không match regex `story_fbid=` hoặc `/posts/\d+`; cần mở rộng pattern hoặc lấy từ attribute khác.
- **Empty content**: Bài chỉ có ảnh/video không có text → `content` rỗng; hợp lệ nhưng làm sentiment/keywords kém ý nghĩa. Có thể đánh dấu `content_type` và bỏ qua phân tích text cho bài không có content.

### 2.2 Lưu trữ / Pipeline

- **Không lọc trước khi lưu**: Scraper vẫn lưu bài không có `timestamp`, `content`, `post_id` thật → làm bẩn data và làm report (date_range, trends) sai lệch.
- **Không validate khi save**: `storage.save_posts()` không kiểm tra required fields hoặc chất lượng tối thiểu.

### 2.3 Phân tích (analyzer.py)

- **date_range**: Tính từ danh sách bài có `timestamp`; nếu đa số timestamp rỗng thì `date_range` rỗng.
- **Sentiment/Keywords**: Chạy trên cả bài content rỗng → nhiễu, từ khoá/stopword không đại diện.
- **Trends**: TrendDetector sort theo timestamp; timestamp rỗng bị bỏ qua → mẫu ít, kết quả không ổn.

### 2.4 Schema / Data structure

- **File posts**: Một số file vẫn format cũ (mảng ở root); lần save tiếp theo sẽ chuyển sang container — ổn.
- **Report**: Thiếu `schema_version` trong file đã tạo trước khi bổ sung schema — lần save report tiếp theo sẽ có.

---

## 3. Khuyến nghị xử lý

| Ưu tiên | Hành động |
|--------|-----------|
| P1 | **Scraper**: Bỏ qua (không thêm vào dict) bài vừa không có `content` vừa không có `timestamp` hợp lệ; hoặc đánh dấu `quality: "low"` và tùy chọn lọc khi analyze. |
| P1 | **Parser**: Cải thiện selector/fallback cho author, timestamp, post_id (thêm selector, regex, data attribute). |
| P2 | **Analyze**: Chỉ phân tích subset bài có `timestamp` và (optional) `content` không rỗng; báo trong report số bài bị loại. |
| P2 | **Storage**: Option validate khi save (ví dụ bỏ qua bài thiếu post_id thật); hoặc chạy `scripts/validate_data.py` định kỳ. |
| P3 | **Report**: Khi `date_range` rỗng nhưng có bài, ghi cảnh báo trong report (ví dụ `date_range_note: "most posts have empty timestamp"`). |

---

## 4. Chạy validate định kỳ

```bash
# Tất cả groups
python scripts/validate_data.py --output text

# Một group, output JSON
python scripts/validate_data.py --group 1125804114216204 --output json
```

---

## 5. Credentials (đã cấu hình)

- Facebook: đã thêm vào `.env` (FB_EMAIL, FB_PASSWORD). File `.env` nằm trong `.gitignore` — không commit.
