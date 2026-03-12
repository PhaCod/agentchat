````skill

# Facebook Group Post Analyzer

> Part of **[ScrapeClaw](https://www.scrapeclaw.cc/)** — production-ready agentic social media scrapers built with Python & Playwright, no API keys required.

A complete pipeline to scrape, store, and analyze posts from Facebook groups — with AI-powered sentiment analysis, topic clustering, engagement analytics, and trend detection.

```yaml
---
name: facebook-group-analyzer
description: Scrape, query, and analyze posts from Facebook groups. Use when the user asks about Facebook group content, posts, engagement, trends, sentiments, topics, spam, viral posts, or wants to get data/reports from a Facebook group.
emoji: 📊
version: 1.0.0
author: dangt
tags:
  - facebook
  - scraping
  - social-media
  - analysis
  - sentiment
  - trend-detection
  - engagement
  - group-analytics
metadata:
  clawdbot:
    requires:
      bins:
        - python3
        - chromium

    config:
      stateDirs:
        - data/posts
        - data/reports
        - data/exports
        - sessions
      outputFormats:
        - json
        - csv
---
```

## Overview

This skill provides a 6-phase Facebook group post analysis pipeline:

1. **Post Collection** — Scrape posts, reactions, comments via headless browser
2. **Structured Storage** — Deduplicated JSON/CSV storage per group
3. **Content Analysis** — Sentiment, topics, keywords, spam detection
4. **Engagement Analysis** — Top posts, best hours, content-type breakdown
5. **Trend Detection** — Time-series topic shifts, viral post alerts
6. **Agent Tool Interface** — JSON tools callable by OpenClaw agents

---

## Agent Chat Instructions

> **When the user asks anything about Facebook group posts, data analysis, scraping, or group analytics — use this skill.**

The skill directory is: `C:\Users\dangt\.openclaw\workspace\skills\facebook-group-analyzer`

All commands must be run from that directory with `python main.py ...`

### Natural Language → Command Mapping

> **IMPORTANT**: All commands must be run from the skill directory:
> `cd C:\Users\dangt\.openclaw\workspace\skills\facebook-group-analyzer`
> Set env: `$env:PYTHONIOENCODING="utf-8"` before running on Windows.

| User says | Command to run |
|-----------|----------------|
| "scrape group X" / "lấy dữ liệu group X" | `python main.py scrape --group "<url>" --days 7 --output json` |
| "lấy N bài mới nhất" | `python main.py full --group "<url>" --days 1 --max-posts <N> --output json` |
| "phân tích group X" / "analyze" | `python main.py analyze --group <id> --output json` |
| "tóm tắt" / "summary" / "báo cáo" | `python main.py report --group <id> --type summary --output json` |
| "top bài" / "bài viral" / "engagement" | `python main.py report --group <id> --type engagement --output json` |
| "xu hướng" / "trend" / "từ khoá tăng" | `python main.py report --group <id> --type trends --output json` |
| "sentiment" / "cảm xúc" / "tích cực tiêu cực" | `python main.py report --group <id> --type sentiment --output json` |
| "chủ đề" / "topic" | `python main.py report --group <id> --type topics --output json` |
| "spam" / "quảng cáo" | `python main.py report --group <id> --type spam --output json` |
| "từ khoá" / "keywords" | `python main.py report --group <id> --type keywords --output json` |
| "export" / "csv" / "xuất file" | `python main.py export --group <id> --output json` |
| "group nào" / "danh sách" / "list" | `python main.py list --output json` |
| "scrape + phân tích luôn" | `python main.py full --group "<url>" --days 7 --output json` |
| "tìm bài về X" / "search keyword" | `python db_index.py query --group <id> --keyword "<X>" --limit 10` |
| "thống kê nhanh" / "stats" | `python db_index.py stats --group <id>` |
| "validate data" / "kiểm tra dữ liệu" | `python validate_schema.py data/posts/<id>/<partition>.json` |
| "PII audit" / "kiểm tra thông tin cá nhân" | `python pii.py audit data/posts/<id>/<partition>.json` |
| "dọn dẹp data cũ" / "cleanup" | `python scripts/cleanup.py --dry-run` |
| "lịch sử scrape" / "run log" | Query `data/runs/` directory for recent run JSON files |

**Default group** (nếu user không chỉ định): `riviu.official`
**Default group URL**: `https://www.facebook.com/groups/riviu.official/?sorting_setting=CHRONOLOGICAL`

**After running any command**, read the saved report file for clean UTF-8 data, then present a human-readable Vietnamese summary. Do NOT dump raw JSON.

---

## Broad Search & Inference (any topic/product)

When the user asks broad questions like:
- \"tìm X trong group\" (X có thể là bất cứ sản phẩm/chủ đề nào)
- \"nhóm này kinh doanh/bán gì\"
- \"giá X bao nhiêu\" / \"có ai pass/need mua không\"

Do **not** search only the literal phrase. Use this consistent process:

1) **Expand keyword bundle**:
   - Variants: viết liền/viết cách, viết tắt, slang, model lines, capacities, regions (VN/A, LL/A), common typos.
   - Marketplace signals: `bán`, `pass`, `need`, `cần mua`, `inbox`, `giá`, `fix`, `ship`, `TPHCM/HN`.
