# ADR 0021 Phase 4.1 — operator self-check (no soak, no image rebuild).
param(
    [switch]$SkipMesh,
    [switch]$RequireRust
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$argsList = @()
if ($SkipMesh) { $argsList += "--skip-mesh" }
if ($RequireRust) { $argsList += "--require-rust" }

Write-Host "ADR 0021 Phase 4.1+4.2+4.3 self-check" -ForegroundColor Cyan
Write-Host "  python scripts/verify_adr0021_phase1.py $($argsList -join ' ')" -ForegroundColor DarkGray
python scripts/verify_adr0021_phase1.py @argsList
exit $LASTEXITCODE
