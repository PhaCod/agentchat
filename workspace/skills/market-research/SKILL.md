# Market Research AI Assistant

> AI-powered market research that searches web, Facebook groups, and TikTok, then synthesizes findings into actionable reports using Gemini.

```yaml
---
name: market-research
description: >
  Research any topic across web, Facebook, and TikTok. Use when the user asks about
  market research, trends, consumer insights, competitive analysis, product research,
  industry analysis, social media trends, or wants to understand what people are saying
  about a topic online.
emoji: 🔬
version: 1.0.0
author: dangt
tags:
  - market-research
  - social-media
  - trends
  - analysis
  - gemini
  - web-search
  - tiktok
  - facebook
  - competitive-intelligence
metadata:
  clawdbot:
    requires:
      bins:
        - python3
        - chromium
    config:
      stateDirs:
        - data/research
        - data/cache
        - sessions
      outputFormats:
        - json
        - markdown
---
```

## Overview

This skill provides a multi-source market research pipeline:

1. **Web Search** — Google Search via Gemini grounding for articles, statistics, and trends
2. **Facebook Groups** — Scrape real consumer discussions from Facebook groups
3. **TikTok** — Find trending videos, creators, and engagement data
4. **AI Analysis** — Gemini 2.5 Flash synthesizes all data into market intelligence
5. **Report Generation** — Professional markdown reports in Vietnamese or English

---

## Agent Chat Instructions

> **When the user asks anything about market research, trends, consumer insights, product analysis, competitive intelligence, or "what people think about X" — use this skill.**

The skill directory is: `C:\Users\dangt\.openclaw\workspace\skills\market-research`

All commands must be run from that directory with `python main.py ...`

### Natural Language → Command Mapping

> **IMPORTANT**: All commands must be run from the skill directory.
> Set env: `$env:PYTHONIOENCODING="utf-8"` before running on Windows.

| User says | Command to run |
|-----------|----------------|
| "nghiên cứu về X" / "research X" | `python main.py research --topic "X" --sources web,tiktok --output json` |
| "nghiên cứu X trên tất cả nền tảng" | `python main.py research --topic "X" --sources web,facebook,tiktok --output json` |
| "tìm hiểu thị trường X" / "market X" | `python main.py research --topic "X" --sources web,tiktok --output json` |
| "xu hướng X" / "trend X" | `python main.py web --topic "xu hướng X 2026" --output json` |
| "mọi người nói gì về X" / "people say about X" | `python main.py research --topic "X" --sources facebook,tiktok --output json` |
| "tìm trên web" / "search web" | `python main.py web --topic "X" --output json` |
| "tìm trên facebook" / "facebook X" | `python main.py facebook --topic "X" --output json` |
| "tìm trên tiktok" / "tiktok X" | `python main.py tiktok --topic "X" --output json` |
| "phân tích lại" / "re-analyze" | `python main.py analyze --topic "X" --output json` |
| "báo cáo" / "report" | `python main.py report --topic "X" --output json` |
| "danh sách nghiên cứu" / "list" | `python main.py list --output json` |
| "đọc nghiên cứu" / "read research" | `python main.py read --topic "X" --output json` |

**Default language**: Vietnamese (`--lang vi`)
**Default sources**: web + tiktok (fastest, no login needed)
**Full research**: `--sources web,facebook,tiktok` (includes Facebook, requires login)

### After Running Commands

> **⚠️ IMPORTANT — Encoding on Windows**: Exec stdout may contain garbled characters.
> Always read the saved output files instead of parsing stdout.
> - Research results: `data/research/<timestamp>_<topic>.json`
> - Reports: `data/research/<timestamp>_<topic>_report.md`

1. Run the command via Exec
2. Read the latest file in `data/research/` for clean UTF-8 results
3. Present findings as a clear Vietnamese summary to the user

### Example Flows

1. User: "nghiên cứu thị trường son môi"
   ```
   Step 1: Exec → python main.py research --topic "thị trường son môi Việt Nam" --sources web,tiktok --output json
   Step 2: Read latest file in data/research/*.json
   Step 3: Present executive summary + key findings + trends + recommendations in Vietnamese
   ```

2. User: "mọi người trên facebook nói gì về sữa rửa mặt"
   ```
   Step 1: Exec → python main.py research --topic "sữa rửa mặt" --sources facebook --output json
   Step 2: Read report file → Present consumer sentiments and pain points
   ```

3. User: "xu hướng tiktok tháng này về skincare"
   ```
   Step 1: Exec → python main.py tiktok --topic "skincare trend Vietnam 2026" --output json
   Step 2: Present trending videos, creators, and engagement stats
   ```

---

## Usage

### CLI Interface

```bash
# Full research (web + tiktok — fast, no login)
python main.py research --topic "cà phê Việt Nam" --sources web,tiktok --output json

# Full research (all sources — includes Facebook)
python main.py research --topic "cà phê Việt Nam" --sources web,facebook,tiktok --output json

# Web search only
python main.py web --topic "thị trường cà phê Việt Nam 2026" --output json

# Facebook group search
python main.py facebook --topic "cà phê" --days 7 --output json

# TikTok video search
python main.py tiktok --topic "coffee review Vietnam" --output json

# Re-analyze previous data
python main.py analyze --topic "cà phê" --output json

# Generate formatted report
python main.py report --topic "cà phê" --output json

# List all research
python main.py list --output json
```

### MCP Server

```bash
# Start as MCP server (stdio — for OpenClaw)
python server.py

# Start as HTTP MCP server (for external clients)
python server.py --transport http --port 8100
```

---

## Configuration

Edit `config.json`:

```json
{
  "gemini": {
    "model": "gemini-2.5-flash",
    "temperature": 0.7,
    "max_output_tokens": 8192
  },
  "search": {
    "web_max_results": 10,
    "facebook_max_posts": 30,
    "tiktok_max_videos": 20,
    "cache_ttl_hours": 6
  },
  "facebook": {
    "default_groups": [
      "https://www.facebook.com/groups/riviu.official/?sorting_setting=CHRONOLOGICAL"
    ]
  }
}
```

---

## File Outputs

| Path | Description |
|------|-------------|
| `data/research/<ts>_<topic>.json` | Full research result (all sources + analysis) |
| `data/research/<ts>_<topic>_report.md` | Formatted markdown report |
| `data/cache/<key>.json` | Cached search results (TTL-based) |
