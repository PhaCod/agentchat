# OpenClaw — Báo cáo Vai trò & Hướng Triển khai Product

---

## 1. OpenClaw là gì?

OpenClaw là một **AI agent framework** cho phép deploy agent AI tự trị (autonomous agent) chạy liên tục trên máy cục bộ hoặc server. Khác với chatbot thông thường chỉ trả lời trong session, OpenClaw tạo ra một agent có:

- **Danh tính bền vững** — personality, giá trị cốt lõi (SOUL.md), không thay đổi giữa các session
- **Bộ nhớ dài hạn** — ghi nhận, tóm lược qua thời gian (MEMORY.md + daily logs)
- **Khả năng thực thi** — chạy shell commands, gọi external tools, tự động hóa pipeline
- **Nhiều kênh giao tiếp** — Telegram bot, HTTP gateway, CLI
- **Skill registry** — gắn thêm công cụ chuyên biệt (scraper, analyzer, v.v.) theo dạng plugin

> Một câu: **OpenClaw biến LLM thành một nhân viên AI luôn online, có trí nhớ, và có thể thao tác máy tính thay người dùng.**

---

## 2. Vai trò hiện tại trong hệ sinh thái

### 2.1 Lớp kiến trúc

```
┌─────────────────────────────────────────────────────────┐
│                     User (Telegram / HTTP)               │
└──────────────────────────┬──────────────────────────────┘
                           │ tin nhắn tự nhiên (tiếng Việt)
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   OpenClaw Agent (Claw)                  │
│                                                         │
│  SOUL.md        — personality & core values             │
│  IDENTITY.md    — Name: Claw 🦞, role: data engineering  │
│  USER.md        — context về người dùng (Peter Dang)    │
│  MEMORY.md      — kiến thức tích lũy qua thời gian      │
│  TOOLS.md       — setup notes, paths, accounts          │
│                                                         │
│  Model: Google Gemini 2.5 Flash (primary)               │
└──────────────────────────┬──────────────────────────────┘
                           │ gọi skill / chạy command
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      Skill Registry                      │
│                                                         │
│  facebook-group-analyzer  — scrape + analyze FB groups  │
│  facebook-scraper          — discover pages & groups    │
│  (... skills mới có thể thêm vào)                       │
└──────────────────────────┬──────────────────────────────┘
                           │ đọc file output
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      Data Layer                          │
│                                                         │
│  data/posts/     — raw Facebook posts (JSON)            │
│  data/reports/   — analysis results (JSON)              │
│  data/exports/   — CSV outreach files                   │
│  data/runs/      — run audit trail                      │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Luồng hoạt động điển hình

```
Peter: "lấy 20 bài mới nhất group riviu rồi cho tao xem pain points"
    ↓
Claw: Nhận Telegram message
    ↓
Claw: Đọc SKILL.md → maps → python main.py full --group URL --days 1 --max-posts 20
    ↓
Claw: Chạy command → đọc data/reports/riviu.official_analysis.json
    ↓
Claw: Parse pain_points, tóm tắt bằng tiếng Việt → trả về Telegram
```

### 2.3 Công cụ đang hoạt động

| Skill | Trạng thái | Chức năng chính |
|-------|-----------|-----------------|
| `facebook-group-analyzer` | ✅ Production | 5 objectives: pain points, leads, crisis, competitor SOV, NL queries |
| `facebook-scraper` | 🔧 Beta | Discover pages/groups theo địa điểm + category |

### 2.4 Channels đang active

| Channel | Trạng thái | Ghi chú |
|---------|-----------|---------|
| Telegram bot | ✅ Enabled | Pairing mode, streaming partial |
| HTTP Gateway | ✅ Localhost | Port 18789, token auth |
| Tailscale | ⬜ Off | Có thể bật cho remote access |

---

## 3. Điểm mạnh hiện tại

**Kỹ thuật:**
- Incremental scraping với cursor — không scrape lại bài đã có
- Gemini cache bằng MD5 hash — không tốn API quota khi dữ liệu không đổi
- Atomic writes (tmp + os.replace) — không bao giờ corrupt file
- SQLite full-text index — query nhanh trong 500+ bài
- APScheduler fallback loop — chạy được ngay cả khi không có daemon

**Nghiệp vụ:**
- Rule-based NLP tiếng Việt không cần model riêng
- 5 objectives coverage trong 1 lần analyze
- Export CSV sẵn sàng cho outreach workflow
- Telegram alerts tích hợp sẵn khi có crisis

**Agent:**
- Memory layer cho phép Claw nhớ context giữa các session
- Tool profile "full" cho phép execute bất kỳ command nào
- Compaction mode "safeguard" giữ nguyên context quan trọng

---

## 4. Giới hạn & rủi ro hiện tại

| Vấn đề | Chi tiết | Mức độ |
|--------|---------|--------|
| **Facebook anti-bot** | Playwright headless có thể bị detect, cần session login thủ công | Cao |
| **Gemini quota** | Free tier giới hạn calls/day; nếu vượt thì mất ai_insights | Trung bình |
| **Author data sparse** | Scraper chưa lấy được author_id đáng tin cậy, ảnh hưởng lead outreach | Trung bình |
| **Windows encoding** | Stdout tiếng Việt bị lỗi cp1252; phải đọc file thay vì parse stdout | Thấp (đã có workaround) |
| **Single-node** | Toàn bộ chạy trên 1 máy, không có redundancy | Thấp (phù hợp use case cá nhân) |
| **No hot reload** | Thay đổi config cần restart agent | Thấp |

---

## 5. Hướng triển khai product

### Giai đoạn 1 — Hoàn thiện nền tảng (hiện tại)

**Mục tiêu:** Ổn định pipeline Facebook Group Analyzer, đủ tin cậy để dùng hàng ngày.

- [x] 5 business objectives implemented & tested
- [x] Incremental scraping, Gemini cache
- [x] Crisis monitor + Telegram alerts
- [x] Leads CSV export cho outreach
- [x] SKILL.md + README đầy đủ cho agent routing
- [ ] **Tiếp theo:** Cải thiện author extraction để leads CSV có đủ thông tin liên hệ
- [ ] **Tiếp theo:** Thêm `facebook-scraper` skill vào agent routing (SKILL.md chưa đầy đủ)

### Giai đoạn 2 — Mở rộng data sources

**Mục tiêu:** Không chỉ Facebook group, mà nhiều nguồn dữ liệu xã hội hơn.

```
Skill hiện tại:          Skill cần thêm:
facebook-group-analyzer  → tiktok-comment-analyzer
facebook-scraper         → shopee-review-analyzer
                         → zalo-group-analyzer
                         → youtube-comment-analyzer
