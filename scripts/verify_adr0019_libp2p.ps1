# ADR 0019 local verify (Windows)
# From Experimental repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\verify_adr0019_libp2p.ps1
# Optional:
#   .\scripts\verify_adr0019_libp2p.ps1 -Evidence
#   .\scripts\verify_adr0019_libp2p.ps1 -LabsOnly

param(
    [switch]$Evidence,
    [switch]$LabsOnly,
    [switch]$UnitOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$pyArgs = @("scripts\verify_adr0019_libp2p.py")
if ($Evidence) { $pyArgs += "--evidence" }
if ($LabsOnly) { $pyArgs += "--labs-only" }
if ($UnitOnly) { $pyArgs += "--unit-only" }

Write-Host "Running: python $($pyArgs -join ' ')"
& python @pyArgs
exit $LASTEXITCODE
