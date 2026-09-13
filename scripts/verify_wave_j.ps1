# Wave J operator self-check (L2 satoshi / eth_call / fee / smart-account / tip prod).
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

Write-Host "WAVE J self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave J honesty pack"
python -m pytest -q `
  tests/unit/test_wave_j_honesty_fixes.py `
  tests/unit/test_smart_accounts_auth.py `
  tests/unit/test_p2p_dispatch.py::test_tip_evidence_unbound_refuses_in_prod `
  tests/unit/test_p2p_dispatch.py::test_tip_evidence_shadow_provider_exception_logs_unbound `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave J unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave J unit tests" -ForegroundColor Green
}

Step "2) source needles"
$will = Get-Content -Raw -Path (Join-Path $Root "features\crypto_will.py")
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$p2p = Get-Content -Raw -Path (Join-Path $Root "network\p2p_node.py")
$tip = Get-Content -Raw -Path (Join-Path $Root "network\p2p_dispatch\tip_evidence.py")
$sa = Get-Content -Raw -Path (Join-Path $Root "features\smart_accounts.py")
if ($will -notmatch "balance_delta_satoshi") {
    Write-Host "FAIL: crypto_will not satoshi" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "evm adapter unavailable for eth_call") {
    Write-Host "FAIL: eth_call honesty missing" -ForegroundColor Red
    $fail++
} elseif ($p2p -match "float\(fee\) < 0\.0") {
    Write-Host "FAIL: P2P still float-compares negative fee" -ForegroundColor Red
    $fail++
} elseif ($sa -notmatch "smart_accounts_ephemeral_unbound") {
    Write-Host "FAIL: smart-account ephemeral refuse missing" -ForegroundColor Red
    $fail++
} elseif ($tip -notmatch "_prod_fail_closed") {
    Write-Host "FAIL: tip evidence prod fail-closed missing" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave J source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave J ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave J self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_i.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
