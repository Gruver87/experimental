# Wave M operator self-check.
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

Write-Host "WAVE M self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave M honesty pack"
python -m pytest -q `
  tests/unit/test_wave_m_honesty_fixes.py `
  tests/unit/test_wave42_wasm_relayer.py::test_wasm_call_persists_storage `
  tests/unit/test_l2_advanced_features.py::test_lightning_htlc_settle_and_refund `
  tests/unit/test_l2_advanced_features.py::test_lightning_htlc_refund_after_expiry `
  --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave M unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave M unit tests" -ForegroundColor Green
}

Step "2) source needles"
$q = Get-Content -Raw -Path (Join-Path $Root "consensus\bft\quorum.py")
$ln = Get-Content -Raw -Path (Join-Path $Root "features\lightning.py")
$zk = Get-Content -Raw -Path (Join-Path $Root "core\components\zk_gateway.py")
$wasm = Get-Content -Raw -Path (Join-Path $Root "features\wasm_vm.py")
$pl = Get-Content -Raw -Path (Join-Path $Root "features\plasma.py")
if ($q -notmatch "voted\*3 >= total\*2" -and $q -notmatch "\* 3 >= .* \* 2") {
    Write-Host "FAIL: BFT quorum still float" -ForegroundColor Red
    $fail++
} elseif ($ln -match "amount \* ch\.fee_rate") {
    Write-Host "FAIL: lightning still float fee" -ForegroundColor Red
    $fail++
} elseif ($zk -notmatch "must not paint ZK enabled") {
    Write-Host "FAIL: ZK still paints enabled on error" -ForegroundColor Red
    $fail++
} elseif ($wasm -notmatch "wasm_pseudo_token_host_refused") {
    Write-Host "FAIL: WASM pseudo transfer still green" -ForegroundColor Red
    $fail++
} elseif ($pl -notmatch "_l2_balance_sat") {
    Write-Host "FAIL: plasma L2 not satoshi" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave M source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave M ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave M self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_l.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
