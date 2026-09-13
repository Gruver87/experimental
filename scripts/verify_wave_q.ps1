# Wave Q operator self-check.
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

Write-Host "WAVE Q self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave Q honesty pack"
python -m pytest -q tests/unit/test_wave_q_honesty_fixes.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave Q unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave Q unit tests" -ForegroundColor Green
}

Step "2) source needles"
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$w = Get-Content -Raw -Path (Join-Path $Root "crypto\wallet.py")
$vk = Get-Content -Raw -Path (Join-Path $Root "crypto\validator_keys.py")
if ($http -match 'fee", 0\.001\)' -or $http -match "tx\.fee \* 1e9") {
    Write-Host "FAIL: http still invents fee/MEV gas" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "fee or fee_satoshi required") {
    Write-Host "FAIL: /tx/sign still invents fee" -ForegroundColor Red
    $fail++
} elseif ($w -notmatch "ECDSA backend missing") {
    Write-Host "FAIL: wallet still paints missing ECDSA as False" -ForegroundColor Red
    $fail++
} elseif ($vk -notmatch "attestation verify unavailable") {
    Write-Host "FAIL: validator_keys still paints derive fail as False" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave Q source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave Q ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave Q self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_p.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
