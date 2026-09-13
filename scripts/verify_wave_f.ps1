# Wave F operator self-check (validators fail-closed + demote/under_mesh alerts).
# Does NOT start soak. Does NOT rebuild Docker / mesh.
param(
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0

function Step([string]$Name) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

Write-Host "WAVE F self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave F validators + alerts"
python -m pytest -q tests/unit/test_wave_f_input_validators_fail_closed.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave F unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave F unit tests" -ForegroundColor Green
}

Step "2) regression: Wave E demote gauges still present"
python -m pytest -q tests/unit/test_wave_e_mempool_demote_metric.py tests/unit/test_wave_d_under_mesh_metric.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave D/E regression units" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave D/E regression units" -ForegroundColor Green
}

Step "3) source needles (no identity sanitize; alerts; verify packs)"
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$alerts = Get-Content -Raw -Path (Join-Path $Root "deploy\prometheus\alerts.yml")
$glance = Get-Content -Raw -Path (Join-Path $Root "docs\AT_A_GLANCE.md")
if ($http -match "def sanitize_input\(x\):\s*return x") {
    Write-Host "FAIL: identity sanitize stub still present" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "require_input_validators") {
    Write-Host "FAIL: require_input_validators missing" -ForegroundColor Red
    $fail++
} elseif ($alerts -notmatch "AbsoluteMempoolStoreDemoted") {
    Write-Host "FAIL: alerts missing AbsoluteMempoolStoreDemoted" -ForegroundColor Red
    $fail++
} elseif ($alerts -notmatch "AbsoluteP2PUnderMesh") {
    Write-Host "FAIL: alerts missing AbsoluteP2PUnderMesh" -ForegroundColor Red
    $fail++
} elseif (-not (Test-Path (Join-Path $Root "scripts\verify_wave_e.ps1"))) {
    Write-Host "FAIL: verify_wave_e.ps1 missing" -ForegroundColor Red
    $fail++
} elseif ($glance -notmatch "verify_wave_f") {
    Write-Host "FAIL: AT_A_GLANCE missing verify_wave_f" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave F source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Step "4) industrial_gate"
    python scripts/industrial_gate.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: industrial_gate" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: industrial_gate" -ForegroundColor Green
    }
} else {
    Write-Host "SKIP industrial_gate (-SkipGate)" -ForegroundColor Yellow
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "RESULT: FAIL Wave F ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave F self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_e.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered: .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
exit 0
