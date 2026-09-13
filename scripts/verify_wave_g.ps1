# Wave G operator self-check (pack-fallback alert + ready/watch honesty).
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

Write-Host "WAVE G self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave G"
python -m pytest -q tests/unit/test_wave_g_rocks_pack_alert.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave G unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave G unit tests" -ForegroundColor Green
}

Step "2) regression: Wave F + E"
python -m pytest -q tests/unit/test_wave_f_input_validators_fail_closed.py tests/unit/test_wave_e_mempool_demote_metric.py tests/unit/test_wave_c_rocks_pack_fallback.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave C/E/F regression" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave C/E/F regression" -ForegroundColor Green
}

Step "3) source needles"
$alerts = Get-Content -Raw -Path (Join-Path $Root "deploy\prometheus\alerts.yml")
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$hw = Get-Content -Raw -Path (Join-Path $Root "scripts\health_watch.ps1")
$glance = Get-Content -Raw -Path (Join-Path $Root "docs\AT_A_GLANCE.md")
if ($alerts -notmatch "AbsoluteRocksNativePackFallbacks") {
    Write-Host "FAIL: alerts missing AbsoluteRocksNativePackFallbacks" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch 'payload\["mempool_store"\]') {
    Write-Host "FAIL: ready missing mempool_store" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "rocks_native_pack_fallbacks") {
    Write-Host "FAIL: ready missing rocks_native_pack_fallbacks" -ForegroundColor Red
    $fail++
} elseif ($hw -notmatch "mempool_demoted") {
    Write-Host "FAIL: health_watch missing demote soft-WARN" -ForegroundColor Red
    $fail++
} elseif ($glance -notmatch "verify_wave_g") {
    Write-Host "FAIL: AT_A_GLANCE missing verify_wave_g" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave G source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave G ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave G self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_f.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered: .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
exit 0
