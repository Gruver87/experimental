# Wave R operator self-check.
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

Write-Host "WAVE R self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave R honesty pack"
python -m pytest -q `
  tests/unit/test_wave_r_honesty_fixes.py `
  tests/unit/test_adr0021_phase2_store.py `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave R unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave R unit tests" -ForegroundColor Green
}

Step "2) source needles"
$ts = Get-Content -Raw -Path (Join-Path $Root "crypto\tx_signer.py")
$mp = Get-Content -Raw -Path (Join-Path $Root "blockchain\mempool.py")
$ai = Get-Content -Raw -Path (Join-Path $Root "features\ai_validator.py")
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
if ($ts -match "fee', 0\.001" -or $ts -match 'fee", 0\.001') {
    Write-Host "FAIL: tx_signer still invents fee 0.001" -ForegroundColor Red
    $fail++
} elseif ($ts -notmatch "ECDSA backend missing") {
    Write-Host "FAIL: tx_signer verify still paints missing ECDSA as False" -ForegroundColor Red
    $fail++
} elseif ($mp -notmatch "from_satoshi_float\(amount_sat\)") {
    Write-Host "FAIL: mempool store still raw float money" -ForegroundColor Red
    $fail++
} elseif ($ai -match "max\(1, len\(self\.validators\)\)") {
    Write-Host "FAIL: ai_validator still invents denom=1" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch '"valid": None') {
    Write-Host "FAIL: /tx/verify still paints unavailable as false" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave R source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Step "3) industrial_gate"
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
    Write-Host "RESULT: FAIL Wave R ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave R self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_q.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
