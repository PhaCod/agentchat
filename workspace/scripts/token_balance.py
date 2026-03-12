"""
token_balance.py — Aggregate token usage from OpenClaw session logs + skill ledger.

Usage (from workspace or OpenClaw root):
  python workspace/scripts/token_balance.py [--days 30] [--output docs/TOKEN_BALANCE_SHEET.md]

Reads:
- agents/main/sessions/*.jsonl — usage per LLM call (agent/embedded), infers tool/skill from exec args
- workspace/data/token_usage.jsonl — skill-side Gemini calls (fb-group-crawl ask, etc.)

Outputs:
- JSON summary to stdout (or --json path)
- Markdown balance sheet with 1-month extrapolation (--output).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _openclaw_root(workspace_dir: Path) -> Path:
    """Assume workspace is openclaw/workspace."""
    w = workspace_dir.resolve()
    if w.name == "workspace":
        return w.parent
    return w


def _parse_session_log(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        if not usage:
            continue
        inp = int(usage.get("input") or 0)
        out_tok = int(usage.get("output") or 0)
        total = int(usage.get("totalTokens") or (inp + out_tok))
        cost = (msg.get("usage") or {}).get("cost") or {}
        ts = obj.get("timestamp") or msg.get("timestamp") or ""
        # Infer tool/skill from content
        tool = "agent"
        content = msg.get("content") or []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "toolCall":
                name = c.get("name") or ""
                args = c.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if name == "exec":
                        cmd = args.get("command") or args.get("command_line") or ""
                        if "fb-group-crawl" in cmd:
                            tool = "skill:fb-group-crawl"
                        elif "facebook-group-analyzer" in cmd:
                            tool = "skill:facebook-group-analyzer"
                        elif "market-research" in cmd:
                            tool = "skill:market-research"
                        else:
                            tool = "exec"
                elif name:
                    tool = f"tool:{name}"
                break
        date = ts[:10] if len(ts) >= 10 else ""
        out.append({
            "date": date,
            "input": inp,
            "output": out_tok,
            "total": total,
            "cost_total": float(cost.get("total") or 0),
            "tool": tool,
            "model": msg.get("model") or "?",
        })
    return out


def _parse_ledger(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append({
            "date": r.get("date") or "",
            "skill": r.get("skill") or "?",
            "call": r.get("call") or "?",
            "input": int(r.get("input_tokens") or 0),
            "output": int(r.get("output_tokens") or 0),
            "total": int(r.get("total_tokens") or 0),
        })
    return out


def aggregate(
    sessions_dir: Path,
    ledger_path: Path,
    days: int = 30,
) -> dict:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    by_date = defaultdict(lambda: {"input": 0, "output": 0, "total": 0, "cost": 0.0, "by_tool": defaultdict(lambda: {"total": 0, "cost": 0.0})})
    by_tool = defaultdict(lambda: {"input": 0, "output": 0, "total": 0, "cost": 0.0})

    for jf in sessions_dir.glob("*.jsonl"):
        for row in _parse_session_log(jf):
            if row["date"] < cutoff:
                continue
            by_date[row["date"]]["input"] += row["input"]
            by_date[row["date"]]["output"] += row["output"]
            by_date[row["date"]]["total"] += row["total"]
            by_date[row["date"]]["cost"] += row.get("cost_total") or 0
            by_date[row["date"]]["by_tool"][row["tool"]]["total"] += row["total"]
            by_date[row["date"]]["by_tool"][row["tool"]]["cost"] += row.get("cost_total") or 0
            by_tool[row["tool"]]["input"] += row["input"]
            by_tool[row["tool"]]["output"] += row["output"]
            by_tool[row["tool"]]["total"] += row["total"]
            by_tool[row["tool"]]["cost"] += row.get("cost_total") or 0

    for row in _parse_ledger(ledger_path):
        if row["date"] < cutoff:
            continue
        tool = f"skill:{row['skill']}({row['call']})"
        by_date[row["date"]]["input"] += row["input"]
        by_date[row["date"]]["output"] += row["output"]
        by_date[row["date"]]["total"] += row["total"]
        by_date[row["date"]]["by_tool"][tool]["total"] += row["total"]
        by_tool[tool]["input"] += row["input"]
        by_tool[tool]["output"] += row["output"]
        by_tool[tool]["total"] += row["total"]

    total_input = sum(d["input"] for d in by_date.values())
    total_output = sum(d["output"] for d in by_date.values())
    total_tokens = sum(d["total"] for d in by_date.values())
    total_cost = sum(d["cost"] for d in by_date.values())

    def _serialize_date(d: dict) -> dict:
        out = {"input": d["input"], "output": d["output"], "total": d["total"], "cost": d["cost"]}
        out["by_tool"] = {tk: dict(tv) for tk, tv in d["by_tool"].items()}
        return out

    return {
        "period_days": days,
        "cutoff": cutoff,
        "by_date": {k: _serialize_date(v) for k, v in sorted(by_date.items())},
        "by_tool": {k: dict(v) for k, v in sorted(by_tool.items())},
        "totals": {
            "input": total_input,
            "output": total_output,
            "total": total_tokens,
            "cost": round(total_cost, 6),
        },
        "extrapolate_30d": {
            "total": int(total_tokens * (30 / max(1, len(by_date)))) if by_date else 0,
            "cost": round(total_cost * (30 / max(1, len(by_date))), 6) if by_date else 0,
        },
    }


def write_balance_sheet(data: dict, out_path: Path, openclaw_root: Path) -> None:
    t = data["totals"]
    ex = data["extrapolate_30d"]
    cost_display = max(0.0, t["cost"])
    ex_cost_display = max(0.0, ex["cost"])
    lines = [
        "# Token balance sheet — OpenClaw",
        "",
        f"*Tổng hợp từ session logs + skill ledger (trong {data['period_days']} ngày gần nhất, cutoff {data['cutoff']}).*",
        "",
        "## Tổng quan",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|--------|",
        f"| Tổng token (input) | {t['input']:,} |",
        f"| Tổng token (output) | {t['output']:,} |",
        f"| **Tổng token** | **{t['total']:,}** |",
        f"| Chi phí ước tính (USD) | ${cost_display:.6f} |",
        "",
        "## Ước lượng 1 tháng (30 ngày)",
        "",
        "Ngoại suy từ số ngày có dữ liệu (chỉ mang tính tham khảo):",
        "",
        "| Chỉ số | Ước lượng 30 ngày |",
        "|--------|-------------------|",
        f"| Tổng token | ~{ex['total']:,} |",
        f"| Chi phí (USD) | ~${ex_cost_display:.6f} |",
        "",
        "## Phân bổ theo nguồn (tool/skill)",
        "",
        "| Nguồn | Input | Output | Tổng token | Cost (USD) |",
        "|-------|-------|--------|------------|------------|",
    ]
    for tool, v in sorted(data["by_tool"].items()):
        c = max(0.0, v["cost"])
        lines.append(f"| {tool} | {v['input']:,} | {v['output']:,} | {v['total']:,} | {c:.6f} |")
    lines.extend([
        "",
        "## Ghi chú",
        "",
        "- **agent / tool:read / tool:exec**: Token từ embedded agent (Gemini qua gateway) khi trả lời user, đọc file, hoặc chạy lệnh.",
        "- **skill:fb-group-crawl**: Token khi skill gọi Gemini (lệnh `ask`) — ghi vào `workspace/data/token_usage.jsonl`.",
        "- Gemini free tier: thường giới hạn RPM (requests/min) và RPD; khi vượt sẽ 429. Chi phí paid: tham khảo https://ai.google.dev/pricing.",
        "- **So sánh phương pháp**: Nếu dùng OpenClaw ít tương tác (vài câu/ngày) thì token chủ yếu từ agent. Nếu tăng rag-query/market (ít gọi LLM) thì token skill giảm. Có thể so với: ChatGPT API, Claude, hoặc self-hosted model (Ollama) để ước lượng chi phí thay thế.",
        "",
        "## Cách chạy lại báo cáo",
        "",
        "Từ thư mục `workspace`:",
        "",
        "```bash",
        "python scripts/token_balance.py --days 30 --output docs/TOKEN_BALANCE_SHEET.md --json docs/token_summary.json",
        "```",
        "",
        "Hoặc từ OpenClaw root: `python workspace/scripts/token_balance.py --openclaw . --output workspace/docs/TOKEN_BALANCE_SHEET.md`",
        "",
    ])
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate OpenClaw token usage and write balance sheet")
    ap.add_argument("--openclaw", type=Path, default=None, help="OpenClaw root (default: parent of workspace)")
    ap.add_argument("--days", type=int, default=30, help="Days to aggregate")
    ap.add_argument("--output", type=Path, default=None, help="Write balance sheet Markdown here")
    ap.add_argument("--json", type=Path, default=None, help="Write full JSON summary here")
    args = ap.parse_args()

    if args.openclaw is None:
        # Assume script is in workspace/scripts
        script_dir = Path(__file__).resolve().parent
        workspace = script_dir.parent
        root = _openclaw_root(workspace)
    else:
        root = Path(args.openclaw)
        workspace = root / "workspace"

    sessions_dir = root / "agents" / "main" / "sessions"
    ledger_path = workspace / "data" / "token_usage.jsonl"

    if not sessions_dir.exists():
        print("Sessions dir not found:", sessions_dir)
        return

    data = aggregate(sessions_dir, ledger_path, days=args.days)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote JSON to", args.json)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_balance_sheet(data, args.output, root)
        print("Wrote balance sheet to", args.output)

    if not args.json and not args.output:
        print(json.dumps(data["totals"], ensure_ascii=False, indent=2))
        print("Extrapolate 30d:", data["extrapolate_30d"])


if __name__ == "__main__":
    main()