```

Mỗi skill mới theo cùng pattern:
- `main.py` với `scrape` / `analyze` / `report` subcommands
- Output JSON cùng schema (pain_points, leads, sentiment)
- SKILL.md cho agent routing
- Gemini AI integration

### Giai đoạn 3 — Cross-platform Intelligence

**Mục tiêu:** Agent có thể tổng hợp insight từ nhiều platform cùng lúc.

```
Peter: "nói cho tao biết người dùng đang nói gì về X trên tất cả nền tảng"
    ↓
Claw orchestrates:
  facebook-group-analyzer → pain_points về X
  tiktok-comment-analyzer → sentiment về X
  shopee-review-analyzer  → review về X
    ↓
Claw: Tổng hợp + cross-reference → báo cáo unified
```

**Yêu cầu kỹ thuật:**
- Unified report schema cross-skill
- Claw sub-agent orchestration (maxConcurrent: 8 đã sẵn sàng)
- Shared competitor config per project

### Giai đoạn 4 — Productization & SaaS

**Mục tiêu:** Từ tool cá nhân → sản phẩm có thể scale cho nhiều user.

**Mô hình:**

```
┌─────────────────────────────────────────────────┐
│              ScrapeClaw Platform                 │
│                                                 │
│  Web Dashboard  ←→  OpenClaw Agent Pool         │
│                        ↓                        │
│  User A → Agent A → skill set A (FB groups)     │
│  User B → Agent B → skill set B (Shopee)        │
│  User C → Agent C → skill set A+B+C             │
│                        ↓                        │
│              Shared Skill Registry               │
│         (versioned, updatable, marketplace)      │
└─────────────────────────────────────────────────┘
```

**Differentiator so với SaaS analytics thông thường:**
1. **Agent-native** — không chỉ dashboard, mà AI biết ngữ cảnh, trả lời câu hỏi tự nhiên
2. **Vietnam-first** — NLP tiếng Việt, Vietnamese commerce signals, local platforms (Zalo, Shopee)
3. **No API key required** — scrape trực tiếp, không phụ thuộc Facebook/TikTok API
4. **Skill marketplace** — community có thể đóng góp skills (pattern đã có: author field trong _meta.json)

### Giai đoạn 5 — Agent Autonomy

**Mục tiêu:** Agent chủ động theo dõi, không chờ người dùng hỏi.

```
Scheduled jobs (cron/jobs.json):
  Mỗi 6 giờ  → run full pipeline cho tất cả groups
  Mỗi ngày   → gửi morning briefing qua Telegram
  Real-time  → push alert ngay khi phát hiện crisis
  Weekly     → tổng hợp weekly report + gợi ý action items
```

**HEARTBEAT.md** — file đã có sẵn trong workspace, chờ được điền nội dung:
```markdown
# Heartbeat tasks
- [ ] Daily: run facebook-group-analyzer cho tracked groups
- [ ] Weekly: cross-platform summary report
- [ ] On crisis: alert + summarize + suggest response
```

---

## 6. Định vị product

| Dimension | Hiện tại | Mục tiêu |
|-----------|---------|----------|
| **User** | 1 person (Peter) | Teams, brands, agencies |
| **Data sources** | Facebook Groups | Facebook + TikTok + Shopee + Zalo |
| **Interface** | Telegram + CLI | Telegram + Web Dashboard |
| **Intelligence** | Rule-based + Gemini | Rule-based + Multiple LLMs + Fine-tuned Vietnamese model |
| **Deployment** | Local machine | Cloud (single-tenant per user) |
| **Skill count** | 2 | Marketplace (community + official) |

---

## 7. Tóm tắt

OpenClaw không phải là một analytics tool — nó là **infrastructure để deploy AI agents biết làm việc**. Facebook Group Analyzer là skill đầu tiên chứng minh pattern này hoạt động tốt:

- Agent nhận yêu cầu tự nhiên bằng tiếng Việt
- Map sang command và chạy skill
- Đọc kết quả, tổng hợp, trả về insight có giá trị

Hướng đi tiếp theo là **nhân rộng pattern này** sang nhiều data sources, nhiều skill, và cuối cùng là một agent có thể tự chủ theo dõi và báo cáo mà không cần được hỏi — giống như một nhân viên nghiên cứu thị trường làm việc 24/7.

---

*Tạo ngày: 2026-03-05*
*Dựa trên: codebase tại `C:\Users\dangt\.openclaw\workspace\skills\`*
