# Wave K operator self-check.
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

Write-Host "WAVE K self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave K honesty pack"
python -m pytest -q `
  tests/unit/test_wave_k_honesty_fixes.py `
  tests/unit/test_smart_accounts_auth.py `
  tests/unit/test_wave40_l2_persistence.py `
  tests/unit/test_l2_advanced_features.py::test_plasma_merkle_proof_roundtrip `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave K unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave K unit tests" -ForegroundColor Green
}

Step "2) source needles"
$p2p = Get-Content -Raw -Path (Join-Path $Root "network\p2p_node.py")
$pl = Get-Content -Raw -Path (Join-Path $Root "features\plasma.py")
$sh = Get-Content -Raw -Path (Join-Path $Root "dynamic_sharding.py")
$ps = Get-Content -Raw -Path (Join-Path $Root "scripts\verify_pre_soak.ps1")
$sa = Get-Content -Raw -Path (Join-Path $Root "features\smart_accounts.py")
if ($p2p -match "float\(value\) < 0\.0") {
    Write-Host "FAIL: P2P value still float-negative" -ForegroundColor Red
    $fail++
} elseif ($pl -notmatch "unsigned plasma txs must not admit") {
    Write-Host "FAIL: plasma unsigned still allowed" -ForegroundColor Red
    $fail++
} elseif ($sh -notmatch "try_debit_satoshi") {
    Write-Host "FAIL: cross-shard not satoshi" -ForegroundColor Red
    $fail++
} elseif ($ps -notmatch "PASS static-only") {
    Write-Host "FAIL: pre-soak SkipMesh still claims pre-soak PASS" -ForegroundColor Red
    $fail++
} elseif ($sa -notmatch "guardian_verifier") {
    Write-Host "FAIL: recovery still address-only" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave K source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave K ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave K self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_j.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
