# Crawl logic: đăng nhập và timestamp

## 1. Đăng nhập (session)

- **Session file** (cookie lưu để không đăng nhập lại mỗi lần):
  - Ưu tiên: `workspace/skills/facebook-group-analyzer/sessions/fb_session.json`
  - Nếu không có: dùng **workspace/sessions/fb_session.json** (fallback)
- **Khi nào cần đăng nhập lại:**
  - Chưa có file session, hoặc
  - Facebook redirect về trang login (`login` / `checkpoint` trong URL), hoặc
  - Trên trang group xuất hiện **modal "See more on Facebook"** (form email/password, nút Log in).
- **Khi phát hiện cần login:** scraper xóa session cũ, gọi form login (email + password), sau đó lưu session mới.
- **Điều kiện để tự đăng nhập:** phải có **FB_EMAIL** và **FB_PASSWORD** (trong `.env` của skill hoặc biến môi trường). Nếu không có, scraper báo lỗi và không crawl được.

**Cách cấu hình khi chạy từ agent/Telegram:**  
Đặt `FB_EMAIL` và `FB_PASSWORD` trong file `workspace/skills/facebook-group-analyzer/.env` (không commit file này). Hoặc cấu hình env trên máy chạy OpenClaw để khi gọi `exec` đã có sẵn hai biến này.

## 2. Timestamp (mốc thời gian bài đăng)

- **Chỉ khi đã đăng nhập** Facebook mới trả về DOM đầy đủ (link bài, aria-label, data-utime). Nếu chưa login hoặc bị vướng modal, hầu hết bài sẽ **không có timestamp**.
- Scraper thử **5 cách** lấy thời gian (theo thứ tự):
  1. Thuộc tính `data-utime` trên thẻ `abbr` / element (Unix time).
  2. `aria-label` trên link bài (permalink) — thường là "2 giờ" / "March 4, 2026 at 9:30 AM".
  3. Text trong các thẻ `abbr`, `span`, link gần bài.
  4. Quét toàn bộ span/abbr trong bài bằng JS, tìm chuỗi giống thời gian (phút, giờ, ngày, tuần, tháng, yesterday, just now, …).
  5. Bất kỳ element nào có `[data-utime]` trong cây DOM của bài.
- Nếu vẫn không có: trường **timestamp** để trống; mỗi bài vẫn có **scraped_at** (thời điểm crawl) trong JSON.
- **Kết luận:** Muốn có timestamp đầy đủ thì **bắt buộc phải đăng nhập thành công** (session hợp lệ hoặc re-login bằng FB_EMAIL/FB_PASSWORD). Sau khi fix login và modal "See more on Facebook", chạy lại scrape; timestamp sẽ có nhiều hơn.

## 3. Thứ tự crawl (tư duy khi crawl)

- Vào group với URL có `?sorting_setting=CHRONOLOGICAL` (bài mới nhất trước).
- Cuộn trang (scroll), thu thập lần lượt các `div[role='article']` **top-level** (không lấy bài là comment).
- Dừng khi: đủ **max_posts** hoặc vượt **days_back** (nếu có timestamp) hoặc không thêm bài mới sau vài lần cuộn.
