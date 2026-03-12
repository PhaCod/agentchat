# Facebook Group Analyzer — Production Runbook

## 1. Môi trường

- **Python**: 3.10+ (khuyến nghị 3.10 hoặc 3.11).
- **Chromium**: cài qua `playwright install chromium` sau khi `pip install -r requirements.txt`.
- **Secrets**: không lưu trong `config/config.json`; dùng biến môi trường.

## 2. Cấu hình bí mật (Production)

1. Copy `.env.example` thành `.env` (hoặc set env trực tiếp trên server).
2. Điền và export:
   - `FB_EMAIL`: email đăng nhập Facebook.
   - `FB_PASSWORD`: mật khẩu (hoặc app password nếu bật 2FA).
3. Tuỳ chọn:
   - `FB_SESSION_FILE`: đường dẫn file session (mặc định `sessions/fb_session.json`).
   - `PROXY_ENABLED`, `PROXY_USERNAME`, `PROXY_PASSWORD` nếu dùng proxy.
   - `LOG_LEVEL`: `INFO` (mặc định), `DEBUG`, `WARNING`, `ERROR`.
   - `LOG_FORMAT`: `text` hoặc `json` (cho log aggregator).

**Lưu ý**: `config/config.json` trong repo không chứa email/password; chỉ dùng `config.example.json` làm mẫu. Production đọc secret từ env qua `load_config.py`.

## 3. Cài đặt

```bash
cd C:\Users\dangt\.openclaw\workspace\skills\facebook-group-analyzer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Copy `config/config.example.json` thành `config/config.json` nếu chưa có; chỉnh `scraper`, `analysis`, `proxy` nếu cần. Không ghi email/password vào file.

## 4. Health check

Chạy trước khi schedule hoặc deploy:

```bash
python scripts/healthcheck.py
```

Exit 0 = sẵn sàng; non-zero = thiếu config/credential/deps. Session file thiếu chỉ cảnh báo (lần chạy đầu sẽ đăng nhập).

## 5. Chạy theo lịch (Data pipeline)

- **Danh sách group**: chỉnh `config/scheduled_groups.json` (thêm/bớt group, `days_back`, `max_posts`, `enabled`).
- **Chạy một lần** (toàn bộ group đã bật):

  ```cmd
  scripts\run_scheduled.cmd
  ```

  hoặc PowerShell:

  ```powershell
  .\scripts\run_scheduled.ps1
  ```

- **Lên lịch**:
  - **Windows**: Task Scheduler, trigger theo ngày/giờ; action: `scripts\run_scheduled.cmd`, start in: thư mục skill; set env `FB_EMAIL`, `FB_PASSWORD` trong task.
  - **OpenClaw cron**: thêm job gọi lệnh trên (ví dụ mỗi ngày 6h).

Sau mỗi lần chạy, dữ liệu nằm ở `data/posts/<group_id>.json`, báo cáo ở `data/reports/<group_id>_analysis.json`, export CSV ở `data/exports/`.

## 6. OpenClaw: cho agent chat chạy skill (AI Engineer)

Để agent trên chat (HTTP/Telegram) **tự chạy** lệnh `python main.py ...` khi user yêu cầu phân tích group:

1. Mở file cấu hình OpenClaw tại thư mục gốc OpenClaw (ví dụ `C:\Users\dangt\.openclaw\openclaw.json`).
2. Đổi **tools.profile** từ `messaging` sang **`full`** (hoặc profile có bật native/shell theo tài liệu OpenClaw):
   - Có thể tham khảo fragment trong `docs/openclaw-production-override.example.json`.
3. Khởi động lại gateway/agent.
4. Trong chat, thử: *"phân tích group 1125804114216204 trong 7 ngày"* — agent sẽ gọi skill và trả kết quả.

**Cảnh báo**: Profile `full` cho phép agent chạy lệnh trên máy; chỉ dùng trên môi trường tin cậy (local hoặc server nội bộ).

## 7. Log và giám sát

- Log ra stdout; mức và format điều khiển bởi `LOG_LEVEL`, `LOG_FORMAT`.
- Có thể pipe vào file hoặc log aggregator (ví dụ `LOG_FORMAT=json`).
- Lỗi scraper/analyze được ghi qua logger `storage`, `scraper`; exit code của `main.py` khác 0 khi lỗi.

## 8. Tóm tắt luồng production

| Bước | Công cụ / File | Ghi chú |
|------|----------------|--------|
| Secrets | `.env` hoặc env vars | `FB_EMAIL`, `FB_PASSWORD` |
| Config | `config/config.json` + env | Không commit secret |
| Cài đặt | `requirements.txt`, `playwright install chromium` | Pin version |
| Health check | `scripts/healthcheck.py` | Trước schedule/deploy |
| Pipeline theo lịch | `config/scheduled_groups.json` + `scripts/run_scheduled.*` | Scrape + analyze nhiều group |
| Agent chat | OpenClaw `tools.profile` = `full` | Để chat gọi `python main.py` |