2) **Ensure coverage**:
   - Default: scrape last **7 days**.
   - If few matches: scrape **30 days** or increase `--max-posts`.
3) **Execution order**:
   - `scrape`/`full` (small first: 20–50 posts) → `db_index.py query` with multiple keywords → merge & dedup results.
   - Then `analyze/report` only when user wants insights, not just matches.
4) **Output format**:
   - Return: list of matching posts with `post_url`, `timestamp` (or `scraped_at`), `price/model/location` if present, and a short preview.

> **⚠️ IMPORTANT — Encoding on Windows**: The Exec stdout may contain garbled characters.
> Always read the saved output file instead of parsing stdout directly.
> Report files are always stored as clean UTF-8 at:
> - Analysis result: `data/reports/<group_id>_analysis.json`
> - Raw posts: `data/posts/<group_id>/YYYY-MM.json` or `data/posts/<group_id>/_unknown.json`

**Example flows:**
1. User: "lấy 10 bài mới nhất group riviu"
   ```
   Step 1: Run Exec → $env:PYTHONIOENCODING="utf-8"; python main.py full --group "https://www.facebook.com/groups/riviu.official/?sorting_setting=CHRONOLOGICAL" --days 1 --max-posts 10 --output json
   Step 2: Read file → data/reports/riviu.official_analysis.json
   Step 3: Parse clean JSON → Present summary in Vietnamese
   ```

2. User: "group đang bàn về gì hôm nay?"
   ```
   Step 1: Run Exec → $env:PYTHONIOENCODING="utf-8"; python main.py report --group riviu.official --type topics --output json
   Step 2: Read file → data/reports/riviu.official_analysis.json
   Step 3: "Nhóm đang thảo luận chủ yếu về [X] (Y%)..."
   ```

3. User: "tìm bài về son môi"
   ```
   Step 1: Run Exec → $env:PYTHONIOENCODING="utf-8"; python db_index.py query --group riviu.official --keyword "son môi" --limit 10
   Step 2: Parse stdout (db_index output is ASCII-safe) → List matching posts with content preview
   ```

---

## Usage

### Agent Tool Interface

```bash
# 1. Scrape posts from a group (by group URL or name)
python main.py scrape --group "https://facebook.com/groups/mygroup" --days 30 --output json

# 2. Analyze stored posts (run after scrape)
python main.py analyze --group mygroup --output json

# 3. Get engagement report
python main.py report --group mygroup --type engagement --output json

# 4. Get trend report
python main.py report --group mygroup --type trends --period weekly --output json

# 5. Get full summary (scrape + analyze + report in one shot)
python main.py full --group "https://facebook.com/groups/mygroup" --days 7 --output json

# 6. Export to CSV
python main.py export --group mygroup --format csv
```

---

## Output Data

### Post Schema

