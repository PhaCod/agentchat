# Sử dụng skill qua Telegram chat

Hướng dẫn cách dùng các skill (Goodreads, Facebook Group Analyzer, Market Research…) **trực tiếp trong Telegram** — chat với bot, agent sẽ gọi skill và trả kết quả.

---

## 1. Điều kiện (một lần)

### 1.1. OpenClaw daemon đang chạy

Agent chạy trong process OpenClaw. Cần khởi động daemon (CLI cài global):

```powershell
openclaw start
# hoặc theo hướng dẫn cài OpenClaw (npx / npm ...)
```

Khi chạy, daemon sẽ:

- Đọc `openclaw.json` (gateway port 18789, Telegram bot token).
- Load workspace `C:\Users\dangt\.openclaw\workspace` và agent `main`.
- Kết nối Telegram qua `botToken` trong `channels.telegram`.

### 1.2. Telegram bot đã kết nối

Trong `openclaw.json` đã có:

```json
"channels": {
  "telegram": {
    "enabled": true,
    "botToken": "8799101696:AAE...",
    "dmPolicy": "pairing",
    "groupPolicy": "open"
  }
}
```

- **DM (chat riêng):** Mở Telegram → tìm bot (tên bot do bạn đặt khi tạo Bot với @BotFather) → bắt đầu chat.
- **Group:** Thêm bot vào group; với `groupPolicy: "open"` bot có thể đọc/trả lời trong group (tuỳ cấu hình có thể chỉ trả lời khi được mention).

### 1.3. Agent biết dùng skill

Agent đọc **TOOLS.md** và **SKILL.md** của từng skill. Trong workspace đã có:

- **TOOLS.md** — ghi rõ lệnh chạy Goodreads, Facebook Group Analyzer, Market Research.
- **AGENTS.md** — dặn agent: *"Skills provide your tools. When you need one, check its SKILL.md. Keep local notes in TOOLS.md."*

Không cần “đăng ký” skill riêng — chỉ cần file trong `workspace\skills\` và mô tả trong TOOLS.md.

---

## 2. Cách dùng trên Telegram

Bạn **chat với bot như bình thường**. Nói rõ việc cần làm (sách, group FB, nghiên cứu thị trường…), agent sẽ tự chạy lệnh phù hợp và trả lời.

### Goodreads

| Bạn nói (ví dụ) | Agent sẽ (gợi ý) |
|-----------------|-------------------|
| "Tôi đang đọc sách gì?" / "What am I currently reading?" | Chạy `goodreads-rss.py shelf <USER_ID> --shelf currently-reading` → trả danh sách sách đang đọc. |
| "Tìm sách atomic habits" | Chạy `goodreads-rss.py search "atomic habits" --limit 5` → trả link + tên sách. |
| "Chi tiết sách [book_id]" | Chạy `goodreads-rss.py book <book_id>`. |
| "Đánh giá 5 sao cho sách 40121378" | Chạy `goodreads-writer.py rate 40121378 5` (cần đã login Goodreads một lần). |

**Lưu ý:** Để agent biết Goodreads user ID của bạn, nên ghi trong **TOOLS.md** (hoặc MEMORY.md) một dòng kiểu:  
`Goodreads user ID: 12345678`  
hoặc set env `GOODREADS_USER_ID` khi chạy daemon.

### Facebook Group Analyzer

| Bạn nói (ví dụ) | Agent sẽ (gợi ý) |
|-----------------|-------------------|
| "Phân tích group FB 1125804114216204" / "tóm tắt group" | Chạy `python main.py report --group 1125804114216204 --type summary --output json` (từ thư mục skill). |
| "Scrape 20 bài mới nhất group đó" | Chạy `python main.py scrape --group "https://www.facebook.com/groups/1125804114216204" --max-posts 20 --output json`. |
| "Sentiment / cảm xúc group" | Chạy `python main.py report --group 1125804114216204 --type sentiment --output json`. |

### Market Research

| Bạn nói (ví dụ) | Agent sẽ (gợi ý) |
|-----------------|-------------------|
| "Nghiên cứu thị trường về [chủ đề]" | Chạy `python main.py research --topic "..." --sources web,tiktok --output json` (từ thư mục market-research). |

---

## 3. Luồng kỹ thuật (tích hợp đã có sẵn)

```
Bạn gửi tin nhắn Telegram
        ↓
