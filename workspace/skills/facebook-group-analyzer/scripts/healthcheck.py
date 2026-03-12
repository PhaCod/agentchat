#!/usr/bin/env python3
"""
Production health check: config, env, deps, optional session.
Exit 0 = OK, non-zero = failure. Use in cron or monitoring.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    errors = []

    # Config exists
    cfg_path = root / "config" / "config.json"
    if not cfg_path.exists():
        errors.append("config/config.json missing")
    else:
        import json
        try:
            json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"config invalid: {e}")

    # Credentials: env or config (load_config merges env)
    try:
        from load_config import load_config
        cfg = load_config()
        email = (cfg.get("facebook") or {}).get("email") or os.environ.get("FB_EMAIL")
    except Exception as e:
        email = None
        errors.append(f"load_config failed: {e}")
    if not email:
        errors.append("FB_EMAIL not set and facebook.email empty in config")

    # Python deps
    try:
        import playwright
    except ImportError:
        errors.append("playwright not installed (pip install -r requirements.txt && playwright install chromium)")

    # Optional: session file (faster runs; missing = first run will require login)
    session_file = os.environ.get("FB_SESSION_FILE") or "sessions/fb_session.json"
    session_path = root / session_file
    if not session_path.exists():
        print(f"healthcheck WARN: session file missing: {session_path}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"healthcheck FAIL: {e}", file=sys.stderr)
        return 1
    print("healthcheck OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
