"""
monitor.py — Objective 3: Crisis Management & Real-time Alerts.

Polling-based monitor that periodically re-analyzes stored posts to detect:
  - Negative sentiment spikes
  - Viral post eruptions (reaction surge)
  - Keyword crisis signals (e.g. "lừa đảo", "scam", "tẩy chay")

When a threshold is breached, sends alerts via:
  - Telegram (if configured)
  - Console (always)

Usage:
    python monitor.py --group 1125804114216204 --interval 300
    python monitor.py --group 1125804114216204 --interval 60 --telegram

Config (config.json):
    "crisis": {
        "negative_pct_threshold": 15,
        "viral_reactions_threshold": 500,
        "crisis_keywords": ["lừa đảo", "scam", "tẩy chay", "boycott", "kiện"]
    },
    "telegram": {
        "token": "YOUR_BOT_TOKEN",
        "chat_id": "@yourchannel_or_chat_id"
    }
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_log = logging.getLogger(__name__)

# Default crisis thresholds
_DEFAULT_NEG_THRESHOLD = 15      # % negative posts
_DEFAULT_VIRAL_THRESHOLD = 500   # reactions for viral detection
_DEFAULT_CRISIS_KEYWORDS = [
    "lừa đảo", "scam", "tẩy chay", "boycott", "kiện",
    "tố cáo", "cảnh báo khẩn", "nguy hiểm", "độc hại",
    "gian lận", "vi phạm", "báo công an",
]


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _send_telegram(token: str, chat_id: str, message: str) -> bool:
    """Send alert via Telegram Bot API. Returns True on success."""
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
        req = urllib.request.Request(
            url,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        _log.warning("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Alert detection
# ---------------------------------------------------------------------------

def _check_negative_spike(report: dict, threshold: float) -> dict | None:
    """Return alert dict if negative sentiment > threshold, else None."""
    neg_pct = report.get("sentiment", {}).get("distribution_pct", {}).get("negative", 0)
    if neg_pct >= threshold:
        return {
            "type": "negative_spike",
            "severity": "high" if neg_pct >= threshold * 1.5 else "medium",
            "value": neg_pct,
            "threshold": threshold,
            "message": f"Negative sentiment spike: {neg_pct}% (threshold: {threshold}%)",
        }
    return None


def _check_viral_negative(report: dict, viral_threshold: int) -> list[dict]:
    """Return list of viral posts with negative sentiment."""
    alerts = []
    top_posts = report.get("engagement", {}).get("top_posts", [])
    for p in top_posts:
        if p.get("reactions", 0) >= viral_threshold:
            preview = p.get("content_preview", "")
            # Check for negative keywords in preview
            if any(kw in preview.lower() for kw in _DEFAULT_CRISIS_KEYWORDS):
                alerts.append({
                    "type": "viral_negative_post",
                    "severity": "high",
                    "post_id": p.get("post_id"),
                    "reactions": p.get("reactions", 0),
                    "post_url": p.get("post_url", ""),
                    "preview": preview[:100],
                    "message": f"Viral post with crisis keywords: {p.get('reactions')} reactions",
                })
    return alerts


def _check_crisis_keywords(posts: list[dict], crisis_keywords: list[str]) -> dict | None:
    """Return alert if crisis keywords appear in recent posts."""
    hit_count = 0
    hit_posts = []
    for p in posts:
        text = (p.get("content") or "").lower()
        matched_kws = [kw for kw in crisis_keywords if kw in text]
        if matched_kws:
            hit_count += 1
            hit_posts.append({
                "post_id": p.get("post_id"),
                "keywords": matched_kws,
                "reactions": (p.get("reactions") or {}).get("total", 0)
                    if isinstance(p.get("reactions"), dict) else 0,
                "preview": (p.get("content") or "")[:100].replace("\n", " "),
            })

    if hit_count >= 3:  # alert when 3+ posts contain crisis keywords
        return {
            "type": "crisis_keyword_cluster",
            "severity": "high" if hit_count >= 10 else "medium",
            "value": hit_count,
            "message": f"{hit_count} posts contain crisis keywords",
            "affected_posts": sorted(hit_posts, key=lambda x: x["reactions"], reverse=True)[:5],
        }
    return None


def _format_alert_message(group_id: str, alerts: list[dict]) -> str:
    """Format multiple alerts into a single Telegram-friendly message."""
    lines = [
        f"🚨 <b>CRISIS ALERT: {group_id}</b>",
        f"Time: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Alerts: {len(alerts)}",
        "",
    ]
    for a in alerts:
        severity_emoji = "🔴" if a.get("severity") == "high" else "🟡"
        lines.append(f"{severity_emoji} <b>{a['type']}</b>: {a['message']}")
        if a.get("post_url"):
            lines.append(f"   {a['post_url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Monitor loop
# ---------------------------------------------------------------------------

class CrisisMonitor:
    def __init__(self, group_id: str, cfg: dict):
        self.group_id = group_id
        self.cfg = cfg
        self.crisis_cfg = cfg.get("crisis", {})
        self.tg_cfg = cfg.get("telegram", {})
        self.neg_threshold = self.crisis_cfg.get("negative_pct_threshold", _DEFAULT_NEG_THRESHOLD)
        self.viral_threshold = self.crisis_cfg.get("viral_reactions_threshold", _DEFAULT_VIRAL_THRESHOLD)
        self.crisis_keywords = self.crisis_cfg.get("crisis_keywords", _DEFAULT_CRISIS_KEYWORDS)
        self._last_alert_hash: str = ""

    def check(self) -> list[dict]:
        """Run one check cycle. Returns list of active alerts."""
        import storage
        from analyzer import GroupAnalyzer

        posts = storage.load_posts(self.group_id)
        if not posts:
            _log.warning("No posts for group %s", self.group_id)
            return []

        analyzer = GroupAnalyzer(self.cfg)
        report = analyzer.analyze(posts, self.group_id)

        alerts = []

        # Check 1: Negative sentiment spike
        alert = _check_negative_spike(report, self.neg_threshold)
        if alert:
            alerts.append(alert)

        # Check 2: Viral negative posts
        viral_alerts = _check_viral_negative(report, self.viral_threshold)
        alerts.extend(viral_alerts)

        # Check 3: Crisis keyword cluster
        keyword_alert = _check_crisis_keywords(posts, self.crisis_keywords)
        if keyword_alert:
            alerts.append(keyword_alert)

        if alerts:
            self._send_alerts(alerts, report)

        return alerts

    def _send_alerts(self, alerts: list[dict], report: dict) -> None:
        """Log and optionally push alerts to Telegram."""
        print(f"\n{'='*60}")
        print(f"CRISIS ALERTS DETECTED for {self.group_id} — {len(alerts)} alert(s)")
        print(f"{'='*60}")
        for a in alerts:
            severity = a.get("severity", "medium").upper()
            print(f"[{severity}] {a.get('type')}: {a.get('message')}")

        # Telegram push
        tg_token = self.tg_cfg.get("token", "")
        tg_chat = self.tg_cfg.get("chat_id", "")
        if tg_token and tg_chat:
            msg = _format_alert_message(self.group_id, alerts)
            success = _send_telegram(tg_token, tg_chat, msg)
            if success:
                print("  Telegram alert sent.")
            else:
                print("  Telegram alert FAILED — check token/chat_id in config.")

    def run(self, interval_sec: int = 300) -> None:
        """Polling loop — runs indefinitely."""
        print(f"Crisis monitor started for group: {self.group_id}")
        print(f"Polling every {interval_sec}s | Neg threshold: {self.neg_threshold}% | "
              f"Viral threshold: {self.viral_threshold} reactions")
        print("Press Ctrl+C to stop.\n")

        while True:
            now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[{now}] Checking {self.group_id} ...", end=" ", flush=True)
            try:
                alerts = self.check()
                if alerts:
                    print(f"⚠️  {len(alerts)} alert(s) fired!")
                else:
                    print("OK — no crisis signals.")
            except Exception as exc:
                print(f"ERROR: {exc}")
                _log.exception("Monitor check failed")
            time.sleep(interval_sec)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Crisis Monitor — poll stored posts for crisis signals"
    )
    parser.add_argument("--group", required=True, help="group_id to monitor")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds (default 300)")
    parser.add_argument("--check-once", action="store_true", help="Run one check and exit (no loop)")
    args = parser.parse_args()

    from load_config import load_config
    cfg = load_config()

    monitor = CrisisMonitor(args.group, cfg)

    if args.check_once:
        alerts = monitor.check()
        print(json.dumps(alerts, ensure_ascii=False, indent=2))
    else:
        monitor.run(interval_sec=args.interval)


if __name__ == "__main__":
    main()
