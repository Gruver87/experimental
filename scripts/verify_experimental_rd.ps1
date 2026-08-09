# Verify Profile F experimental R&D (waves unit + labs).
# Usage:
#   .\scripts\verify_experimental_rd.ps1
#   .\scripts\verify_experimental_rd.ps1 -LabsOnly
#   .\scripts\verify_experimental_rd.ps1 -UnitOnly
param(
    [switch]$UnitOnly,
    [switch]$LabsOnly,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$argsList = @()
if ($UnitOnly) { $argsList += "--unit-only" }
if ($LabsOnly) { $argsList += "--labs-only" }
if ($Quiet) { $argsList += "-q" }

& python (Join-Path $PSScriptRoot "verify_experimental_rd.py") @argsList
exit $LASTEXITCODE
