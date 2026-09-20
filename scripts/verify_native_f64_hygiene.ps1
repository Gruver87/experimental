# Native f64/unwrap hygiene - operator self-check.
# Does NOT start soak. Does NOT rebuild Docker mesh (native rebuild optional).
# Run:
#   .\scripts\verify_native_f64_hygiene.ps1
#   .\scripts\verify_native_f64_hygiene.ps1 -SkipBuild -SkipGate
param(
    [switch]$SkipBuild,
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
Write-Host " Native f64/unwrap hygiene - operator self-check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Repo: $Root" -ForegroundColor DarkGray
Write-Host "  NOT soak / NOT mesh probe / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray
Write-Host ""

if (-not $SkipBuild) {
    Write-Step "0 - build_native"
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_native.ps1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: build_native" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: build_native" -ForegroundColor Green
    }
} else {
    Write-Host "SKIP: build_native (-SkipBuild)" -ForegroundColor DarkYellow
}

Write-Step "1 - Rust amount unit tests"
Push-Location (Join-Path $Root "native\abs_native")
cargo test amount:: -- --nocapture
$rustCode = $LASTEXITCODE
Pop-Location
if ($rustCode -ne 0) {
    Write-Host "FAIL: Rust amount tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Rust amount tests" -ForegroundColor Green
}

Write-Step "2 - Python hygiene + amount parity"
$unitFiles = @(
    "tests/unit/test_native_f64_unwrap_hygiene.py",
    "tests/unit/test_native_amount_state.py",
    "tests/unit/test_amount_units.py"
)
python -m pytest -v --tb=line @unitFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Python native amount pack" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Python native amount pack" -ForegroundColor Green
}

Write-Step "3 - source needles"
$wb = Get-Content -Raw -Path (Join-Path $Root "native\abs_native\src\evm_writeback.rs")
$amt = Get-Content -Raw -Path (Join-Path $Root "native\abs_native\src\amount.rs")
$needleFail = 0
if ($wb -match 'f \* 1_000_000\.0' -or $wb -match '\(sat as f64\) / 1_000_000\.0') {
    Write-Host "FAIL: evm_writeback still uses IEEE x1e6 money path" -ForegroundColor Red
    $needleFail++
}
if ($amt -notmatch "must be integer satoshi") {
    Write-Host "FAIL: amount.rs missing integer satoshi refuse" -ForegroundColor Red
    $needleFail++
}
if ($amt -match "to_f64\(\)\.unwrap_or\(0\.0\)") {
    Write-Host "FAIL: amount.rs still paints float conversion failure as 0.0" -ForegroundColor Red
    $needleFail++
}
if ($needleFail -gt 0) {
    $fail += $needleFail
} else {
    Write-Host "OK: source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Write-Step "4 - industrial_gate"
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
    Write-Host " RESULT: PASS - native f64/unwrap hygiene self-check" -ForegroundColor Green
    Write-Host " Honesty: rust+unit+needles(+gate). Not mesh probe. Not 48h soak." -ForegroundColor DarkGray
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
}

Write-Host (" RESULT: FAIL ({0} checks)" -f $fail) -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Cyan
exit 1
