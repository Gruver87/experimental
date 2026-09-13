# Release gate - unit/static verification before tag/push.
# Honesty (Wave H): default path is NOT a live mesh probe.
# Add -RequireMesh to run probe_prod_mesh -Quick, or -Mainnet for cutover gates.
param(
    [switch]$FullNativeBuild,
    [switch]$Mainnet,
    [switch]$RequireMesh,
    [string]$CeremonyDir = "",
    [switch]$ProdSmokeSpawn,
    [switch]$Live
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$args = @("-SkipNativeBuild")
if ($FullNativeBuild) {
    $args = @()
}
& "$PSScriptRoot\test_all.ps1" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($RequireMesh) {
    Write-Host "==> RequireMesh: probe_prod_mesh -Quick" -ForegroundColor Cyan
    & "$PSScriptRoot\probe_prod_mesh.ps1" -Quick
    if ($LASTEXITCODE -ne 0) {
        Write-Host "RESULT: FAIL release gate (mesh probe)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Mainnet) {
    $pyArgs = @("scripts/mainnet_readiness.py")
    if ($CeremonyDir) {
        $pyArgs += @("--ceremony-dir", $CeremonyDir)
    }
    if ($ProdSmokeSpawn) {
        $pyArgs += "--prod-smoke-spawn"
    }
    if ($Live) {
        $pyArgs += @("--live", "--base-url", "http://127.0.0.1:8080")
    }
    python @pyArgs
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "RESULT: PASS unit/static release gate" -ForegroundColor Green
Write-Host "  NOT mesh probe / NOT soak / NOT mainnet cutover" -ForegroundColor DarkGray
Write-Host "  Live mesh: .\scripts\release_gate.ps1 -RequireMesh" -ForegroundColor DarkGray
Write-Host "  Cutover:   .\scripts\release_gate.ps1 -Mainnet" -ForegroundColor DarkGray
exit 0