```json
{
  "post_id": "123456789",
  "group_id": "mygroup",
  "author": "Nguyen Van A",
  "author_id": "user_abc123",
  "content": "Nội dung bài đăng...",
  "media": [
    {"type": "image", "url": "https://..."}
  ],
  "reactions": {
    "total": 145,
    "like": 100,
    "love": 30,
    "haha": 10,
    "wow": 3,
    "sad": 1,
    "angry": 1
  },
  "comments_count": 32,
  "shares_count": 12,
  "post_url": "https://facebook.com/groups/mygroup/posts/123456789",
  "timestamp": "2026-02-28T14:30:00",
  "content_type": "text|image|video|link|reel",
  "scraped_at": "2026-03-01T08:00:00"
}
```

### Analysis Schema

```json
{
  "group_id": "mygroup",
  "analyzed_at": "2026-03-01T08:00:00",
  "total_posts": 250,
  "date_range": {"from": "2026-02-01", "to": "2026-03-01"},
  "sentiment": {
    "positive": 145,
    "neutral": 80,
    "negative": 25,
    "distribution_pct": {"positive": 58.0, "neutral": 32.0, "negative": 10.0}
  },
  "top_keywords": [
    {"keyword": "review", "count": 45},
    {"keyword": "giá", "count": 38}
  ],
  "topics": [
    {"topic": "Hỏi giá sản phẩm", "post_count": 60, "pct": 24.0},
    {"topic": "Review + feedback", "post_count": 85, "pct": 34.0},
    {"topic": "Quảng cáo/spam", "post_count": 20, "pct": 8.0}
  ],
  "spam_posts": 20,
  "engagement": {
    "avg_reactions": 58.0,
    "avg_comments": 12.8,
    "avg_shares": 4.8,
    "top_posts": [
      {
        "post_id": "987654321",
        "content_preview": "...",
        "reactions": 892,
        "comments_count": 145,
        "shares_count": 67
      }
    ],
    "best_hours": [9, 12, 20],
    "content_type_breakdown": {
      "image": {"count": 110, "avg_reactions": 72.0},
      "video": {"count": 40, "avg_reactions": 120.0},
      "text": {"count": 80, "avg_reactions": 25.0},
      "link": {"count": 20, "avg_reactions": 18.0}
    }
  },
  "trends": {
    "rising_keywords": ["flash sale", "giao hàng"],
    "declining_keywords": ["khuyến mãi"],
    "viral_posts": ["987654321"],
    "weekly_topic_shift": {
      "week_1": {"topic": "Review", "pct": 40.0},
      "week_4": {"topic": "Review", "pct": 28.0}
    }
  }
}
```

---

## Configuration

Edit `config/config.json`:

```json
{
  "scraper": {
    "headless": false,
    "scroll_delay_ms": 2000,
    "max_posts": 500,
    "days_back": 30,
    "download_media_meta": true
  },
  "analysis": {
    "language": "vi",
    "sentiment_model": "rule_based",
    "min_keyword_freq": 3,
    "spam_min_score": 0.7,
    "topic_clusters": 8
  },
  "proxy": {
    "enabled": false,
    "provider": "netnut",
    "username": "",
    "password": "",
    "country": "vn"
  },
  "facebook": {
    "email": "",
    "password": "",
    "session_file": "sessions/fb_session.json"
  }
}
```

---

## Filters

Auto-filters:
- ❌ Deleted / hidden posts
- ❌ Duplicate posts (by `post_id`)
- ❌ Posts outside date range
- ❌ Spam posts (when `--filter-spam`)

---

## File Outputs

| Path | Description |
|------|-------------|
| `data/posts/{group_id}/YYYY-MM.json` | Raw posts (time-partitioned by month) |
| `data/posts/{group_id}/_unknown.json` | Posts without timestamp |
| `data/reports/{group_id}_analysis.json` | Full analysis result |
| `data/exports/{group_id}_{date}.csv` | CSV export |
| `data/runs/run_{ts}_{group_id}.json` | Scrape run log (lineage) |
| `data/manifest.json` | Group index + incremental cursor |
| `data/index.db` | SQLite index for fast queries |
| `sessions/fb_session.json` | Saved login session |

````