Telegram server → OpenClaw gateway (port 18789, webhook/polling)
        ↓
Gateway map tin nhắn → session agent "main" (workspace của bạn)
        ↓
Agent nhận nội dung + context (AGENTS.md, TOOLS.md, SOUL.md, USER.md…)
        ↓
Agent quyết định gọi skill → dùng tool "exec" chạy lệnh (vd: python goodreads-rss.py ...)
        ↓
Lệnh chạy trong thư mục skill (workspace\skills\goodreads\scripts hoặc facebook-group-analyzer)
        ↓
Kết quả (JSON/text) trả về agent → agent tóm tắt/format lại
        ↓
Agent gửi trả lời qua gateway → Telegram → bạn thấy trong chat
```

Bạn **không cần** cấu hình thêm tích hợp Telegram cho từng skill — chỉ cần daemon bật, bot Telegram đã kết nối, và TOOLS.md mô tả đúng lệnh.

---

## 4. Nếu agent không gọi đúng skill

- **Kiểm tra TOOLS.md**  
  Đảm bảo có mục tương ứng (Goodreads, Facebook Group Analyzer…) và **lệnh chạy chính xác** (đường dẫn, thư mục, `python` vs `python3`).

- **Gợi ý rõ hơn trong lời nhắn**  
  Ví dụ: *"Dùng skill Goodreads xem shelf currently-reading giúp tôi"* hoặc *"Chạy report summary cho group FB 1125804114216204"*.

- **Goodreads user ID**  
  Nếu agent báo thiếu user ID, thêm vào TOOLS.md:  
  `Goodreads user ID (for shelf/activity): 12345678`

- **Lệnh ghi Goodreads (rate, shelf, review)**  
  Chỉ chạy được sau khi đã login một lần trên máy (chạy `python goodreads-writer.py login` trong `workspace\skills\goodreads\scripts`). Session lưu vài tuần.

---

## 5. Tóm tắt

| Bước | Việc cần làm |
|------|----------------|
| 1 | Chạy OpenClaw daemon (`openclaw start` hoặc tương đương). |
| 2 | Mở Telegram → chat với bot (DM hoặc group đã thêm bot). |
| 3 | Gửi yêu cầu bằng ngôn ngữ tự nhiên (sách, group FB, research…). |
| 4 | Agent đọc TOOLS.md → chạy lệnh skill → trả kết quả trong chat. |

Skill đã nằm trong `workspace\skills\` và đã được mô tả trong **TOOLS.md** — tích hợp Telegram chính là **chat với bot**, agent sẽ tự dùng skill khi phù hợp.

---

## Skill workspace không hiện trong danh sách "bạn có skill gì"?

Danh sách skill bot trả về khi bạn hỏi **"bạn có skill gì"** lấy từ **skillsSnapshot** của session (skill bundled + skill trong workspace đã được OpenClaw quét lúc tạo session). Skill bạn tự thêm vào `workspace\skills\` (vd. **facebook-group-analyzer**, **market-research**) có thể chưa nằm trong snapshot nên không hiện.

**Đã xử lý:** Trong **AGENTS.md** đã thêm quy tắc: khi user hỏi "bạn có skill gì" / "what skills do you have", agent **bắt buộc** liệt kê cả skill trong snapshot **và** các skill workspace (facebook-group-analyzer, market-research, …) theo mô tả trong TOOLS.md. Bạn chỉ cần **hỏi lại** trong Telegram (vd. "bạn có skill gì") hoặc **bắt đầu đoạn chat mới** — bot sẽ trả lời đủ danh sách kèm skill workspace.

**Nếu vẫn thiếu:** Kiểm tra trong AGENTS.md có đoạn *"When the user asks ... list your skills"* và mục workspace skills. Có thể restart OpenClaw daemon rồi mở lại chat Telegram để session refresh snapshot (tuỳ phiên bản OpenClaw).
