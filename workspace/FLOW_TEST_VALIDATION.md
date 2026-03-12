# Test luồng & validate dữ liệu

**Ngày chạy:** 2026-03-10

---

## 1. Luồng đã test

### 1.1. Facebook Group Analyzer (report)

- **Lệnh (như agent gọi):**
  ```powershell
  cd C:\Users\dangt\.openclaw\workspace\skills\facebook-group-analyzer
  python main.py report --group 1125804114216204 --type summary --output json
  ```
- **Kết quả:** Exit code 0, JSON trả về đầy đủ.
- **Full report:** `python main.py report --group 1125804114216204 --type full --output json` → OK.

### 1.2. Goodreads (search – read only)

- **Lệnh (như agent gọi):**
  ```powershell
  cd C:\Users\dangt\.openclaw\workspace\skills\goodreads\scripts
  python goodreads-rss.py search "atomic habits" --limit 3
  ```
- **Kết quả:** Exit code 0, JSON có `query`, `count`, `books[]` với `book_id`, `title`, `author`, `book_url`.

---

## 2. Validate dữ liệu

### 2.1. FB report (group 1125804114216204)

- **Script:** `workspace\skills\facebook-group-analyzer\validate_report.py`
- **Chạy:** `python validate_report.py 1125804114216204`
- **Kết quả:** `"ok": true`, "Report validation passed".

**Kiểm tra:**
- `total_posts` = `posts_with_content` + `posts_excluded_from_text_analysis` (500 = 198 + 302).
- Sentiment: `positive + neutral + negative` = `posts_with_content` (41 + 154 + 3 = 198).
- `distribution_pct` cộng lại ≈ 100% (20.7 + 77.8 + 1.5).
- Các trường engagement (avg_reactions, avg_comments) không âm.

### 2.2. Goodreads search

- **Schema:** Mỗi phần tử trong `books` có `book_id`, `title`, `author`, `book_url`.
- **Số lượng:** `count` = độ dài mảng `books` (3 = 3).
- **Nội dung:** Query "atomic habits" trả về sách liên quan (vd. James Clear, Atomic Habits).

---

## 3. Kết luận

| Thành phần            | Luồng chạy | Validate dữ liệu |
|-----------------------|------------|-------------------|
| FB report (summary)   | OK         | OK (script pass)  |
| FB report (full)      | OK         | Cùng report, đã validate |
| Goodreads search     | OK         | Schema & nội dung hợp lý |

Luồng skill (chạy từ đúng thư mục, output JSON) **chạy bình thường**. Dữ liệu report FB **nhất quán** (số lượng, sentiment, phần trăm). Goodreads search trả về đúng format và nội dung.

**Ghi chú:** Manifest hiện tại ghi `post_count: 510` cho group 1125804114216204 (sau lần scrape +10 bài). File report đang dùng là lần analyze khi còn 500 bài; muốn số liệu mới nhất thì chạy `python main.py analyze --group 1125804114216204` rồi chạy lại report/validate.
