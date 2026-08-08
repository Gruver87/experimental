# ADR 0019 HARD local verify (Windows)
# From Experimental repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p_hard.ps1
#
# Optional:
#   .\scripts\verify_adr0019_libp2p_hard.ps1 -Rebuild
#   .\scripts\verify_adr0019_libp2p_hard.ps1 -Evidence
#   .\scripts\verify_adr0019_libp2p_hard.ps1 -KeepGoing
#   .\scripts\verify_adr0019_libp2p_hard.ps1 -SkipCargo

param(
    [switch]$Rebuild,
    [switch]$Evidence,
    [switch]$KeepGoing,
    [switch]$SkipCargo,
    [switch]$SkipLabs,
    [switch]$SkipUnits,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$pyArgs = @("scripts\verify_adr0019_libp2p_hard.py")
if ($Rebuild) { $pyArgs += "--rebuild" }
if ($Evidence) { $pyArgs += "--evidence" }
if ($KeepGoing) { $pyArgs += "--keep-going" }
if ($SkipCargo) { $pyArgs += "--skip-cargo" }
if ($SkipLabs) { $pyArgs += "--skip-labs" }
if ($SkipUnits) { $pyArgs += "--skip-units" }
if ($Quiet) { $pyArgs += "-q" }

Write-Host "HARD verify: python $($pyArgs -join ' ')"
Write-Host "honesty: Experimental R&D only - not tip proof / not prod libp2p mesh"
& python @pyArgs
exit $LASTEXITCODE
