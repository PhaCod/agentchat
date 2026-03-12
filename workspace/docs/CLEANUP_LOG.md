# Cleanup log — files removed for clear source & QC

**Date:** 2026-03-10

## Removed (không cần cho source, tránh AI nhầm lẫn)

| Item | Lý do |
|------|--------|
| `tmp-openclaw-skills/` (cả thư mục) | Clone tạm để cài goodreads; skill đã copy vào workspace/skills/goodreads. |
| Tất cả `tmpclaude-*-cwd` (trong .openclaw và workspace/skills) | Thư mục tạm do editor/agent tạo, không phải source. |
| `openclaw.json.bak` | Backup config; dùng openclaw.json. |
| `workspace/skills/facebook-group-analyzer/data/posts/*.json.bak` | Backup dữ liệu posts cũ; data chính nằm trong data/posts/<id>/ hoặc partition. |
| `workspace/skills/facebook-group-analyzer/_restore_ai.py` | Script một lần để restore ai_insights vào report; không dùng trong flow chạy. |

## Giữ lại (source & QC)

- Toàn bộ file nguồn: `*.py`, `SKILL.md`, `README.md`, `config/`, script trong `scripts/`.
- Cấu hình: `config.json`, `openclaw.json`, `.env` (không commit; chỉ ignore trong .cursorignore).
- Docs: `docs/`, `references/`, `CRAWL_LOGIC.md`, v.v.
- Data thật (posts, reports): giữ trong `data/`; chỉ xóa file `.bak`.

## Để tránh tái tạo rác

- **Tạo `.cursorignore`** (ở thư mục gốc project hoặc workspace) với nội dung gợi ý:
  ```
  .venv/
  venv/
  __pycache__/
  tmp-openclaw-skills/
  tmpclaude-*-cwd/
  *.bak
  .env
  ```
  để Cursor/AI không index các thư mục và file này.
- Nên thêm vào **.gitignore** (nếu dùng git): `tmp-openclaw-skills/`, `tmpclaude-*-cwd/`, `*.bak`, `.env`, `.venv/`, `__pycache__/`.
