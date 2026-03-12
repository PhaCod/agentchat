# Token balance sheet — OpenClaw

*Tổng hợp từ session logs + skill ledger (trong 30 ngày gần nhất, cutoff 2026-02-10).*

## Tổng quan

| Chỉ số | Giá trị |
|--------|--------|
| Tổng token (input) | 4,389,192 |
| Tổng token (output) | 49,668 |
| **Tổng token** | **4,635,084** |
| Chi phí ước tính (USD) | $0.000000 |

## Ước lượng 1 tháng (30 ngày)

Ngoại suy từ số ngày có dữ liệu (chỉ mang tính tham khảo):

| Chỉ số | Ước lượng 30 ngày |
|--------|-------------------|
| Tổng token | ~23,175,420 |
| Chi phí (USD) | ~$0.000000 |

## Phân bổ theo nguồn (tool/skill)

| Nguồn | Input | Output | Tổng token | Cost (USD) |
|-------|-------|--------|------------|------------|
| agent | 2,071,845 | 36,094 | 2,304,163 | 0.000000 |
| exec | 131,965 | 1,945 | 133,910 | 0.044623 |
| skill:facebook-group-analyzer | 802,178 | 6,455 | 808,633 | 0.283892 |
| skill:market-research | 67,077 | 172 | 67,249 | 0.025383 |
| tool:process | 844,288 | 1,873 | 846,161 | 0.271270 |
| tool:read | 411,208 | 2,772 | 413,980 | 0.144966 |
| tool:session_status | 39,821 | 51 | 39,872 | 0.012074 |
| tool:web_search | 20,810 | 306 | 21,116 | 0.007008 |

## Ghi chú

- **agent / tool:read / tool:exec**: Token từ embedded agent (Gemini qua gateway) khi trả lời user, đọc file, hoặc chạy lệnh.
- **skill:fb-group-crawl**: Token khi skill gọi Gemini (lệnh `ask`) — ghi vào `workspace/data/token_usage.jsonl`.
- Gemini free tier: thường giới hạn RPM (requests/min) và RPD; khi vượt sẽ 429. Chi phí paid: tham khảo https://ai.google.dev/pricing.
- **So sánh phương pháp**: Nếu dùng OpenClaw ít tương tác (vài câu/ngày) thì token chủ yếu từ agent. Nếu tăng rag-query/market (ít gọi LLM) thì token skill giảm. Có thể so với: ChatGPT API, Claude, hoặc self-hosted model (Ollama) để ước lượng chi phí thay thế.

## Cách chạy lại báo cáo

Từ thư mục `workspace`:

```bash
python scripts/token_balance.py --days 30 --output docs/TOKEN_BALANCE_SHEET.md --json docs/token_summary.json
```

Hoặc từ OpenClaw root: `python workspace/scripts/token_balance.py --openclaw . --output workspace/docs/TOKEN_BALANCE_SHEET.md`
