# Phase 5.2 - Oracle lab operator self-check (aux sprout).
# Does NOT start soak. Does NOT flip feature_oracles on prod 778888.
param(
    [switch]$SkipGate
)

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

Write-Host "ORACLE LAB verify (Phase 5)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT prod arm / feature_oracles must stay false on 778888" -ForegroundColor DarkGray

Invoke-Check "oracle_lab.py" {
    python scripts/oracle_lab.py
}

Invoke-Check "pytest_wave39_oracle" {
    python -m pytest -q tests/unit/test_wave39_oracle_bridge.py --tb=line
}

Invoke-Check "prod_mesh_feature_oracles_false" {
    python -c "import json, pathlib; root=pathlib.Path('docker'); files=sorted(root.glob('node.prod.mesh*.json')); assert files, 'no mesh json';
[print(p.name, json.loads(p.read_text(encoding='utf-8')).get('feature_oracles')) or None for p in files];
assert all(json.loads(p.read_text(encoding='utf-8')).get('feature_oracles') is False for p in files)"
}

if (-not $SkipGate) {
    Invoke-Check "industrial_gate_oracle_needle" {
        python -c "from pathlib import Path; t=(Path('scripts')/'industrial_gate.py').read_text(encoding='utf-8'); assert 'oracle_lab.py' in t; assert 'quorum' in t.lower() or 'median' in t.lower(); print('oracle_gate_needles_ok')"
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "5.2-oracle-lab"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    steps = $steps
    honesty = @(
        "NOT soak",
        "NOT feature_oracles on prod 778888",
        "aux SQLite lab only"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_oracle_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS oracle lab verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL oracle lab verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
