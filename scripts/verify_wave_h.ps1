# Wave H operator self-check (audit honesty fixes).
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

Write-Host "WAVE H self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave H honesty pack"
python -m pytest -q tests/unit/test_wave_h_honesty_fixes.py tests/unit/test_sphincs_plus_fail_closed.py tests/unit/test_wave_f_input_validators_fail_closed.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave H unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave H unit tests" -ForegroundColor Green
}

Step "2) source needles"
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
$nat = Get-Content -Raw -Path (Join-Path $Root "runtime\native_capabilities.py")
$sph = Get-Content -Raw -Path (Join-Path $Root "crypto\sphincs_plus.py")
$val = Get-Content -Raw -Path (Join-Path $Root "middleware\validators.py")
$br = Get-Content -Raw -Path (Join-Path $Root "bridge\abs_bridge.py")
if ($http -notmatch "Wave H: with peers/mesh expected") {
    Write-Host "FAIL: ready wire-gate missing" -ForegroundColor Red
    $fail++
} elseif ($nat -notmatch "forbids demote") {
    Write-Host "FAIL: demote-require missing" -ForegroundColor Red
    $fail++
} elseif ($sph -notmatch "verify backend not available") {
    Write-Host "FAIL: SPHINCS verify still stub False?" -ForegroundColor Red
    $fail++
} elseif ($val -notmatch "to_satoshi") {
    Write-Host "FAIL: validators not satoshi" -ForegroundColor Red
    $fail++
} elseif ($br -notmatch "BRIDGE_FEE_BPS") {
    Write-Host "FAIL: bridge fee BPS missing" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave H source needles" -ForegroundColor Green
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
    Write-Host "RESULT: FAIL Wave H ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave H self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_g.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
