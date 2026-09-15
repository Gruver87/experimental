# Mempool + validation STRICT soak (Experimental prod mesh).
#
# Does NOT auto-start unless you run this script. Operator-ordered only.
# PASS bar: soak_monitor STRICT (fail=0 mesh_warn=0) + sidecar refuse_fail=0
#           + mempool_store not demoted. NOT 48h / NOT mainnet / NOT Hybrid.
#
# Usage (repo root):
#   .\scripts\start_mempool_validation_soak.ps1              # default 5h
#   .\scripts\start_mempool_validation_soak.ps1 -Hours 2
#   .\scripts\start_mempool_validation_soak.ps1 -PreflightOnly
#   .\scripts\start_mempool_validation_soak.ps1 -SkipRebuild

param(
    [int]$Hours = 5,
    [int]$IntervalSec = 60,
    [int]$SidecarIntervalSec = 300,
    [switch]$SkipRebuild,
    [switch]$SkipHostAudit,
    [switch]$PreflightOnly,
    [switch]$NoSidecar
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$LogFile = "logs/soak_mempool_validation_${Hours}h.log"
$ReportFile = "logs/soak_report_mempool_validation_${Hours}h.json"
$SidecarLog = "logs/mempool_validation_sidecar.log"
$fail = 0

function Invoke-Check {
    param([string]$Name, [scriptblock]$Command, [switch]$Soft)
    Write-Host ""
    Write-Host (">>> " + $Name) -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $Command
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }
    if ($rc -eq 0) {
        Write-Host ("OK: " + $Name) -ForegroundColor Green
    } elseif ($Soft) {
        Write-Host ("WARN: " + $Name + " (soft, exit $rc)") -ForegroundColor Yellow
    } else {
        Write-Host ("FAIL: " + $Name + " (exit $rc)") -ForegroundColor Red
        $script:fail++
    }
}

Write-Host ""
Write-Host "MEMPOOL+VALIDATION STRICT soak prep (Experimental)" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s sidecar=${SidecarIntervalSec}s" -ForegroundColor DarkGray
Write-Host "  NOT 48h claim until report passed=true / NOT mainnet / NOT Hybrid" -ForegroundColor DarkGray

# Load .env into process (needed for sidecar JWT mint) without printing secrets.
$envPath = Join-Path $Root ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or ($line -notmatch "=")) { return }
        $i = $line.IndexOf("=")
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
        if ($k -and -not [Environment]::GetEnvironmentVariable($k)) {
            [Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
    Write-Host "  .env loaded for sidecar/smoke (values not printed)" -ForegroundColor DarkGray
}

& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force

if (-not $SkipHostAudit) {
    Invoke-Check "industrial_gate" { python scripts/industrial_gate.py }
    Invoke-Check "ADR0021 require-rust" { python scripts/verify_adr0021_phase1.py --require-rust --skip-mesh }
    Invoke-Check "mempool get_for_block unit" {
        python -m pytest -q tests/unit/test_mempool_get_for_block.py --tb=line
    }
    Invoke-Check "evm_mempool_load_harness" {
        python scripts/evm_mempool_load_harness.py --rounds 40 --workers 8 --batch 16
    }
}

if ($fail -gt 0) {
    Write-Host "ABORT: host preflight failed ($fail)" -ForegroundColor Red
    exit 1
}

if ($SkipRebuild) {
    Invoke-Check "docker_prod_3node keep (HARD - must succeed)" {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -SkipBuild -KeepVolumes
    }
} else {
    Invoke-Check "docker_prod_3node rebuild" {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -KeepVolumes
    }
}

Invoke-Check "probe_prod_mesh -Quick" { & (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick }
Invoke-Check "prepare_48h_soak" { & (Join-Path $ScriptDir "prepare_48h_soak.ps1") }
Invoke-Check "prod_evm_smoke" { python scripts/prod_evm_smoke.py }

if ($fail -gt 0) {
    Write-Host "ABORT: mesh preflight failed ($fail)" -ForegroundColor Red
    exit 1
}

if ($PreflightOnly) {
    Write-Host "RESULT: PASS preflight-only (soak NOT started)" -ForegroundColor Green
    exit 0
}

$gitSha = (git rev-parse --short HEAD 2>$null)
if (-not $gitSha) { $gitSha = "unknown" }
$active = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    strict = $true
    mempool_validation = $true
    sidecar_log = $SidecarLog
    started_at = (Get-Date -Format "o")
    git_sha = "$gitSha"
    note = "mempool+validation STRICT soak - NOT 48h evidence"
}
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$active | ConvertTo-Json | Set-Content -Path (Join-Path $Root "logs/soak_active.json") -Encoding UTF8

if (-not $NoSidecar) {
    $sidecarProc = Start-Process -FilePath "python" -ArgumentList @(
        "scripts/mempool_validation_sidecar.py",
        "--hours", "$Hours",
        "--interval-sec", "$SidecarIntervalSec",
        "--log-file", $SidecarLog
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Write-Host ("Sidecar started pid=" + $sidecarProc.Id) -ForegroundColor DarkGray
}

$soakProc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $ScriptDir "soak_monitor.ps1"),
    "-Hours", "$Hours",
    "-IntervalSec", "$IntervalSec",
    "-ProdMesh",
    "-Strict",
    "-LogFile", $LogFile,
    "-ReportFile", $ReportFile
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

Write-Host ""
Write-Host ("RESULT: mempool+validation STRICT soak STARTED (pid=" + $soakProc.Id + ")") -ForegroundColor Green
Write-Host "  Monitor: .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  Log:     $LogFile" -ForegroundColor DarkGray
Write-Host "  Sidecar: $SidecarLog" -ForegroundColor DarkGray
Write-Host "  Honesty: NOT 48h / NOT mainnet / NOT Hybrid" -ForegroundColor DarkGray
exit 0
