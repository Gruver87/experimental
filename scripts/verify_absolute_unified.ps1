# Absolute Blockchain — unified Hybrid + Experimental verify
#
# One operator entrypoint for:
#   1) Ultimate Hybrid industrial path (TCP+TLS default mesh)
#   2) Experimental Profile F R&D units/labs
#   3) ADR 0019 rust-libp2p hard gate (standard/full)
#
# Usage (from Experimental repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\verify_absolute_unified.ps1
#   .\scripts\verify_absolute_unified.ps1 -Mode Quick
#   .\scripts\verify_absolute_unified.ps1 -Mode Standard
#   .\scripts\verify_absolute_unified.ps1 -Mode Full
#   .\scripts\verify_absolute_unified.ps1 -Mode Standard -RebuildLibp2p
#   .\scripts\verify_absolute_unified.ps1 -HybridRoot "C:\Users\vovun\Desktop\Absolute_Blockchain_Ultimate_Hybrid"
#
# Honesty: PASS != public mainnet / tip proof / prod libp2p cutover.
# Report: data\verify_absolute_unified.json

param(
    [ValidateSet("Quick", "Standard", "Full")]
    [string]$Mode = "Standard",
    [string]$HybridRoot = "",
    [double]$MinSoakHours = 48,
    [switch]$SkipHybrid,
    [switch]$SkipExperimentalRd,
    [switch]$SkipLibp2p,
    [switch]$RebuildLibp2p,
    [switch]$KeepGoing,
    [switch]$Quiet,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Help) {
    Write-Host ""
    Write-Host "verify_absolute_unified.ps1 - Hybrid + Experimental as one operator view"
    Write-Host ""
    Write-Host "  Quick      Hybrid quick + Experimental RD (skip ADR 0019 hard)"
    Write-Host "  Standard   Hybrid standard + Experimental RD + ADR 0019 hard"
    Write-Host "  Full       Hybrid industrial + Experimental RD + ADR 0019 hard"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\scripts\verify_absolute_unified.ps1"
    Write-Host "  .\scripts\verify_absolute_unified.ps1 -Mode Quick"
    Write-Host "  .\scripts\verify_absolute_unified.ps1 -Mode Full -MinSoakHours 48"
    Write-Host "  .\scripts\verify_absolute_unified.ps1 -RebuildLibp2p"
    Write-Host ""
    Write-Host "Report: data\verify_absolute_unified.json"
    Write-Host "Honesty: green != merged prod tree / != public mainnet / != libp2p cutover"
    Write-Host ""
    exit 0
}

$modeArg = $Mode.ToLowerInvariant()
$pyArgs = @(
    "scripts\verify_absolute_unified.py"
    "--mode", $modeArg
    "--min-soak-hours", "$MinSoakHours"
)
if ($HybridRoot) { $pyArgs += @("--hybrid-root", $HybridRoot) }
if ($SkipHybrid) { $pyArgs += "--skip-hybrid" }
if ($SkipExperimentalRd) { $pyArgs += "--skip-experimental-rd" }
if ($SkipLibp2p) { $pyArgs += "--skip-libp2p" }
if ($RebuildLibp2p) { $pyArgs += "--rebuild-libp2p" }
if ($KeepGoing) { $pyArgs += "--keep-going" }
if ($Quiet) { $pyArgs += "-q" }

Write-Host "UNIFIED verify: python $($pyArgs -join ' ')"
Write-Host "honesty: Hybrid TCP+TLS default + Experimental R&D - not one merged prod tree"
& python @pyArgs
exit $LASTEXITCODE
