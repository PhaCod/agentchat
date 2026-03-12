# Planning: Gộp skill trùng chức năng & Database riêng thống nhất

Mục tiêu: (1) Gộp luồng dữ liệu của các skill giống nhau để chạy nhất quán, đồng bộ; (2) Lưu trữ trong database riêng để truy xuất lại khi cần.

---

## 1. Hiện trạng — skill nào giống nhau, lưu ở đâu

| Skill | Chức năng chính | Nguồn dữ liệu | Lưu trữ hiện tại |
|-------|-----------------|---------------|-------------------|
| **facebook-group-analyzer** | Scrape + phân tích (sentiment, topics, engagement, pain, leads, competitor) | FB group feed | JSON: `data/posts/{group_id}/YYYY-MM.json` + manifest; Report: `data/reports/{id}_analysis.json`; SQLite: `data/index.db` (chỉ index, đồng bộ từ JSON) |
| **fb-group-crawl** | Scrape FB group → lưu DB → hỏi đáp tự nhiên (AI) | FB group feed | SQLite: `data/fb_posts.db` (FTS5, time index) — **cùng domain, khác file** |
| **facebook-scraper** | Discovery + scrape page/group FB | FB page/group | `data/output`, `data/queue`, thumbnails — hướng discovery, output có thể trùng concept “post” |
| **market-research** | Nghiên cứu thị trường (web + FB + TikTok) → báo cáo | Web, FB, TikTok | JSON + MD: `data/research/{timestamp}_{topic}.json`, `*_report.md` — không dùng chung DB với FB posts |
| **goodreads** | Sách, kệ, đánh giá | Goodreads RSS/API | Không lưu DB trong workspace; chỉ gọi API / session |

**Kết luận trùng lặp:**

- **facebook-group-analyzer** và **fb-group-crawl** cùng làm một việc: crawl bài đăng FB group → lưu lại → dùng sau. Khác nhau: analyzer lưu JSON + index (phục vụ report), crawl lưu SQLite (phục vụ NL query). **Hai luồng dữ liệu song song, không đồng bộ.**
- **facebook-scraper** có thể sinh ra dữ liệu “post” tương tự nhưng format/flow khác; nếu dùng chung nguồn FB group thì cũng nên đổ về cùng một nơi.
- **market-research** có thể lấy FB từ một nguồn thống nhất (DB chung) thay vì crawl riêng, và kết quả research nên lưu có cấu trúc để truy vấn lại.

---

## 2. Hướng thiết kế: một database riêng, luồng nhất quán

### 2.1. Database riêng (một nơi truy xuất)

- **Vị trí đề xuất:** `workspace/data/social.db` (SQLite) hoặc thư mục `workspace/data/` + file DB do config quyết định (ví dụ env `SOCIAL_DB_PATH`).
- **Lý do SQLite:** Đủ cho volume vài trăm nghìn bài, FTS5 full-text, không cần server, dễ backup (copy 1 file), đã dùng thành công trong fb-group-crawl và facebook-group-analyzer (index).

### 2.2. Schema thống nhất (gợi ý)

**Bảng 1: `posts` — bài đăng từ mọi nền tảng (FB group, page; sau này TikTok, X…)**

| Cột | Kiểu | Ghi chú |
|-----|------|--------|
| id | INTEGER PK | Auto |
| platform | TEXT | `facebook`, `tiktok`, `x`, … |
| source_type | TEXT | `group`, `page`, `profile` |
| source_id | TEXT | group_id, page_id, handle |
| post_id | TEXT | UNIQUE (platform + source_id + post_id) |
| author | TEXT | |
| author_id | TEXT | |
| content | TEXT | Nội dung chính |
| content_type | TEXT | text, image, video, link |
| post_url | TEXT | |
| posted_at | TEXT | ISO-8601 (nullable nếu chưa parse được) |
| scraped_at | TEXT | ISO-8601 |
| reactions_total | INTEGER | |
| reactions_like, love, haha, wow, sad, angry | INTEGER | (tùy platform) |
| comments_count | INTEGER | |
| shares_count | INTEGER | |
| views_count | INTEGER | (TikTok, …) |
| raw_meta | TEXT | JSON mở rộng (media, …) |
| scrape_run_id | TEXT | Liên kết run log (audit) |

