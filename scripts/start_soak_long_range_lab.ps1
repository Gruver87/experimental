# ADR 0017 Long-Range lab soak (NOT prod mesh 18180, NOT libp2p 48h claim).
# Default: 2h on ports 29080-29082. Use -Hours 48 only after a 2h PASS.
#
#   .\scripts\start_soak_long_range_lab.ps1
#   .\scripts\start_soak_long_range_lab.ps1 -Intensify   # 2h stress preflight (not 48h proof)
#   .\scripts\start_soak_long_range_lab.ps1 -Hours 48
param(
    [int]$Hours = 2,
    [int]$IntervalSec = 0,
    [int]$Port = 29080,
    [int[]]$Ports = @(),
    [switch]$SkipBuild,
    [switch]$SkipPreflight,
    [switch]$SkipTipGrowthSmoke,
    [switch]$Foreground,
    # 2h stress: denser probes, tip-stagnant 5m, BLOCK_TIME=5, follower bounce chaos.
    # Surfaces reconnect/ban/mesh_min races faster. Does NOT prove 48h durability.
    [switch]$Intensify,
    [string]$LogFile = "",
    [string]$ReportFile = "",
    # Tip-dead hard-FAIL (lab honesty). Default: 1h for Hours>=48, 30m for shorter.
    [int]$TipStagnantFailAfterSec = 0
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

if ($Hours -lt 1) { throw "Hours must be >= 1" }
if ($Intensify -and $Hours -gt 2) {
    throw "REFUSE: -Intensify is 2h stress preflight only (not a 48h claim). Drop -Intensify or use -Hours 2."
}
if ($Intensify) {
    $Hours = 2
}
if (-not $Ports -or $Ports.Count -eq 0) {
    $Ports = @(29080, 29081, 29082)
}
foreach ($p in $Ports) {
    if ($p -in @(18180, 18181, 18182)) {
        throw "REFUSE: Long-Range soak must not use prod mesh ports 18180-18182"
    }
}
# 48h: prefer 300s intervals (HOL-safe). Intensify: dense 15s. Else 60s for 2h.
if ($IntervalSec -le 0) {
    if ($Intensify) { $IntervalSec = 15 }
    elseif ($Hours -ge 48) { $IntervalSec = 300 }
    else { $IntervalSec = 60 }
}
if ($TipStagnantFailAfterSec -le 0) {
    if ($Intensify) { $TipStagnantFailAfterSec = 300 }
    elseif ($Hours -ge 48) { $TipStagnantFailAfterSec = 3600 }
    else { $TipStagnantFailAfterSec = 1800 }
}
if (-not $LogFile) {
    if ($Intensify) { $LogFile = "logs/soak_2h_long_range_lab.intensify.log" }
    elseif ($Hours -ge 48) { $LogFile = "logs/soak_48h_long_range_lab.log" }
    else { $LogFile = "logs/soak_2h_long_range_lab.log" }
}
if (-not $ReportFile) {
    if ($Intensify) { $ReportFile = "logs/soak_report_2h_long_range_lab.intensify.json" }
    elseif ($Hours -ge 48) { $ReportFile = "logs/soak_report_48h_long_range_lab.json" }
    else { $ReportFile = "logs/soak_report_2h_long_range_lab.json" }
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
if ($Intensify) {
    Write-Host "  MODE=INTENSIFY (2h stress: BLOCK_TIME=5, probe=15s, tip_stagnant=5m, follower bounce)" -ForegroundColor Yellow
    Write-Host "  honesty: intensify PASS is NOT a 48h claim" -ForegroundColor Yellow
}
Write-Host "  hours=$Hours ports=$($Ports -join ',') interval=${IntervalSec}s tip_stagnant_fail_after=${TipStagnantFailAfterSec}s" -ForegroundColor DarkGray
Write-Host "  log=$LogFile report=$ReportFile" -ForegroundColor DarkGray
Write-Host "  OPS: leave PC awake (no sleep/hibernate) for the full wall-clock" -ForegroundColor Yellow

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
$composeArgs = @("-p", "abs-lr-lab", "-f", "docker-compose.long_range.lab.yml")
if ($Intensify) {
    $composeArgs += @("-f", "docker-compose.long_range.lab.intensify.yml")
}
$composeArgs += "up", "-d"
if (-not $SkipBuild) { $composeArgs += "--build" }
docker compose @composeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "4. seed WS checkpoint (committee) + restart tip gate" -ForegroundColor Cyan
python scripts/seed_long_range_lab_ws.py --restart
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "5. live honesty + tip-gate probe (all lab HTTP ports)" -ForegroundColor Cyan
python scripts/long_range_lab_live_probe.py --all-nodes
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipTipGrowthSmoke) {
    Write-Host "5b. tip-growth smoke (refuse start if tip dead)" -ForegroundColor Cyan
    python scripts/long_range_lab_tip_growth_smoke.py --timeout-sec 180 --min-advance 2
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$gitSha = "unknown"
try { $gitSha = (git rev-parse HEAD 2>$null).Trim() } catch { }
$active = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    tip_stagnant_fail_after_sec = $TipStagnantFailAfterSec
    ports = @($Ports)
    strict = $false
    intensify = [bool]$Intensify
    started_at = (Get-Date -Format "o")
    git_sha = $gitSha
    note = $(if ($Intensify) {
        "ADR 0017 Long-Range LAB INTENSIFY 2h - not 48h proof - not prod 778888 - not BLS"
    } else {
        "ADR 0017 Long-Range LAB mesh soak - not prod 778888 - not BLS - not libp2p 3c801b87"
    })
}
$active | ConvertTo-Json | Set-Content -Path "logs/soak_active.json" -Encoding UTF8

$soakArgs = @{
    Hours = $Hours
    IntervalSec = $IntervalSec
    Ports = $Ports
    LogFile = $LogFile
    ReportFile = $ReportFile
    TipStagnantFailAfterSec = $TipStagnantFailAfterSec
}
if ($Intensify) {
    # Dense full harness without Strict delta=0 (5s tip ticks make delta=1 normal).
    $soakArgs.AlwaysFullHarness = $true
}

if ($Foreground) {
    if ($Intensify) {
        Write-Host "Foreground intensify: start chaos_pulse in a second terminal:" -ForegroundColor Yellow
        Write-Host "  .\scripts\long_range_lab_chaos_pulse.ps1 -Hours $Hours -LogFile '$LogFile'" -ForegroundColor DarkGray
    }
    & (Join-Path $ScriptDir "soak_monitor.ps1") @soakArgs
    exit $LASTEXITCODE
}

$portsCsv = ($Ports -join ",")
$alwaysFullFlag = if ($Intensify) { " -AlwaysFullHarness" } else { "" }
$cmdLine = @(
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden",
    "-Command `"& '$ScriptDir\soak_monitor.ps1' -Hours $Hours -IntervalSec $IntervalSec -Ports $portsCsv -LogFile '$LogFile' -ReportFile '$ReportFile' -TipStagnantFailAfterSec $TipStagnantFailAfterSec$alwaysFullFlag`""
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

$chaosPid = $null
if ($Intensify) {
    $chaosCmd = @(
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden",
        "-Command `"& '$ScriptDir\long_range_lab_chaos_pulse.ps1' -Hours $Hours -LogFile '$LogFile'`""
    ) -join " "
    $chaos = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine      = $chaosCmd
        CurrentDirectory = $Root
    }
    if ($chaos.ReturnValue -eq 0 -and $chaos.ProcessId) {
        $chaosPid = [int]$chaos.ProcessId
        $active.chaos_pid = $chaosPid
        Write-Host "OK: chaos_pulse PID=$chaosPid" -ForegroundColor Green
    } else {
        Write-Host "WARN: chaos_pulse failed to spawn (soak continues without bounce)" -ForegroundColor Yellow
    }
}

$active | ConvertTo-Json | Set-Content -Path "logs/soak_active.json" -Encoding UTF8

Write-Host "OK: Long-Range lab soak started PID=$($created.ProcessId) (not yet PASS)" -ForegroundColor Green
Write-Host "  check:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  status: .\scripts\soak_status.ps1" -ForegroundColor DarkGray
Write-Host "  probe:  python scripts/long_range_lab_live_probe.py --all-nodes" -ForegroundColor DarkGray
Write-Host "  stop:   .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
Write-Host "  down:   docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml down -v" -ForegroundColor DarkGray
Write-Host "  honesty: lab-only; not BLS; not prod mesh; not mainnet" -ForegroundColor Yellow
if ($Intensify) {
    Write-Host "  intensify: PASS here is preflight only - still need plain/48h for B2" -ForegroundColor Yellow
}
exit 0

