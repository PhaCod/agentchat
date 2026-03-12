@echo off
rem Production: run full (scrape + analyze) for all enabled groups in config/scheduled_groups.json
rem Schedule via Windows Task Scheduler or OpenClaw cron; set FB_EMAIL, FB_PASSWORD in env.
setlocal
set "SKILL_ROOT=%~dp0.."
cd /d "%SKILL_ROOT%"

if not exist "config\scheduled_groups.json" (
  echo [run_scheduled] config\scheduled_groups.json not found
  exit /b 1
)

python -c "
import json
import subprocess
import sys
from pathlib import Path

root = Path('.')
cfg = json.loads((root / 'config' / 'scheduled_groups.json').read_text(encoding='utf-8'))
defaults = cfg.get('defaults', {})
groups = [g for g in cfg.get('groups', []) if g.get('enabled', True)]
if not groups:
    print('[run_scheduled] No enabled groups')
    sys.exit(0)

for g in groups:
    gid = g.get('id') or g.get('url', '')
    days = g.get('days_back', defaults.get('days_back', 7))
    max_posts = g.get('max_posts', defaults.get('max_posts', 500))
    url = g.get('url') or f'https://www.facebook.com/groups/{gid}'
    print(f'[run_scheduled] Running full for {gid} (days={days}, max_posts={max_posts})')
    r = subprocess.run([
        sys.executable, 'main.py', 'full', '--group', url,
        '--days', str(days), '--max-posts', str(max_posts), '--output', 'json'
    ], cwd=root)
    if r.returncode != 0:
        print(f'[run_scheduled] Failed for {gid}')
        sys.exit(r.returncode)
print('[run_scheduled] All groups done')
"

endlocal
