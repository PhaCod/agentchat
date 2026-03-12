# Facebook Group Analyzer

Công cụ thu thập, lưu trữ và phân tích bài đăng từ Facebook group — không cần Facebook API, không cần API key.

---

## Hệ thống hoạt động như thế nào?

```
Facebook Group
      │
      ▼
┌─────────────────┐
│  post_scraper   │  Trình duyệt headless (Playwright) cuộn trang,
│                 │  thu thập bài đăng, reaction, comment
└────────┬────────┘
         │ posts[]
         ▼
┌─────────────────┐
│    storage      │  Lưu JSON theo tháng (data/posts/{group}/)
│                 │  Index SQLite để query nhanh
└────────┬────────┘
         │ posts[]
         ▼
┌─────────────────────────────────────────────────────┐
│                    analyzer                         │
│                                                     │
│  ┌───────────┐  ┌───────────┐  ┌────────────────┐  │
│  │ Sentiment │  │  Topics   │  │   Keywords     │  │
│  │ rule-based│  │ clustering│  │   + Trends     │  │
│  └───────────┘  └───────────┘  └────────────────┘  │
│                                                     │
│  ┌───────────┐  ┌───────────┐  ┌────────────────┐  │
│  │   Pain    │  │   Lead    │  │  Competitor    │  │
│  │ Extractor │  │ Detector  │  │   Tracker      │  │
│  └───────────┘  └───────────┘  └────────────────┘  │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │          Gemini AI (optional)               │   │
│  │   Tóm tắt + insight bằng ngôn ngữ tự nhiên │   │
│  └─────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────┘
                           │ report JSON
                           ▼
              data/reports/{group}_analysis.json
```

Mỗi lần `analyze` chạy qua toàn bộ pipeline và ghi kết quả vào một file JSON duy nhất. Các lần chạy sau dùng Gemini cache (hash) để không tốn quota nếu dữ liệu không đổi.

---

## 5 Mục tiêu nghiệp vụ

### 1. Market Insights — Phân tích nỗi đau thị trường

Phát hiện bài đăng chứa dấu hiệu bức xúc, nhu cầu chưa được đáp ứng, so sánh giá, nhạy cảm chi phí.

**4 category được detect:**
| Category | Ví dụ signal |
|----------|-------------|
| `frustration` | "bực quá", "tệ thật", "lừa đảo", "chán" |
| `need_help` | "ai biết không", "làm sao để", "hướng dẫn mình" |
| `comparison` | "so sánh", "nên mua cái nào", "cái nào tốt hơn" |
| `price_sensitivity` | "đắt quá", "giá cao", "tìm chỗ rẻ hơn" |

**Output:**
```json
{
  "total_pain_posts": 10,
  "category_breakdown": {
    "frustration": {"count": 35, "pct": 17.7}
  },
  "top_pain_posts": [...]
}
```

---

### 2. Lead Generation — Tìm khách hàng tiềm năng

Chấm điểm bài đăng theo ý định mua hàng, phân 3 tier:

| Tier | Ý nghĩa | Signal điển hình |
|------|---------|-----------------|
| **Hot** | Sẵn sàng mua ngay | "inbox giá", "còn hàng không", "chốt luôn", "đặt lịch" |
| **Warm** | Đang nghiên cứu | "giá bao nhiêu", "mua ở đâu", "uy tín không", "gợi ý" |
| **Cold** | Mới khám phá | "nghe nói", "ai xài chưa", "xem review" |

**Export danh sách leads ra CSV** để dùng cho outreach:
```
tier, lead_score, author, author_id, product_category, reactions, post_url, preview
Warm, 0.6, Nguyen Van A, ..., beauty, 5, https://..., "Spa nào ok không mn?"
```

---

### 3. Crisis Management — Quản lý khủng hoảng

Tự động phát hiện 3 loại tín hiệu nguy hiểm:

| Alert | Điều kiện mặc định |
|-------|-------------------|
| Negative spike | Bài tiêu cực > 15% tổng bài |
| Viral negative | Bài tiêu cực > 500 reaction |
| Crisis keywords | Xuất hiện: "lừa đảo", "scam", "tẩy chay", "báo công an"... |

Khi có alert có thể **push Telegram** (cấu hình token + chat_id).

**Chạy continuous polling:**
```bash
python main.py monitor --group <id> --interval 300
```

---

### 4. Competitor Monitoring — Theo dõi đối thủ

Tính toán **Share of Voice (SOV)** và sentiment theo từng thương hiệu từ nội dung bài đăng. Cấu hình danh sách đối thủ trong `config/config.json`.

**Output:**
```json
{
  "total_brand_mentions": 4,
  "share_of_voice": [
    {"brand": "Spa/Thẩm mỹ", "mentions": 2, "sov_pct": 50.0},
    {"brand": "Grab", "mentions": 1, "sov_pct": 25.0}
  ],
  "brand_details": {
    "Spa/Thẩm mỹ": {
      "sentiment": {"positive_pct": 50.0, "negative_pct": 0.0}
    }
  }
}
```

---

### 5. Automated Reporting — Tự động hóa & NL Queries

**6 preset query bằng ngôn ngữ tự nhiên:**

| Query | Trả về |
|-------|--------|
| `"hot leads"` | Danh sách leads tier Hot |
| `"pain points"` | Top 10 bài đau nhất |
| `"viral posts"` | Top 5 bài tương tác cao nhất |
| `"negative posts"` | Phân phối sentiment |
| `"competitors"` | SOV + sentiment đối thủ |
| `"summary"` | Tóm tắt tổng hợp |

