# Self-check Experimental blockchain (live mesh + unit tests + industrial_gate).
#
# Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.
#
# Usage (from repo root):
#   .\scripts\check_blockchain.ps1
#   .\scripts\check_blockchain.ps1 -SkipTests
#   .\scripts\check_blockchain.ps1 -SkipLive
#   .\scripts\check_blockchain.ps1 -PytestAll
#   .\scripts\check_blockchain.ps1 -RequireSoak48h
#   .\scripts\check_blockchain.ps1 -Help
#
# Report: logs\check_blockchain.json

param(
    [switch]$SkipLive,
    [switch]$SkipTests,
    [switch]$SkipGate,
    [switch]$PytestAll,
    [switch]$RequireSoak48h,
    [int]$Wait = 0,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($Help) {
    Write-Host ""
    Write-Host "check_blockchain.ps1 - Experimental mesh + tests"
    Write-Host ""
    Write-Host "  Default: probe :18180-18182, unit slice, industrial_gate,"
    Write-Host "  honest 48h/5h soak status (soak is NOT started)."
    Write-Host ""
    Write-Host "  .\scripts\check_blockchain.ps1"
    Write-Host "  .\scripts\check_blockchain.ps1 -SkipTests"
    Write-Host "  .\scripts\check_blockchain.ps1 -SkipLive"
    Write-Host "  .\scripts\check_blockchain.ps1 -PytestAll   (full tests/ tree)"
    Write-Host "  .\scripts\check_blockchain.ps1 -RequireSoak48h"
    Write-Host ""
    Write-Host "Exit: 0 OK, 1 FAIL, 2 mesh unreachable"
    Write-Host "Report: logs\check_blockchain.json"
    Write-Host "Honesty: OK != mainnet. 48h PASS only if soak_report passed=true."
    Write-Host ""
    exit 0
}

$pyArgs = @("scripts/check_blockchain.py")
if ($SkipLive) { $pyArgs += "--skip-live" }
if ($SkipTests) { $pyArgs += "--skip-tests" }
if ($SkipGate) { $pyArgs += "--skip-gate" }
if ($PytestAll) { $pyArgs += "--pytest-all" }
if ($RequireSoak48h) { $pyArgs += "--require-soak-48h" }
if ($Wait -gt 0) { $pyArgs += @("--wait", "$Wait") }

python @pyArgs
exit $LASTEXITCODE
