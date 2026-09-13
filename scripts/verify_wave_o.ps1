# Wave O operator self-check.
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

Write-Host "WAVE O self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave O honesty pack"
python -m pytest -q `
  tests/unit/test_wave_o_honesty_fixes.py `
  tests/unit/test_native_p2p_wire.py::test_validate_validator_register_peers_get_block_blocks `
  tests/unit/test_native_p2p_wire.py::test_validate_cross_shard_and_migration `
  tests/unit/test_pool_dao.py::test_dao_vote_unlocks_ecosystem_pool `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave O unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave O unit tests" -ForegroundColor Green
}

Step "2) source needles"
$nat = Get-Content -Raw -Path (Join-Path $Root "crypto\native.py")
$pl = Get-Content -Raw -Path (Join-Path $Root "runtime\pool_locks.py")
$p2p = Get-Content -Raw -Path (Join-Path $Root "network\p2p_node.py")
if ($nat -notmatch "stake_satoshi" -or $nat -notmatch "amount_satoshi" -or $nat -notmatch "balance_satoshi") {
    Write-Host "FAIL: P2P validators missing satoshi fields" -ForegroundColor Red
    $fail++
} elseif ($pl -notmatch "DAO_VOTE_BPS" -or $pl -match "total_validators = 1") {
    Write-Host "FAIL: pool_locks still invents denom / float quorum" -ForegroundColor Red
    $fail++
} elseif ($p2p -notmatch "fee_gas_price_unset") {
    Write-Host "FAIL: p2p still invents gas_price or 0.001" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave O source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave O ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave O self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_n.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
