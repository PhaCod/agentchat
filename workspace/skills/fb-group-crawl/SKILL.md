````skill

# Facebook Group Crawl & AI Query

> Crawl full Facebook group posts into SQLite, then query the database with natural language through AI.

```yaml
---
name: fb-group-crawl
description: Crawl Facebook group posts into a SQLite database, then answer any question about the data using AI. Use when the user wants to collect Facebook group data, store it, search posts, get stats, or ask AI to analyze/summarize group activity.
emoji: 🗄️
version: 1.0.0
author: dangt
tags:
  - facebook
  - crawling
  - sqlite
  - ai-query
  - data-collection
metadata:
  clawdbot:
    requires:
      bins:
        - python3
        - chromium
    config:
      stateDirs:
        - data
        - sessions
      outputFormats:
        - json
        - csv
---
```

## Overview

Simple 3-layer architecture:

1. **Crawl** — Playwright scraper collects all post fields from Facebook group feed
2. **Store** — SQLite database with FTS5 full-text search and time-series indexes
3. **Query** — Ask any question in natural language, AI synthesizes answer from the database

No predefined analysis modules. The AI answers whatever you ask, based on the actual data.

---

## Agent Chat Instructions

> **Use this skill when the user wants to crawl/collect Facebook group posts, store them, search stored data, or ask AI questions about a Facebook group's content.**

The skill directory is: `C:\Users\dangt\.openclaw\workspace\skills\fb-group-crawl`

All commands must be run from that directory with `python main.py ...`

### Natural Language → Command Mapping

> **IMPORTANT**: Set env first on Windows:
> `$env:PYTHONIOENCODING="utf-8"`

| User says | Command to run |
|-----------|----------------|
| "crawl group X" / "lấy dữ liệu group X" | `python main.py scrape --group "<url>" --days 30 --output json` |
| "lấy N bài" / "scrape N posts" | `python main.py scrape --group "<url>" --max-posts <N> --output json` |
| "crawl lại từ đầu" / "full rescrape" | `python main.py scrape --group "<url>" --full-rescrape --output json` |
| "hỏi về group X" / any question | `python main.py ask --group <id> -q "<question>" --output json` |
| "tuần này group bàn gì?" | `python main.py ask --group <id> -q "tuần này group bàn gì?" --output json` |
| "top bài viral" | `python main.py ask --group <id> -q "top bài viral nhất" --output json` |
| "ai đang bán hàng" | `python main.py ask --group <id> -q "ai đang bán hàng trong group"` |
| "thống kê" / "stats" | `python main.py stats --group <id> --output json` |
| "tìm bài về X" / "search X" | `python main.py search --group <id> -k "<keyword>" --output json` |
| "tìm deal rẻ / săn hàng / mua bán" (bất kỳ chủ đề) | `python main.py market --group <id> -q "<câu hỏi rộng>" --days 7 --limit 10 --output json` |
| "lưu batch để hỏi lại" / "RAG batch" | `python main.py rag-build --group <id> -q "<topic>" --days 7 --output json` |
| "hỏi lại từ batch đã lưu" | `python main.py rag-ask --group <id> -q "<question>" --output json` |
| "tìm mới (nếu chưa có batch thì auto crawl 20 bài)" | `python main.py rag-query --group "<url_or_id>" -q "<question>" --limit 10 --output json` |
| "xuất CSV" / "export" | `python main.py export --group <id> --output json` |
| "group nào đã lưu" / "list groups" | `python main.py groups --output json` |

**Default group** (nếu user không chỉ định): If the user doesn't specify, ask which group.

**After running `ask` command**, present the AI answer directly. No need to read files — the answer is in the command output.

**After running `scrape` command**, read the JSON output and report: how many posts scraped, how many new, total in database.

---

## Broad Questions (any topic/product) — How to reason

This skill is meant for **wide questions**, not only one keyword.

When user asks: *\"nhóm này bán gì\"*, *\"tìm X\"*, *\"giá bao nhiêu\"*, *\"trend gì\"*, *\"có ai bán/need mua\"*, etc.:

1) **Expand the query** (do not search literally only):
   - Add variants: abbreviations, spacing, VI/EN (e.g. `iphone 15` → `iphone15`, `ip15`, `15 pro`, `15pm`, `15 pro max`, `15 prm`).
   - Add marketplace signals: `bán`, `pass`, `cần mua`, `inbox`, `giá`, `fix`, `ship`, `TPHCM/HN`, `VN/A`, `LL/A`, capacities (`128/256/512`).
2) **Use the DB first**:
   - Run `search` multiple times with expanded keywords and merge results (dedup by `post_url` or `post_id`).
   - If results are sparse, **scrape more** (increase `--days` or `--max-posts`) then repeat search.
3) **Decide which command to use (router logic)**:
   - If question is about **mua/bán + giá cụ thể** → prefer `market` (fast, no LLM).
   - If question is **“tìm bài / liệt kê / search X”** → prefer `rag-query` (RAG listing with small crawl fallback).
   - If question is về **trend, insight, tổng kết, so sánh theo thời gian** → prefer `ask` (full AI summary).
   - The Python module `query_router.py` implements this as code (`decide_route()`), you can mirror its rules in prompts if needed.

### Time-aware crawl policy (production defaults)

- Mặc định crawl tối đa **20 bài** (`config.json: scraper.max_posts=20`).
- `rag-query` tự detect thời gian từ câu hỏi ("3 ngày qua" → 3, không nói → default 7 ngày).
- **DB-first**: nếu DB đã có ≥ 60 bài trong cửa sổ thời gian → **skip crawl**, dùng data sẵn.
- Crawl window = `min(days_question, 7)` — không crawl sâu quá 7 ngày.
- Output JSON có `time_policy` cho debug: `days_question, days_crawl, existing_posts_in_window, did_crawl`.

### Example Flows

1. User: "phân tích group X" / "group này đang bàn gì 3 ngày qua"
   ```
   python main.py rag-query --group "https://www.facebook.com/groups/riviu.official" -q "chủ đề hot nhất 3 ngày qua" --limit 10 --output json
   ```
   → DB-first; nếu thiếu data thì auto crawl max 20 bài trong 3 ngày.

2. User: "tìm bài về son môi"
   ```
   python main.py search --group riviu.official -k "son môi" --output json
   ```

3. User: "tìm xe giá rẻ dưới 10tr"
   ```
   python main.py market --group riviu.official -q "xe giá rẻ dưới 10tr" --days 7 --limit 10 --output json
   ```

4. User: "tìm iPhone 17" (tự động, DB-first + small crawl)
   ```
   python main.py rag-query --group "https://www.facebook.com/groups/riviu.official" -q "iphone 17" --limit 10 --output json
   ```

5. User: cần crawl nhiều hơn (explicit)
   ```
   python main.py scrape --group "https://www.facebook.com/groups/riviu.official" --max-posts 50 --days 7 --output json
   ```

---

## File Outputs

| Path | Description |
|------|-------------|
| `data/fb_posts.db` | SQLite database (all posts, all groups) |
| `data/{group_id}_{date}.csv` | CSV export |
| `sessions/fb_session.json` | Saved Facebook login session |

---

## Configuration

Edit `config/config.json`:

```json
{
  "scraper": {
    "headless": false,
    "scroll_delay_ms": 2500,
    "max_posts": 20,
    "days_back": 30,
    "skip_low_quality": true
  },
  "facebook": {
    "email": "",
    "password": "",
    "session_file": "sessions/fb_session.json"
  },
  "gemini": {
    "model": "gemini-2.5-flash",
    "max_posts_per_query": 30,
    "language": "vi"
  }
}
```

Or use environment variables:
- `FB_EMAIL` / `FB_PASSWORD` — Facebook credentials
- `GOOGLE_API_KEY` — Gemini API key
- `GEMINI_MODEL` — Override model name

````