- **Index:** `(platform, source_id, posted_at DESC)`, `(platform, source_id, scraped_at DESC)`.
- **FTS5:** Bảng ảo `posts_fts(content)` để full-text search (keyword, tiếng Việt).

**Bảng 2: `sources` — nguồn đã đăng ký (group/page/handle)**

| Cột | Kiểu | Ghi chú |
|-----|------|--------|
| platform | TEXT | |
| source_id | TEXT | PK (hoặc composite PK) |
| source_url | TEXT | |
| name | TEXT | Tên hiển thị |
| last_scraped_at | TEXT | |
| last_post_id | TEXT | Cursor incremental |
| total_posts | INTEGER | Cached count (optional) |

**Bảng 3: `scrape_runs` — audit trail mỗi lần crawl**

| Cột | Kiểu | Ghi chú |
|-----|------|--------|
| run_id | TEXT PK | UUID hoặc timestamp-based |
| platform | TEXT | |
| source_id | TEXT | |
| trigger | TEXT | manual, schedule, api |
| started_at, finished_at | TEXT | |
| status | TEXT | success, error, partial |
| posts_scraped | INTEGER | |
| posts_saved | INTEGER | |
| settings | TEXT | JSON (days_back, max_posts, …) |

**Bảng 4: `reports` — kết quả phân tích / báo cáo (có thể truy vấn lại)**

| Cột | Kiểu | Ghi chú |
|-----|------|--------|
| id | INTEGER PK | |
| report_type | TEXT | `group_analysis`, `market_research`, … |
| scope_id | TEXT | group_id hoặc topic slug |
| generated_at | TEXT | ISO-8601 |
| file_path | TEXT | Đường dẫn file JSON/MD (hoặc lưu blob) |
| summary | TEXT | Tóm tắt ngắn (optional) |
| meta | TEXT | JSON (model, version, filters) |

**Bảng 5 (optional): `research` — market research runs**

| Cột | Kiểu | Ghi chú |
|-----|------|--------|
| id | INTEGER PK | |
| topic | TEXT | |
| sources_used | TEXT | web, facebook, tiktok |
| created_at | TEXT | |
| result_path | TEXT | Path to JSON |
| report_path | TEXT | Path to MD |

---

## 3. Luồng dữ liệu thống nhất (đồng bộ, nhất quán)

### 3.1. Một pipeline crawl FB group

- **Chọn một scraper làm “nguồn chính”:** Hoặc **facebook-group-analyzer** (đã có partition, manifest, analyzer) hoặc **fb-group-crawl** (đã có SQLite + FTS). Đề xuất: **giữ facebook-group-analyzer làm scraper chính** (đã dùng production, có run log, partition), thêm bước **sync vào `social.db`** sau mỗi lần `save_posts`.
- **Luồng:**
  1. User/agent gọi: scrape group X (chỉ một lệnh, từ facebook-group-analyzer).
  2. Scraper crawl → lưu như hiện tại (JSON partition + manifest) **và** ghi vào `social.db` (bảng `posts`, `sources`, `scrape_runs`). Dedup theo `(platform, source_id, post_id)`.
  3. Analyzer đọc từ **social.db** (hoặc vẫn đọc từ JSON do backward compat) → sinh report → lưu file report + ghi bảng `reports`.
  4. **fb-group-crawl** chuyển thành “consumer”: không crawl nữa, chỉ **đọc từ social.db** để trả lời NL query (ask). Có thể deprecate scraper trong fb-group-crawl hoặc để làm fallback tạm.

### 3.2. facebook-scraper (discovery + scrape)

- Nếu output là “post” giống schema trên: khi scrape xong, **đẩy vào cùng `social.db`** (bảng `posts`, `sources`, `scrape_runs`) với `platform=facebook`, `source_type=page` hoặc `group`.
- Nếu chỉ discovery (list group/page): có thể chỉ lưu vào `sources` hoặc bảng phụ “discovery_queue”.

### 3.3. market-research

