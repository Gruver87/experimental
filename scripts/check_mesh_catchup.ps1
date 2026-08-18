# Slice check: catch-up #340 (false slash / PathA reorg) + live ready/peers.
# Does not start soak. Does not rebuild Docker.
param(
    [switch]$SkipLive,
    [switch]$SkipUnit,
    [switch]$Gate
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$fail = 0

if (-not $SkipUnit) {
    Write-Host "1) unit tests (tip-safety bind + PathA reorg + hash-idempotent slash)" -ForegroundColor Cyan
    python -m pytest -q `
        tests/unit/test_tip_safety_shadow.py `
        tests/unit/test_catchup_path_a.py `
        tests/unit/test_v1339_ffg_slash.py `
        tests/unit/test_silent_except_honesty.py `
        tests/unit/test_state_root_probe_coalesce.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "RESULT: FAIL unit" -ForegroundColor Red
        $fail = 1
    } else {
        Write-Host "RESULT: PASS unit" -ForegroundColor Green
    }
}

if ($Gate) {
    Write-Host "2) industrial_gate.py" -ForegroundColor Cyan
    python scripts/industrial_gate.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "RESULT: FAIL gate" -ForegroundColor Red
        $fail = 1
    } else {
        Write-Host "RESULT: PASS gate" -ForegroundColor Green
    }
}

if (-not $SkipLive) {
    Write-Host "3) live mesh :18180-:18182 (ready 200, gap<=1, peers>=2, consist/topo/wire)" -ForegroundColor Cyan
    python scripts/check_mesh_catchup.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "RESULT: FAIL live (or mesh down)" -ForegroundColor Yellow
        $fail = 1
    } else {
        Write-Host "RESULT: PASS live" -ForegroundColor Green
    }
}

if ($fail -ne 0) {
    Write-Host ""
    Write-Host "If unit PASS but live FAIL: image must include this Python, then:" -ForegroundColor DarkGray
    Write-Host "  .\scripts\docker_prod_3node.ps1 -KeepVolumes" -ForegroundColor DarkGray
    Write-Host "  .\scripts\check_mesh_catchup.ps1" -ForegroundColor DarkGray
    Write-Host "Soak is not this script. Do not claim soak from a PASS here." -ForegroundColor DarkGray
    exit 1
}
Write-Host "RESULT: PASS" -ForegroundColor Green
Write-Host "Soak not run." -ForegroundColor DarkGray
exit 0
