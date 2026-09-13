# Phase 5.5 - Bridge OFF honesty operator self-check.
# Does NOT enable bridge. Does NOT start soak. Does NOT cut over L1.
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0
$started = Get-Date
$steps = @()

function Invoke-Check([string]$Name, [scriptblock]$Command) {
    Write-Host ""
    Write-Host (">>> " + $Name) -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $Command
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }
    $ok = ($rc -eq 0)
    $script:steps += @{ name = $Name; ok = $ok; exit_code = $rc }
    if ($ok) {
        Write-Host ("OK: " + $Name) -ForegroundColor Green
    } else {
        Write-Host ("FAIL: " + $Name + " (exit " + $rc + ")") -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "BRIDGE OFF verify (Phase 5)" -ForegroundColor Cyan
Write-Host "  NOT bridge cutover / NOT L1 contracts / NOT soak" -ForegroundColor DarkGray

Invoke-Check "bridge_off_audit_gate" {
    python scripts/bridge_off_audit_gate.py
}

Invoke-Check "prod_mesh_bridge_enabled_false" {
    python -c "import json, pathlib; files=list(pathlib.Path('docker').glob('node.prod.mesh*.json')); assert files;
assert all(json.loads(p.read_text(encoding='utf-8')).get('bridge_enabled') is False for p in files);
print('bridge_enabled_false', [p.name for p in files])"
}

Invoke-Check "compose_bridge_enabled_default_false" {
    python -c "from pathlib import Path; t=Path('docker-compose.prod.3node.yml').read_text(encoding='utf-8'); assert 'BRIDGE_ENABLED' in t and ':-false' in t; print('compose_default_false_ok')"
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "5.5-bridge-off"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    steps = $steps
    honesty = @(
        "NOT bridge ON",
        "NOT L1 cutover",
        "NOT soak / NOT mainnet",
        "bridge OFF PASS != bridge ready"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_bridge_off_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS bridge OFF verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL bridge OFF verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
