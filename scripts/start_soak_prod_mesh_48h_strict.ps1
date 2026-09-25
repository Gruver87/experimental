# STRICT 48h Experimental prod mesh soak (libp2p / ADR 0020).
# Parity with mempool48pass1: IntervalSec=60, Strict, FullHarnessEvery=6 (long STRICT).
# Does NOT require P2P-TLS (Experimental industrial default is Noise, not TCP+TLS).
# Default 48h scoring (ind48pass1) is unchanged — this is a separate evidence pack.
#
#   .\scripts\start_soak_prod_mesh_48h_strict.ps1
#   .\scripts\start_soak_prod_mesh_48h_strict.ps1 -SkipRebuild
#   .\scripts\start_soak_prod_mesh_48h_strict.ps1 -PreflightOnly
param(
    [int]$Hours = 48,
    [int]$IntervalSec = 60,
    [string]$LogFile = "logs/soak_48h_libp2p_strict.log",
    [string]$ReportFile = "logs/soak_report_48h_libp2p_strict.json",
    [switch]$SkipRebuild,
    [switch]$SkipPreflight,
    [switch]$PreflightOnly,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

Write-Host "STRICT 48h Experimental prod mesh soak (libp2p)" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s Strict + FullHarnessEvery=6" -ForegroundColor DarkGray
Write-Host "  bar: fail=0 mesh_warn=0 (soft peer_probe/harness_timeout WARN OK)" -ForegroundColor DarkGray
Write-Host "  NOT default ind48pass1 / NOT mempool sidecar / NOT TLS-required / NOT mainnet" -ForegroundColor DarkGray
Write-Host "  log=$LogFile report=$ReportFile" -ForegroundColor DarkGray

& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipPreflight) {
    if ($SkipRebuild) {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -SkipBuild -KeepVolumes
    } else {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -KeepVolumes
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: docker_prod_3node. Do not start STRICT soak." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    & (Join-Path $ScriptDir "prepare_48h_soak.ps1") -Hours $Hours -IntervalSec $IntervalSec
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: 48h prepare. Do not start STRICT soak." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    & (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: probe_prod_mesh -Quick." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($PreflightOnly) {
    Write-Host "RESULT: PASS preflight-only (STRICT soak NOT started)" -ForegroundColor Green
    exit 0
}

$gitTag = "unknown"
$gitSha = "unknown"
$gitDirty = $false
try {
    $desc = git describe --tags --abbrev=0 2>$null
    if ($desc) { $gitTag = $desc.Trim() }
    $sha = git rev-parse HEAD 2>$null
    if ($sha) { $gitSha = $sha.Trim() }
    $gitDirty = [bool](git status --porcelain 2>$null)
} catch { }

$imageId = ""
try {
    $imageId = (docker inspect abs-blockchain-prod:local --format "{{.Id}}" 2>$null | Out-String).Trim()
} catch { }

$activeMeta = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    strict = $true
    full_harness_every = 6
    started_at = (Get-Date -Format "o")
    git_tag = $gitTag
    git_sha = $gitSha
    git_dirty = $gitDirty
    image_id = $imageId
    note = "STRICT 48h libp2p prod mesh - parity with mempool48pass1 interval/bar - not default ind48pass1"
}
$activePath = Join-Path $Root "logs/soak_active.json"
$activeMeta | ConvertTo-Json | Set-Content -Path $activePath -Encoding UTF8

python scripts/record_evidence_run.py `
    --name soak_monitor_48h_libp2p_strict `
    --result IN_PROGRESS `
    --command ".\scripts\start_soak_prod_mesh_48h_strict.ps1" `
    --artifact $LogFile `
    --git-tag $gitTag `
    2>$null | Out-Null

$soakScript = Join-Path $ScriptDir "soak_monitor.ps1"
$soakArgs = @(
    "-Hours", $Hours,
    "-IntervalSec", $IntervalSec,
    "-ProdMesh",
    "-Strict",
    "-LogFile", $LogFile,
    "-ReportFile", $ReportFile
)

if ($Foreground) {
    & $soakScript @soakArgs
    exit $LASTEXITCODE
}

$cmdLine = @(
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden",
    "-File `"$soakScript`"",
    "-Hours $Hours",
    "-IntervalSec $IntervalSec",
    "-ProdMesh -Strict",
    "-LogFile `"$LogFile`"",
    "-ReportFile `"$ReportFile`""
) -join " "
$created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine      = $cmdLine
    CurrentDirectory = $Root
}
if ($created.ReturnValue -ne 0 -or -not $created.ProcessId) {
    Write-Host "FAIL: could not spawn soak_monitor (Win32 Create=$($created.ReturnValue))" -ForegroundColor Red
    exit 1
}
Start-Sleep -Seconds 3
$alive = Get-CimInstance Win32_Process -Filter "ProcessId=$($created.ProcessId)" -ErrorAction SilentlyContinue
if (-not $alive) {
    Write-Host "FAIL: soak_monitor PID $($created.ProcessId) died immediately" -ForegroundColor Red
    exit 1
}

$activeMeta.pid = [int]$created.ProcessId
$activeMeta | ConvertTo-Json | Set-Content -Path $activePath -Encoding UTF8

Write-Host "OK: STRICT 48h libp2p soak started PID=$($created.ProcessId) (not yet PASS)" -ForegroundColor Green
Write-Host "  check:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  stop:   .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
Write-Host "  claim PASS only if hours~48 and report passed=true (Strict)" -ForegroundColor Yellow
exit 0
