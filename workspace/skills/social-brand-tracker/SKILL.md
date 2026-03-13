# social-brand-tracker

**Social Brand Tracker** — Crawl Facebook Groups + Pages, analyze brand performance: sentiment, trends, pain points, influencers, share of voice.

## Quick Start

```bash
cd workspace/skills/social-brand-tracker
pip install -r requirements.txt
playwright install chromium
```

## Commands

| Command | Description | LLM? |
|---------|-------------|------|
| `scrape --source <url> --max-posts 50 --with-comments` | Crawl posts + comments | No |
| `analyze --source <id> --days 7` | Full analysis pipeline | Optional |
| `brand --source <id> --brands "HMK,Shopee" --days 7` | Brand mentions + SOV | No |
| `trends --source <id> --days 7` | Topic velocity + rising/declining | No |
| `pain-points --source <id> --brand "HMK" --days 7` | Pain point extraction | Optional |
| `influencers --source <id> --min-followers 10000` | Top influencers | No |
| `report --source <id> --days 7 --format md` | Full dashboard report | Yes |

## Data Stored (SQLite: data/brand_tracker.db)

- **posts**: post_id, content, author, reactions, comments_count, shares, views, media_type, timestamp
- **comments**: comment_id, post_id, parent_comment_id (threading), commenter, likes, replies
- **users**: user_id, follower_count, is_influencer, location, bio
- **hashtags**: tag_raw, tag_normalized, linked to post/comment
- **mentions**: @mention, mention_type (brand/user), sentiment
- **analysis_runs**: run history with results JSON

## Example Flows

1. Crawl a group with comments:
   ```
   python main.py scrape --source "https://www.facebook.com/groups/riviu.official" --max-posts 50 --with-comments --output json
   ```

2. Analyze brand performance:
   ```
   python main.py brand --source riviu.official --brands "HMK,Shopee" --days 7 --output json
   ```

3. Get trending topics:
   ```
   python main.py trends --source riviu.official --days 7 --output json
   ```

4. Full report:
   ```
   python main.py report --source riviu.official --days 7 --format md --output json
   ```

## Configuration

Edit `config/config.json`:
- `scraper`: headless, scroll_delay, max_posts, max_comments_per_post, timeout
- `brands`: list of brands to track with aliases and keywords
- `analysis`: influencer_threshold, trend_window, min_keyword_freq
- `gemini`: model and language for AI summaries

## Agent Routing

- If user asks about **brand performance / sentiment / pain points / influencers** on Facebook → use this skill
- If user asks about **simple post search / RAG query** on a group → use `fb-group-crawl` instead
- `scrape` first, then `analyze` or specific sub-commands
