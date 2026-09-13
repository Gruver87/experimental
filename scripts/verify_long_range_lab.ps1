# Long-Range lab operator self-check (ADR 0017 / Profile F companion).
# Does NOT start 2h/48h soak. Does NOT flip feature_long_range on prod 778888.
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

Write-Host "LONG-RANGE LAB verify (pre-soak DX)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT prod arm / feature_long_range must stay false on 778888" -ForegroundColor DarkGray

Invoke-Check "long_range_lab.py" {
    python scripts/long_range_lab.py
}

Invoke-Check "long_range_p2p_lab.py" {
    python scripts/long_range_p2p_lab.py
}

Invoke-Check "long_range_gossip_lab.py" {
    python scripts/long_range_gossip_lab.py
}

Invoke-Check "prod_mesh_feature_long_range_false" {
    python -c "import json, pathlib; files=sorted(pathlib.Path('docker').glob('node.prod.mesh*.json')); assert files;
assert all(json.loads(p.read_text(encoding='utf-8')).get('feature_long_range') is False for p in files);
print('long_range_false', [p.name for p in files])"
}

if (-not $SkipGate) {
    Invoke-Check "industrial_gate_long_range_needles" {
        python -c "from pathlib import Path; t=(Path('scripts')/'industrial_gate.py').read_text(encoding='utf-8');
assert 'long_range' in t.lower() or 'WeakSubjectivity' in t or 'feature_long_range' in t;
print('lr_gate_needles_ok')"
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "pre-soak-long-range-lab"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    steps = $steps
    honesty = @(
        "NOT soak",
        "NOT feature_long_range on prod 778888",
        "script labs only (no 2h/48h harness start)"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_long_range_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS long-range lab verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL long-range lab verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
