# Slice check: state_root lag reply + empty-wire + late-stash retry honesty.
# Run after this P2P probe fix. Does not start soak. Does not rebuild Docker.
param(
    [switch]$SkipLive,
    [switch]$Gate
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$fail = 0

Write-Host "1) unit tests (lag reply + empty wire)" -ForegroundColor Cyan
python -m pytest -q `
    tests/unit/test_state_root_probe_coalesce.py `
    tests/unit/test_wave54_state_consistency.py `
    tests/unit/test_v13129_p2p_state_root_outbound_honesty.py `
    tests/unit/test_v13135_p2p_tip_ownership_and_local_root.py `
    tests/unit/test_sync_solicit.py `
    tests/unit/test_p2p_dispatch.py `
    tests/unit/test_tip_safety_shadow.py `
    tests/unit/test_catchup_path_a.py `
    tests/unit/test_v1339_ffg_slash.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "RESULT: FAIL unit" -ForegroundColor Red
    $fail = 1
} else {
    Write-Host "RESULT: PASS unit" -ForegroundColor Green
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
    Write-Host "3) live mesh harness :18180-:18182 (image must include this Python)" -ForegroundColor Cyan
    python scripts/check_harness_probe.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "RESULT: FAIL live (or mesh down)" -ForegroundColor Yellow
        $fail = 1
    } else {
        Write-Host "RESULT: PASS live" -ForegroundColor Green
    }
}

if ($fail -ne 0) {
    Write-Host ""
    Write-Host "If unit PASS but live FAIL: rebuild so containers pick up Python:" -ForegroundColor DarkGray
    Write-Host "  .\scripts\docker_prod_3node.ps1 -KeepVolumes" -ForegroundColor DarkGray
    Write-Host "  .\scripts\probe_prod_mesh.ps1 -Quick" -ForegroundColor DarkGray
    Write-Host "  .\scripts\check_harness_probe.ps1" -ForegroundColor DarkGray
    exit 1
}
Write-Host "RESULT: PASS" -ForegroundColor Green
exit 0
