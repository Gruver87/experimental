# ADR 0017 Long-Range lab soak (NOT prod mesh 18180, NOT libp2p 48h claim).
# Default: 2h on ports 29080-29082. Use -Hours 48 only after a 2h PASS.
#
#   .\scripts\start_soak_long_range_lab.ps1
#   .\scripts\start_soak_long_range_lab.ps1 -Hours 48
param(
    [int]$Hours = 2,
    [int]$IntervalSec = 60,
    [int]$Port = 29080,
    [int[]]$Ports = @(),
    [switch]$SkipBuild,
    [switch]$SkipPreflight,
    [switch]$Foreground,
    [string]$LogFile = "",
    [string]$ReportFile = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

if ($Hours -lt 1) { throw "Hours must be >= 1" }
if (-not $Ports -or $Ports.Count -eq 0) {
    $Ports = @(29080, 29081, 29082)
}
foreach ($p in $Ports) {
    if ($p -in @(18180, 18181, 18182)) {
        throw "REFUSE: Long-Range soak must not use prod mesh ports 18180-18182"
    }
}
if (-not $LogFile) {
    $LogFile = if ($Hours -ge 48) { "logs/soak_48h_long_range_lab.log" } else { "logs/soak_2h_long_range_lab.log" }
}
if (-not $ReportFile) {
    $ReportFile = if ($Hours -ge 48) { "logs/soak_report_48h_long_range_lab.json" } else { "logs/soak_report_2h_long_range_lab.json" }
}

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}
New-Item -ItemType Directory -Force -Path "data/long_range_lab0" | Out-Null
New-Item -ItemType Directory -Force -Path "data/long_range_lab1" | Out-Null
New-Item -ItemType Directory -Force -Path "data/long_range_lab2" | Out-Null
New-Item -ItemType Directory -Force -Path "data/long_range_lab_committee" | Out-Null

Write-Host "Long-Range LAB soak (ADR 0017) - not prod mesh, not BLS, not mainnet" -ForegroundColor Cyan
Write-Host "  hours=$Hours ports=$($Ports -join ',') interval=${IntervalSec}s" -ForegroundColor DarkGray
Write-Host "  log=$LogFile report=$ReportFile" -ForegroundColor DarkGray

Write-Host "0. ensure lab Ed25519 committee pubkeys" -ForegroundColor Cyan
python scripts/gen_long_range_lab_committee.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipPreflight) {
    Write-Host "1. long_range_lab_2h_harness preflight" -ForegroundColor Cyan
    python scripts/long_range_lab_2h_harness.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "2. stop leftover soak monitors (prod/lab)" -ForegroundColor Cyan
& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "3. bring up abs-lr-lab compose (3-node)" -ForegroundColor Cyan
$composeArgs = @("-p", "abs-lr-lab", "-f", "docker-compose.long_range.lab.yml", "up", "-d")
if (-not $SkipBuild) { $composeArgs += "--build" }
docker compose @composeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "4. seed WS checkpoint (committee) + restart tip gate" -ForegroundColor Cyan
python scripts/seed_long_range_lab_ws.py --restart
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "5. live honesty + tip-gate probe (all lab HTTP ports)" -ForegroundColor Cyan
python scripts/long_range_lab_live_probe.py --all-nodes
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$gitSha = "unknown"
try { $gitSha = (git rev-parse HEAD 2>$null).Trim() } catch { }
$active = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    ports = @($Ports)
    strict = $false
    started_at = (Get-Date -Format "o")
    git_sha = $gitSha
    note = "ADR 0017 Long-Range LAB mesh soak - not prod 778888 - not BLS - not libp2p 3c801b87"
}
$active | ConvertTo-Json | Set-Content -Path "logs/soak_active.json" -Encoding UTF8

$soakArgs = @{
    Hours = $Hours
    IntervalSec = $IntervalSec
    Ports = $Ports
    LogFile = $LogFile
    ReportFile = $ReportFile
}

if ($Foreground) {
    & (Join-Path $ScriptDir "soak_monitor.ps1") @soakArgs
    exit $LASTEXITCODE
}

$portsCsv = ($Ports -join ",")
$cmdLine = @(
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden",
    "-Command `"& '$ScriptDir\soak_monitor.ps1' -Hours $Hours -IntervalSec $IntervalSec -Ports $portsCsv -LogFile '$LogFile' -ReportFile '$ReportFile'`""
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

$active.pid = [int]$created.ProcessId
$active | ConvertTo-Json | Set-Content -Path "logs/soak_active.json" -Encoding UTF8

Write-Host "OK: Long-Range lab soak started PID=$($created.ProcessId) (not yet PASS)" -ForegroundColor Green
Write-Host "  check:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  status: .\scripts\soak_status.ps1" -ForegroundColor DarkGray
Write-Host "  probe:  python scripts/long_range_lab_live_probe.py --all-nodes" -ForegroundColor DarkGray
Write-Host "  stop:   .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
Write-Host "  down:   docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml down -v" -ForegroundColor DarkGray
Write-Host "  honesty: lab-only; not BLS; not prod mesh; not mainnet" -ForegroundColor Yellow
exit 0