- **Input:** Có thể lấy FB từ **social.db** (query posts theo topic/keyword) thay vì gọi scraper riêng.
- **Output:** Giữ file JSON/MD như hiện tại; **đồng thời** ghi bảng `research` (hoặc `reports` với `report_type=market_research`) để truy vấn lại theo topic/ngày.

### 3.4. goodreads

- Không thay đổi; không cần đưa vào social DB (domain khác). Nếu sau này cần “một DB cho mọi thứ” có thể thêm bảng `books` / `reading_activity` riêng.

---

## 4. Đồng bộ và nhất quán

- **Một nơi ghi posts FB:** Chỉ một pipeline (facebook-group-analyzer + sync vào DB) ghi bảng `posts` cho FB group. fb-group-crawl chỉ đọc.
- **Run log tập trung:** Mỗi lần scrape ghi `scrape_runs` với run_id, status, counts → dễ audit, debug, replay.
- **Schema chuẩn:** Mọi consumer (analyzer, NL ask, market-research) đọc cùng bảng `posts` với cùng tên cột → không lệch định nghĩa.
- **FTS + index thời gian:** Truy xuất lại theo keyword (FTS) và theo khoảng thời gian (posted_at, scraped_at).

---

## 5. Truy xuất lại khi cần

- **Theo nguồn:** `SELECT * FROM posts WHERE platform='facebook' AND source_id=? ORDER BY posted_at DESC`.
- **Theo keyword:** Full-text search trên `posts_fts`.
- **Theo thời gian:** `posted_at BETWEEN ? AND ?` hoặc `scraped_at >= ?`.
- **Theo run:** `SELECT * FROM scrape_runs WHERE source_id=? ORDER BY started_at DESC` → biết lần crawl nào đã chạy, bao nhiêu bài.
- **Report đã sinh:** `SELECT * FROM reports WHERE report_type='group_analysis' AND scope_id=? ORDER BY generated_at DESC` → đọc lại file_path hoặc blob.

Có thể bọc trong một module `workspace/data/query.py` hoặc API nhỏ (CLI hoặc HTTP) để agent/user gọi: “lấy 20 bài gần nhất group X”, “tìm bài có từ Y”, “list report đã tạo cho group Z”.

---

## 6. Lộ trình thực hiện (gợi ý)

| Phase | Nội dung | Ưu tiên |
|-------|----------|--------|
| **1** | Tạo schema `social.db` (posts, sources, scrape_runs, reports) + migration script (tạo bảng, FTS). | Cao |
| **2** | Trong facebook-group-analyzer: sau `save_posts()` gọi sync vào `social.db` (insert/replace posts, update sources, ghi scrape_runs). Giữ nguyên JSON + index hiện tại (backward compat). | Cao |
| **3** | Chuyển fb-group-crawl “ask” sang đọc từ `social.db` thay vì `fb_posts.db`; tùy chọn deprecate scraper trong fb-group-crawl hoặc để nó ghi vào social.db nếu vẫn chạy. | Trung bình |
| **4** | (Tuỳ chọn) Analyzer đọc từ social.db thay vì JSON để tạo report; vẫn ghi report file + bảng `reports`. | Trung bình |
| **5** | market-research: thêm bước đọc FB từ social.db (optional); ghi kết quả vào bảng research/reports. | Thấp |
| **6** | facebook-scraper: nếu output là posts, thêm bước ghi vào social.db. | Thấp |

---

## 7. Tóm tắt

- **Skill giống nhau:** facebook-group-analyzer và fb-group-crawl cùng domain (FB group posts); gộp luồng bằng cách **một DB riêng** (`social.db`), **một pipeline crawl** ghi vào DB, các skill còn lại đọc/ghi bổ sung (reports, research).
- **Database riêng:** SQLite tại `workspace/data/social.db` (hoặc path config), với bảng posts (đa nền tảng), sources, scrape_runs, reports (và optional research).
- **Nhất quán đồng bộ:** Một nguồn ghi posts FB; mọi truy vấn và báo cáo dựa trên cùng schema và cùng DB → dữ liệu truy xuất lại được, audit được, không trùng lặp hai bộ storage.

Nếu bạn muốn, bước tiếp theo có thể là: (1) viết script tạo schema `social.db` và (2) patch nhỏ trong facebook-group-analyzer để sync vào DB ngay sau khi save_posts.
