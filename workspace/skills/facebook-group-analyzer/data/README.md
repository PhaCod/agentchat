# Data layout (schema v1.0)

## Thư mục

| Thư mục | Mô tả |
|--------|--------|
| `posts/` | Raw bài đăng theo group (JSON container) |
| `reports/` | Kết quả phân tích theo group (JSON) |
| `exports/` | Export CSV theo thời điểm |
| `manifest.json` | Index: danh sách group + last_scraped_at, last_analyzed_at |

## Posts: `posts/{group_id}.json`

Định dạng mới (schema_version 1.0):

```json
{
  "schema_version": "1.0",
  "group_id": "1125804114216204",
  "updated_at": "2026-03-04T12:00:00+00:00",
  "post_count": 500,
  "posts": [
    {
      "post_id": "...",
      "group_id": "...",
      "author": "...",
      "author_id": "...",
      "content": "...",
      "media": [{"type": "image", "url": "..."}],
      "reactions": {"total": 0, "like": 0, "love": 0, "haha": 0, "wow": 0, "sad": 0, "angry": 0},
      "comments_count": 0,
      "shares_count": 0,
      "post_url": "...",
      "timestamp": "2026-03-01T00:00:00+00:00",
      "content_type": "text|image|video|link",
      "scraped_at": "2026-03-04T12:00:00+00:00",
      "spam_score": 0.0
    }
  ]
}
```

- **Tương thích ngược**: File cũ (mảng `[...]` trực tiếp) vẫn đọc được; lần ghi tiếp theo sẽ chuyển sang container.
- Trường bổ sung từ analyzer: `spam_score` (optional).

## Reports: `reports/{group_id}_analysis.json`

- Luôn có `schema_version: "1.0"`.
- Các key chính: `group_id`, `analyzed_at`, `total_posts`, `date_range`, `sentiment`, `top_keywords`, `topics`, `spam_posts_count`, `spam_post_ids`, `engagement`, `trends`.

## Manifest: `manifest.json`

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-03-04T12:00:00+00:00",
  "groups": [
    {
      "group_id": "1125804114216204",
      "post_count": 500,
      "date_range": {"from": "2026-02-01", "to": "2026-03-04"},
      "last_scraped_at": "2026-03-04T12:00:00+00:00",
      "last_analyzed_at": "2026-03-04T12:05:00+00:00"
    }
  ]
}
```

- Cập nhật mỗi khi `save_posts` hoặc `save_report`.
- Dùng để liệt kê nhanh group và thời điểm cập nhật.

## Exports: `exports/{group_id}_{YYYYmmdd_HHMMSS}.csv`

- Cột theo `schemas.csv_fieldnames()`: post_id, group_id, author, author_id, content, content_type, timestamp, scraped_at, reactions_total, comments_count, shares_count, post_url, spam_score.
- Encoding: UTF-8 with BOM.

## Schema definition

- `schemas.py`: `POSTS_SCHEMA_VERSION`, `REPORT_SCHEMA_VERSION`, `POST_REQUIRED_FIELDS`, `posts_container()`, `unwrap_posts()`, `report_with_schema()`, `post_to_row()`, `csv_fieldnames()`, `group_manifest_entry()`, `manifest_skeleton()`.
