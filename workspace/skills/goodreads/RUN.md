# Goodreads Skill — Hướng dẫn chạy (Windows / OpenClaw)

Skill này được cài từ repo [phuc-nt/openclaw-skills](https://github.com/phuc-nt/openclaw-skills), nằm tại:

- **Thư mục skill:** `C:\Users\dangt\.openclaw\workspace\skills\goodreads`

---

## 1. Cài đặt (một lần)

### 1.1. Dependencies

Mở terminal, vào thư mục skill (hoặc `scripts`):

```powershell
cd C:\Users\dangt\.openclaw\workspace\skills\goodreads\scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install playwright playwright-stealth
playwright install chromium
```

### 1.2. Đăng nhập Goodreads (cho lệnh ghi: rate, shelf, review…)

Chỉ cần làm **một lần**; session lưu vài tuần–vài tháng.

```powershell
cd C:\Users\dangt\.openclaw\workspace\skills\goodreads\scripts
.\.venv\Scripts\Activate.ps1
python goodreads-writer.py login
```

Trình duyệt Chromium sẽ mở → đăng nhập Goodreads (Amazon/email) → khi thấy trang chủ Goodreads, quay lại terminal và nhấn Enter.

### 1.3. (Tuỳ chọn) User ID cho xác minh RSS

Để lệnh shelf/start/finish tự xác minh qua RSS:

```powershell
$env:GOODREADS_USER_ID = "12345678"
```

Lấy ID từ URL profile: `goodreads.com/user/show/12345678-yourname` → số là `12345678`.

---

## 2. Cách chạy

**Quan trọng:** Mọi lệnh chạy từ thư mục **`scripts`** (hoặc đảm bảo `python` tìm được `goodreads-rss.py` / `goodreads-writer.py`).

### 2.1. Lệnh đọc (RSS + scraping, không cần login)

| Lệnh | Ví dụ |
|------|--------|
| Xem shelf | `python goodreads-rss.py shelf <USER_ID> --shelf currently-reading` |
| Shelf "đã đọc" | `python goodreads-rss.py shelf <USER_ID> --shelf read --limit 20 --sort date_read` |
| Tìm sách | `python goodreads-rss.py search "atomic habits" --limit 5` |
| Chi tiết sách | `python goodreads-rss.py book <book_id>` |
| Review sách | `python goodreads-rss.py reviews <book_id> --limit 10` |
| Hoạt động gần đây | `python goodreads-rss.py activity <USER_ID> --limit 20` |

Thay `<USER_ID>` bằng Goodreads user ID của bạn; `<book_id>` lấy từ kết quả search/shelf.

### 2.2. Lệnh ghi (cần đã login)

Dùng **wrapper Windows** (trong `scripts`):

```powershell
cd C:\Users\dangt\.openclaw\workspace\skills\goodreads\scripts
.\goodreads-write.bat status
.\goodreads-write.bat rate 40121378 5
.\goodreads-write.bat shelf 186190 read
.\goodreads-write.bat start 40121378
.\goodreads-write.bat finish 186190
.\goodreads-write.bat review 186190 "Great book."
.\goodreads-write.bat edit 186190 --stars 4 --start-date 2025-03-01 --end-date 2025-03-08
.\goodreads-write.bat progress 13618551 150
```

Hoặc gọi Python trực tiếp (sau khi activate venv):

```powershell
python goodreads-writer.py rate 40121378 5
python goodreads-writer.py shelf 186190 read
# ...
```

---

## 3. Chạy từ Agent OpenClaw (Telegram / Webchat)

Agent có thể gọi skill qua tool `exec`. Trong **TOOLS.md** (workspace) nên có đoạn tương tự:

```markdown
## Goodreads

- **Skill dir:** `C:\Users\dangt\.openclaw\workspace\skills\goodreads`
- **Chạy từ thư mục:** `workspace\skills\goodreads\scripts`
- **Đọc (RSS):** `python goodreads-rss.py shelf <USER_ID> --shelf read --limit 20`
- **Tìm sách:** `python goodreads-rss.py search "tên sách" --limit 5`
- **Ghi (sau khi đã login):** `python goodreads-writer.py rate <book_id> 5` hoặc `goodreads-write.bat rate <book_id> 5`
```

User có thể nói: *"Tôi đang đọc sách gì?"* → agent chạy `goodreads-rss.py shelf <USER_ID> --shelf currently-reading` và trả lời.

---

## 4. Cài skill từ repo (nhắc lại)

```powershell
# Clone repo
git clone https://github.com/phuc-nt/openclaw-skills.git C:\Users\dangt\.openclaw\tmp-openclaw-skills

# Cài cho workspace hiện tại (tất cả agent dùng chung workspace)
Copy-Item -Path "C:\Users\dangt\.openclaw\tmp-openclaw-skills\goodreads" -Destination "C:\Users\dangt\.openclaw\workspace\skills\goodreads" -Recurse -Force

# (Tuỳ chọn) Cài global — thư mục skills chung của OpenClaw
# Copy-Item -Path "C:\Users\dangt\.openclaw\tmp-openclaw-skills\goodreads" -Destination "C:\Users\dangt\.openclaw\skills\goodreads" -Recurse -Force
```

Cấu trúc OpenClaw trên máy bạn:

- **Per-workspace (đang dùng):** `C:\Users\dangt\.openclaw\workspace\skills\goodreads`  
  → Mọi agent dùng workspace này đều gọi được skill.
- **Global:** `C:\Users\dangt\.openclaw\skills\goodreads`  
  → Nếu tồn tại thư mục `C:\Users\dangt\.openclaw\skills`, copy vào đó thì mọi workspace/agent có thể dùng.

---

## 5. Xử lý lỗi nhanh

| Lỗi | Cách xử lý |
|-----|------------|
| Session hết hạn | Chạy lại `python goodreads-writer.py login` |
| 403 / Access Denied | Chờ vài phút; kiểm tra đã cài `playwright-stealth` |
| Chromium not found | Trong venv: `playwright install chromium` |
| Selector not found | Goodreads đổi giao diện; kiểm tra thủ công hoặc mở issue trên GitHub |

Chi tiết setup đầy đủ: `references/SETUP.md`. Lệnh chi tiết: `SKILL.md`.
