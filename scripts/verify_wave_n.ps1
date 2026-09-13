# Wave N operator self-check.
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

Write-Host "WAVE N self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave N honesty pack"
python -m pytest -q `
  tests/unit/test_wave_n_honesty_fixes.py `
  tests/unit/test_multisig_wallet.py `
  tests/unit/test_native_consensus_select.py `
  tests/unit/test_evm_rpc_compat.py::test_format_block_uses_stored_tx_root `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave N unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave N unit tests" -ForegroundColor Green
}

Step "2) source needles"
$ce = Get-Content -Raw -Path (Join-Path $Root "consensus_engine.py")
$ms = Get-Content -Raw -Path (Join-Path $Root "features\multisig.py")
$fe = Get-Content -Raw -Path (Join-Path $Root "finality_engine.py")
$eth = Get-Content -Raw -Path (Join-Path $Root "api\eth_format.py")
$nat = Get-Content -Raw -Path (Join-Path $Root "crypto\native.py")
if ($ce -notmatch "stake: int" -or $ce -notmatch "to_satoshi") {
    Write-Host "FAIL: consensus_engine stake not satoshi" -ForegroundColor Red
    $fail++
} elseif ($ms -notmatch "amount_satoshi" -or $ms -notmatch '"execution_failed"') {
    Write-Host "FAIL: multisig still float / paints execution_failed success" -ForegroundColor Red
    $fail++
} elseif ($fe -match "max\(1, int\(count or 1\)\)") {
    Write-Host "FAIL: finality still invents denom=1" -ForegroundColor Red
    $fail++
} elseif ($eth -notmatch "Corrupt stored roots return None") {
    Write-Host "FAIL: eth_format still invents over corrupt root" -ForegroundColor Red
    $fail++
} elseif ($nat -match "int\(obj \* 1_000_000\)") {
    Write-Host "FAIL: native canonicalize still float\*1e6" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave N source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave N ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave N self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_m.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