**Chạy scheduler tự động** (mỗi N giờ scrape + analyze tất cả groups):
```bash
python main.py schedule --interval 6
```

---

## Cách cài đặt

```bash
# 1. Cài dependencies
pip install -r requirements.txt

# 2. Cài Playwright browsers
playwright install chromium

# 3. Cấu hình Facebook credentials
# Sửa config/config.json → facebook.email + facebook.password

# 4. (Tùy chọn) Cấu hình đối thủ cạnh tranh
# Sửa config/config.json → competitors[]

# 5. (Tùy chọn) Cấu hình Gemini AI
# Set env: GEMINI_API_KEY=<key>

# 6. (Tùy chọn) Cấu hình Telegram alerts
# Sửa config/config.json → telegram.token + telegram.chat_id
```

---

## Cách dùng

### Luồng cơ bản

```bash
# Bước 1: Scrape bài đăng
python main.py scrape --group "https://www.facebook.com/groups/riviu.official" --days 30

# Bước 2: Phân tích (chạy toàn bộ 5 objectives)
python main.py analyze --group riviu.official

# Bước 3: Xem báo cáo
python main.py report --group riviu.official --type summary
```

### Tất cả lệnh trong một shot

```bash
python main.py full --group "https://www.facebook.com/groups/riviu.official" --days 7
```

### Xem từng loại báo cáo

```bash
# Tổng quan
python main.py report --group <id> --type summary

# Engagement & top bài
python main.py report --group <id> --type engagement

# Xu hướng & từ khoá tăng
python main.py report --group <id> --type trends

# Sentiment
python main.py report --group <id> --type sentiment

# Chủ đề thảo luận
python main.py report --group <id> --type topics

# Nỗi đau thị trường (Obj 1)
python main.py report --group <id> --type pain_points

# Leads tiềm năng (Obj 2)
python main.py report --group <id> --type leads

# Đối thủ (Obj 4)
python main.py report --group <id> --type competitors
```

### Export dữ liệu

```bash
# Export toàn bộ bài đăng ra CSV
python main.py export --group <id> --format csv

# Export danh sách leads (cho outreach)
python main.py export --group <id> --format leads
```

### Crisis monitor

```bash
# Kiểm tra một lần
python main.py monitor --group <id> --check-once

# Polling liên tục mỗi 5 phút
python main.py monitor --group <id> --interval 300
```

### NL Queries & Scheduler

```bash
# Query bằng ngôn ngữ tự nhiên
python main.py schedule --group <id> --query "hot leads"
python main.py schedule --group <id> --query "pain points"
python main.py schedule --group <id> --query "viral posts"

# Chạy pipeline ngay cho tất cả groups
python main.py schedule --run-now

# Start scheduler daemon (mỗi 6 giờ)
python main.py schedule --interval 6
```

### Tìm kiếm trong dữ liệu

```bash
# Tìm bài có từ khoá
python db_index.py query --group <id> --keyword "son môi" --limit 10

# Thống kê nhanh
python db_index.py stats --group <id>
```

### Liệt kê tất cả groups đã lưu

```bash
python main.py list
```

---

## Cấu hình (`config/config.json`)

| Trường | Ý nghĩa | Mặc định |
|--------|---------|----------|
| `scraper.headless` | Ẩn/hiện browser | `false` |
| `scraper.max_posts` | Số bài tối đa mỗi lần scrape | `500` |
| `scraper.days_back` | Lấy bài trong N ngày gần nhất | `30` |
| `analysis.pain_min_score` | Ngưỡng pain score tối thiểu | `0.3` |
| `analysis.lead_min_tier` | Tier tối thiểu để tính lead | `"Cold"` |
| `crisis.negative_pct_threshold` | % bài tiêu cực để alert | `15` |
| `crisis.viral_reactions_threshold` | Reaction threshold cho viral alert | `500` |
| `telegram.token` | Bot token Telegram | `""` |
| `competitors[].name` | Tên thương hiệu cần theo dõi | — |
| `competitors[].keywords` | Từ khoá nhận diện thương hiệu | — |
| `scheduler.interval_hours` | Tần suất chạy tự động | `6` |

**Thêm đối thủ cạnh tranh:**
```json
"competitors": [
  {
    "name": "Shopee",
    "keywords": ["shopee", "shopeepay"],
    "aliases": ["mua shopee"]
  }
]
```

**Thêm groups vào scheduler** (`config/scheduled_groups.json`):
```json
[
  "https://www.facebook.com/groups/riviu.official",
  "https://www.facebook.com/groups/yourgroup"
]
```

---

## Cấu trúc dữ liệu

```
data/
├── posts/
│   └── {group_id}/
│       ├── 2026-02.json       # Bài đăng theo tháng
│       └── _unknown.json      # Bài không có timestamp
├── reports/
│   └── {group_id}_analysis.json   # Kết quả phân tích (toàn bộ 5 objectives)
├── exports/
│   ├── {group_id}_{date}.csv       # CSV toàn bộ bài
│   └── {group_id}_leads_{date}.csv # CSV leads cho outreach
├── runs/
│   └── run_{ts}_{group_id}.json    # Log từng lần scrape
├── manifest.json              # Index groups + incremental cursor
└── index.db                   # SQLite index cho full-text search
```

---

## Lưu ý khi dùng trên Windows

Trước khi chạy lệnh, set encoding để tránh lỗi ký tự tiếng Việt:

```powershell
$env:PYTHONIOENCODING="utf-8"
python main.py ...
```

Hoặc đọc kết quả từ file thay vì stdout:

```bash
python main.py report --group <id> --type summary --output json
# Đọc: data/reports/{id}_analysis.json
```
