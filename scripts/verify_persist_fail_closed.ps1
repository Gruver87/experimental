# Persist fail-closed - operator self-check.
# Does NOT start soak. Does NOT rebuild Docker / mesh.
# Run:
#   .\scripts\verify_persist_fail_closed.ps1
#   .\scripts\verify_persist_fail_closed.ps1 -SkipGate
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
Write-Host " Persist fail-closed - operator self-check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Repo: $Root" -ForegroundColor DarkGray
Write-Host "  NOT soak / NOT mesh probe / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray
Write-Host ""

Write-Step "1 - unit: persist fail-closed + atomic packs"
$unitFiles = @(
    "tests/unit/test_persist_fail_closed.py",
    "tests/unit/test_database_atomic.py",
    "tests/unit/test_rocks_store.py"
)
python -m pytest -v --tb=line @unitFiles
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: persist fail-closed unit pack" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: persist fail-closed unit pack" -ForegroundColor Green
}

Write-Step "2 - source needles"
$rocks = Get-Content -Raw -Path (Join-Path $Root "storage\rocks_store.py")
$db = Get-Content -Raw -Path (Join-Path $Root "storage\database.py")
$chain = Get-Content -Raw -Path (Join-Path $Root "storage\chain_storage.py")
$types = Get-Content -Raw -Path (Join-Path $Root "storage\types.py")
$needleFail = 0
if ($types -notmatch "class PersistError") {
    Write-Host "FAIL: storage.types missing PersistError" -ForegroundColor Red
    $needleFail++
}
if ($rocks -notmatch "raise PersistError" -or $db -notmatch "raise PersistError" -or $chain -notmatch "raise PersistError") {
    Write-Host "FAIL: hot persist paths missing raise PersistError" -ForegroundColor Red
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
    Write-Host " RESULT: PASS - persist fail-closed self-check" -ForegroundColor Green
    Write-Host " Honesty: unit+needles(+gate). Not mesh probe. Not 48h soak." -ForegroundColor DarkGray
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
}

Write-Host (" RESULT: FAIL ({0} checks)" -f $fail) -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Cyan
exit 1
