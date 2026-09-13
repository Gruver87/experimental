# Phase 5.4 - Cross-shard lab operator self-check (Profile E).
# Does NOT start soak. Does NOT flip feature_sharding on prod 778888.
# Does NOT start shard docker mesh (separate: start_shard_devnet.ps1).
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

Write-Host "CROSS-SHARD LAB verify (Phase 5)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT prod arm / feature_sharding must stay false on 778888" -ForegroundColor DarkGray

Invoke-Check "cross_shard_lab.py" {
    python scripts/cross_shard_lab.py
}

Invoke-Check "prod_mesh_feature_sharding_false" {
    python -c "import json, pathlib; files=sorted(pathlib.Path('docker').glob('node.prod.mesh*.json')); assert files;
assert all(json.loads(p.read_text(encoding='utf-8')).get('feature_sharding') is False for p in files);
print('sharding_false', [p.name for p in files])"
}

if (-not $SkipGate) {
    Invoke-Check "industrial_gate_cross_shard_needles" {
        python -c "from pathlib import Path; t=(Path('scripts')/'industrial_gate.py').read_text(encoding='utf-8'); assert 'cross_shard_lab.py' in t; assert '2/3' in t or 'quorum' in t.lower(); print('cross_shard_gate_needles_ok')"
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "5.4-cross-shard-lab"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    steps = $steps
    honesty = @(
        "NOT soak",
        "NOT feature_sharding on prod 778888",
        "Profile E script lab only (no docker shard mesh in this verify)"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_cross_shard_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS cross-shard lab verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL cross-shard lab verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
Write-Host "  optional docker lab later: .\scripts\start_shard_devnet.ps1" -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
