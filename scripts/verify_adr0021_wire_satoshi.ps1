# ADR 0021 wire satoshi cutover - operator self-check.
# Does NOT start soak. Does NOT rebuild Docker / mesh.
# Run:
#   .\scripts\verify_adr0021_wire_satoshi.ps1
#   .\scripts\verify_adr0021_wire_satoshi.ps1 -SkipGate
param(
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0

function Write-Step([string]$Name) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " ADR 0021 wire satoshi cutover - operator self-check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Repo: $Root" -ForegroundColor DarkGray
Write-Host "  NOT soak / NOT mesh probe / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray
Write-Host ""

Write-Step "1 - unit: wire satoshi cutover + fee refuse pack"
$unitFiles = @(
    "tests/unit/test_adr0021_wire_satoshi_cutover.py",
    "tests/unit/test_wave51_tx_propagation.py",
    "tests/unit/test_wave_r_honesty_fixes.py",
    "tests/unit/test_v13177_mempool_min_fee_refuse.py",
    "tests/unit/test_v13184_mempool_negative_value_refuse.py",
    "tests/unit/test_v13186_mempool_negative_fee_refuse.py",
    "tests/unit/test_v13194_mempool_nonfinite_fee_refuse.py",
    "tests/unit/test_canonical_serializer_satoshi.py",
    "tests/unit/test_v13143_mempool_cheap_refuse.py"
)
python -m pytest -v --tb=line @unitFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: wire satoshi unit pack" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: wire satoshi unit pack" -ForegroundColor Green
}

Write-Step "2 - source needles (cutover honesty)"
$wire = Get-Content -Raw -Path (Join-Path $Root "blockchain\mempool_wire.py")
$p2p = Get-Content -Raw -Path (Join-Path $Root "network\p2p_node.py")
$mp = Get-Content -Raw -Path (Join-Path $Root "blockchain\mempool.py")
$gate = Get-Content -Raw -Path (Join-Path $Root "scripts\industrial_gate.py")

$needleFail = 0
if ($wire -notmatch "amount_satoshi" -or $wire -notmatch "fee_satoshi") {
    Write-Host "FAIL: mempool_wire missing amount_satoshi / fee_satoshi emit" -ForegroundColor Red
    $needleFail++
}
if ($wire -notmatch "resolve_wire_fee_sat" -or $wire -notmatch "WireMoneyMismatch") {
    Write-Host "FAIL: mempool_wire missing resolve_wire_fee_sat / WireMoneyMismatch" -ForegroundColor Red
    $needleFail++
}
if ($p2p -notmatch "fee_satoshi_mismatch" -or $p2p -notmatch "value_satoshi_mismatch") {
    Write-Host "FAIL: p2p_node missing satoshi mismatch refuse codes" -ForegroundColor Red
    $needleFail++
}
if ($mp -notmatch "amount_satoshi") {
    Write-Host "FAIL: MempoolTransaction missing amount_satoshi dual-write" -ForegroundColor Red
    $needleFail++
}
if ($gate -notmatch "resolve_wire_fee_sat" -or $gate -notmatch "fee_satoshi_mismatch") {
    Write-Host "FAIL: industrial_gate missing ADR 0021 cutover needles" -ForegroundColor Red
    $needleFail++
}
if ($wire -match 'float\(tx\.amount\)' -or $wire -match 'float\(tx\.fee\)') {
    Write-Host "FAIL: mempool_wire still emits raw float(tx.amount/fee) as money authority" -ForegroundColor Red
    $needleFail++
}

if ($needleFail -gt 0) {
    $fail += $needleFail
} else {
    Write-Host "OK: source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Write-Step "3 - industrial_gate"
    python scripts/industrial_gate.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: industrial_gate" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: industrial_gate" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "SKIP: industrial_gate (-SkipGate)" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
if ($fail -eq 0) {
    Write-Host " RESULT: PASS - wire satoshi cutover self-check" -ForegroundColor Green
    Write-Host " Honesty: unit+needles(+gate). Not mesh probe. Not 48h soak." -ForegroundColor DarkGray
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
}

Write-Host (" RESULT: FAIL ({0} checks)" -f $fail) -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Cyan
exit 1
