# Wave P operator self-check.
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

Write-Host "WAVE P self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave P honesty pack"
python -m pytest -q `
  tests/unit/test_wave_p_honesty_fixes.py `
  tests/unit/test_pool_dao.py::test_dao_vote_unlocks_ecosystem_pool `
  tests/unit/test_devnet_pool_spend.py `
  tests/unit/test_eth_raw_tx.py `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave P unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave P unit tests" -ForegroundColor Green
}

Step "2) source needles"
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$pl = Get-Content -Raw -Path (Join-Path $Root "runtime\pool_locks.py")
$tv = Get-Content -Raw -Path (Join-Path $Root "blockchain\tx_validator.py")
$eth = Get-Content -Raw -Path (Join-Path $Root "crypto\eth_tx.py")
if ($http -notmatch 'unit.: .satoshi' -or $http -notmatch "total_stake_satoshi") {
    Write-Host "FAIL: /consensus/stake missing satoshi unit" -ForegroundColor Red
    $fail++
} elseif ($pl -notmatch "total_satoshi" -or $pl -notmatch "spendable_balance_sat") {
    Write-Host "FAIL: pool_locks not satoshi" -ForegroundColor Red
    $fail++
} elseif ($tv -notmatch "signature verify unavailable") {
    Write-Host "FAIL: tx_validator still paints unavailable as invalid" -ForegroundColor Red
    $fail++
} elseif ($eth -notmatch "eth signature verify unavailable") {
    Write-Host "FAIL: eth_tx still paints unavailable as False" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave P source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave P ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave P self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_o.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
