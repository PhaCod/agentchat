# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## General Skill Reasoning (broad questions)

When you (or the agent) need to answer broad questions from social groups (any product/topic, not only iPhone):

- **Query expansion** (always): include spelling variants, abbreviations, model lines, capacities, and VI/EN synonyms.
  - Example patterns: `ip15`, `iphone15`, `15pm`, `15 pro max`, `15 prm`, `VN/A`, `LL/A`, `99%`, `fullbox`, `trả góp`, `thu cũ đổi mới`, `bảo hành`.
- **Coverage**: default **7 days**, expand to **30 days** if few matches.
- **Execution order**: search existing stored data first → scrape more only if needed.
- **Output format**: list matches with **link + price/model/location (if present)** + short preview, and note coverage (posts scanned, time window).

---

## Facebook Group Analyzer

- **Skill dir**: `C:\Users\dangt\.openclaw\workspace\skills\facebook-group-analyzer`
- **Run commands from**: that directory, via `python main.py ...`
- **Default group**: `1125804114216204` (https://www.facebook.com/groups/1125804114216204)
- **Session:** Skill dùng `sessions/fb_session.json` trong skill dir, hoặc fallback **workspace/sessions/fb_session.json**. Nếu gặp modal "See more on Facebook" hoặc redirect login → cần **re-login**.
- **Re-login (tự đăng nhập):** Đặt `FB_EMAIL` và `FB_PASSWORD` trong `workspace/skills/facebook-group-analyzer/.env` (hoặc env khi chạy). Khi session hết hạn scraper sẽ tự đăng nhập và lưu session mới. Không có credentials thì scrape sẽ thất bại khi cần login.
- **Timestamp:** Chỉ lấy được đầy đủ khi **đã đăng nhập**; nếu không login đúng, hầu hết bài sẽ "(No specific time)". Chi tiết: `skills/facebook-group-analyzer/docs/CRAWL_LOGIC.md`.
- **Data stored**: `data/posts/<group_id>.json`, reports in `data/reports/`
- **List all scraped groups**: `python main.py list --output json`

---

## Market Research AI Assistant

- **Skill dir**: `C:\Users\dangt\.openclaw\workspace\skills\market-research`
- **Run commands from**: that directory, via `python main.py ...`
- **Sources**: web (Google via Gemini), Facebook groups, TikTok
- **AI engine**: Gemini 2.5 Flash (free tier)
- **Output**: `data/research/<timestamp>_<topic>.json` and `_report.md`

### Quick commands:
```bash
# Full research (web + tiktok)
python main.py research --topic "your topic" --sources web,tiktok --output json

# All platforms including Facebook
python main.py research --topic "your topic" --sources web,facebook,tiktok --output json

# Single source
python main.py web --topic "..." --output json
python main.py tiktok --topic "..." --output json
python main.py facebook --topic "..." --output json
```

---

## Goodreads

- **Skill dir**: `C:\Users\dangt\.openclaw\workspace\skills\goodreads`
- **Run commands from**: `workspace\skills\goodreads\scripts` (Python + goodreads-rss.py / goodreads-writer.py)
- **Goodreads user ID** (for shelf/activity): replace with real ID from goodreads.com/user/show/XXXXX-yourname → use in `shelf` and `activity` commands.
- **Read (RSS, no login):** `python goodreads-rss.py shelf <USER_ID> --shelf currently-reading`, `python goodreads-rss.py search "tên sách" --limit 5`, `python goodreads-rss.py book <book_id>`
- **Write (after one-time login):** `python goodreads-writer.py login` once, then `python goodreads-writer.py rate <book_id> 5`, `python goodreads-writer.py shelf <book_id> read`, `goodreads-write.bat start <book_id>`
- **Full instructions**: `workspace\skills\goodreads\RUN.md`, `workspace\skills\goodreads\SKILL.md`

---

## Token balance (ước lượng sử dụng OpenClaw)

- **Script**: `workspace/scripts/token_balance.py` — đọc session logs (`agents/main/sessions/*.jsonl`) + ledger skill (`workspace/data/token_usage.jsonl`), tổng hợp token theo ngày và theo nguồn (agent, tool, skill).
- **Chạy từ thư mục workspace**:
  ```bash
  python scripts/token_balance.py --days 30 --output docs/TOKEN_BALANCE_SHEET.md --json docs/token_summary.json
  ```
- **Kết quả**: `docs/TOKEN_BALANCE_SHEET.md` (balance sheet 1 tháng), `docs/token_summary.json` (chi tiết). Dùng để ước lượng chi phí và so sánh với phương pháp khác (ChatGPT API, Claude, Ollama...).
- Skill **fb-group-crawl** khi gọi Gemini (lệnh `ask`) tự ghi mỗi lần vào `workspace/data/token_usage.jsonl`.

---

Add whatever helps you do your job. This is your cheat sheet.
