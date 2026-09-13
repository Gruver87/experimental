# Wave I operator self-check (PQ / gasPrice / confirmations / ready-require).
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

Write-Host "WAVE I self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave I honesty pack"
python -m pytest -q tests/unit/test_wave_i_honesty_fixes.py tests/unit/test_evm_rpc_compat.py::test_eth_gas_price_tx_lookup_honesty --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave I unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave I unit tests" -ForegroundColor Green
}

Step "2) source needles"
$pq = Get-Content -Raw -Path (Join-Path $Root "features\postquantum.py")
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$ad = Get-Content -Raw -Path (Join-Path $Root "bridge\adapter.py")
$cfg = Get-Content -Raw -Path (Join-Path $Root "runtime\config.py")
if ($pq -notmatch "educational hash-demo removed") {
    Write-Host "FAIL: Dilithium educational demo still present" -ForegroundColor Red
    $fail++
} elseif ($pq -notmatch "SPHINCS\+ verify backend not available") {
    Write-Host "FAIL: SPHINCS verify still returns False?" -ForegroundColor Red
    $fail++
} elseif ($ad -notmatch "confirmations probe failed") {
    Write-Host "FAIL: get_confirmations unknown collapse" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "advertise_config_gas_price") {
    Write-Host "FAIL: eth_gasPrice advertise gate missing" -ForegroundColor Red
    $fail++
} elseif ($cfg -notmatch "advertise_config_gas_price") {
    Write-Host "FAIL: config advertise_config_gas_price missing" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "mempool_store_native") {
    Write-Host "FAIL: ready demote gate missing" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave I source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave I ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave I self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_h.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
