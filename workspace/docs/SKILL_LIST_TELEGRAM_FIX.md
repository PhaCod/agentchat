# Vì sao skill workspace không hiện trong Telegram và cách xử lý

## Nguyên nhân

1. **Danh sách skill bot trả về** khi user hỏi "bạn có skill gì" **không** được tạo bằng cách đọc thư mục `workspace/skills/` mỗi lần. Nó lấy từ **skillsSnapshot** của session, được lưu trong `agents/main/sessions/sessions.json`.

2. **skillsSnapshot** được tạo **một lần** khi session được tạo hoặc khi OpenClaw quét skill (bundled + workspace). Chỉ những skill **đã có trong snapshot** mới nằm trong block `<available_skills>` mà agent nhìn thấy. Skill bạn thêm sau vào `workspace/skills/` (vd. facebook-group-analyzer, market-research) sẽ **không** tự động vào snapshot.

3. **Chỉnh AGENTS.md** (dặn agent “khi hỏi list skills thì liệt kê thêm workspace skills”) **không đủ** vì:
   - Nội dung AGENTS.md được **inject vào system prompt một lần** lúc build (field `systemPromptReport.generatedAt`). Chỉnh file sau đó không được đọc lại cho đến khi system prompt được build lại (vd. session mới hoặc refresh).

## Cách đã xử lý

Đã **thêm trực tiếp** hai skill workspace vào **skillsSnapshot** của session Telegram (và session webchat) trong `agents/main/sessions/sessions.json`:

- **facebook-group-analyzer** — mô tả và đường dẫn SKILL.md
- **market-research** — mô tả và đường dẫn SKILL.md

Cụ thể đã sửa cho session `agent:main:telegram:direct:5787031195` và `agent:main:main`:

- Trong `skillsSnapshot.prompt`: thêm hai block `<skill>...</skill>` vào `<available_skills>`.
- Trong `skillsSnapshot.skills`: thêm hai entry `{ "name": "facebook-group-analyzer" }`, `{ "name": "market-research" }`.
- Trong `skillsSnapshot.resolvedSkills`: thêm hai object đầy đủ (name, description, filePath, baseDir, source: "openclaw-workspace").

## Bạn cần làm gì

1. **Restart OpenClaw daemon** (nếu đang chạy) để nó đọc lại `sessions.json` với snapshot mới. Nếu daemon tự load lại session mỗi request thì có thể không cần restart.

2. Trong Telegram, **gửi lại**: *"bạn có skill gì"* → bot sẽ liệt kê **7 skill**: clawhub, healthcheck, skill-creator, weather, goodreads, **facebook-group-analyzer**, **market-research**.

## Thêm skill workspace mới sau này

Mỗi khi bạn thêm một skill mới vào `workspace/skills/<tên-skill>/` (có `SKILL.md`), để nó **hiện trong danh sách** khi user hỏi "bạn có skill gì", cần **một trong hai**:

- **Cách 1 (thủ công):** Sửa `agents/main/sessions/sessions.json` cho từng session (Telegram, webchat): thêm vào `skillsSnapshot.prompt` (block `<skill>`), `skillsSnapshot.skills`, và `skillsSnapshot.resolvedSkills` theo đúng format như goodreads/facebook-group-analyzer.
- **Cách 2 (tự động):** Dùng tính năng của OpenClaw (nếu có) để **refresh / sync skills** (vd. lệnh hoặc UI “rescan workspace skills”) để snapshot được build lại và đưa tất cả folder trong `workspace/skills/` có SKILL.md vào snapshot. Xem tài liệu hoặc release note OpenClaw.

File này nằm tại `workspace/docs/SKILL_LIST_TELEGRAM_FIX.md`.
