# Production: run full (scrape + analyze) for all enabled groups in config/scheduled_groups.json
# Schedule via Task Scheduler; set $env:FB_EMAIL, $env:FB_PASSWORD before running.
$ErrorActionPreference = "Stop"
$SkillRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $SkillRoot

$configPath = Join-Path $SkillRoot "config\scheduled_groups.json"
if (-not (Test-Path $configPath)) {
    Write-Error "[run_scheduled] config\scheduled_groups.json not found"
    exit 1
}

$cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$defaults = if ($cfg.defaults) { $cfg.defaults } else { @{ days_back = 7; max_posts = 500 } }
$groups = $cfg.groups | Where-Object { $_.enabled -ne $false }
if (-not $groups) {
    Write-Host "[run_scheduled] No enabled groups"
    exit 0
}

foreach ($g in $groups) {
    $gid = if ($g.id) { $g.id } else { $g.url }
    $days = if ($null -ne $g.days_back) { $g.days_back } else { $defaults.days_back }
    $url = if ($g.url) { $g.url } else { "https://www.facebook.com/groups/$gid" }
    Write-Host "[run_scheduled] Running full for $gid (days=$days)"
    & python main.py full --group $url --days $days --output json
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[run_scheduled] Failed for $gid"
        exit $LASTEXITCODE
    }
}
Write-Host "[run_scheduled] All groups done"
