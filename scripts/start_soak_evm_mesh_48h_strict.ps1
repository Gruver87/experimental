# STRICT 48h Experimental prod mesh AFTER EVM preflight (Phase 3 bar + mempool parity).
# Runs evm_pre_48h_harness.py then start_soak_prod_mesh_48h_strict.ps1.
# Distinct evidence from default evm48pass1 (IntervalSec=300, non-Strict).
#
#   .\scripts\start_soak_evm_mesh_48h_strict.ps1
#   .\scripts\start_soak_evm_mesh_48h_strict.ps1 -SkipRebuild
#   .\scripts\start_soak_evm_mesh_48h_strict.ps1 -PreflightOnly
#
# Honesty: NOT EVM-only 48h / not geth / not EIP-4844 / not mainnet / not BLS.
param(
    [int]$Hours = 48,
    [int]$IntervalSec = 60,
    [string]$LogFile = "logs/soak_48h_evm_strict.log",
    [string]$ReportFile = "logs/soak_report_48h_evm_strict.json",
    [switch]$SkipRebuild,
    [switch]$SkipEvmHarness,
    [switch]$SkipPreflight,
    [switch]$PreflightOnly,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

Write-Host "STRICT 48h post-EVM prod mesh soak" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s Strict + FullHarnessEvery=6" -ForegroundColor DarkGray
Write-Host "  NOT default evm48pass1 / NOT EVM-only 48h / NOT mainnet" -ForegroundColor DarkGray
Write-Host "  log=$LogFile report=$ReportFile" -ForegroundColor DarkGray

if (-not $SkipPreflight) {
    if ($SkipRebuild) {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -SkipBuild -KeepVolumes
    } else {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -KeepVolumes
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: docker_prod_3node. Do not start EVM STRICT soak." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if (-not $SkipEvmHarness) {
    Write-Host "EVM pre-48h harness (labs + gate + probe + prod_evm_smoke)..." -ForegroundColor Cyan
    python scripts/evm_pre_48h_harness.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: evm_pre_48h_harness. Do not start EVM STRICT soak." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

$strictArgs = @{
    Hours = $Hours
    IntervalSec = $IntervalSec
    LogFile = $LogFile
    ReportFile = $ReportFile
    # Mesh already rebuilt / EVM-preflighted above — skip nested rebuild.
    SkipRebuild = $true
    SkipPreflight = $SkipPreflight
    PreflightOnly = $PreflightOnly
    Foreground = $Foreground
}

& (Join-Path $ScriptDir "start_soak_prod_mesh_48h_strict.ps1") @strictArgs
exit $LASTEXITCODE
