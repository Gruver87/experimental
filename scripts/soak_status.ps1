# Quick status of the active prod mesh soak (no wait).
# Prefer logs/soak_active.json so 5h STRICT and 48h soaks both show.
param(
    [string]$LogGlob = "logs/soak_*h*.log",
    [string]$ReportFile = "logs/soak_report_48h_experimental.json"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$activePath = Join-Path $Root "logs/soak_active.json"
$log = $null
if (Test-Path $activePath) {
    try {
        $active = Get-Content $activePath -Raw | ConvertFrom-Json
        $candidate = Join-Path $Root ($active.log_file -replace '/', '\')
        if (Test-Path $candidate) {
            $log = $candidate
            if ($active.report_file) {
                $ReportFile = $active.report_file
            }
            Write-Host "Active soak (logs/soak_active.json)" -ForegroundColor Cyan
            Write-Host "  started: $($active.started_at) hours=$($active.hours)" -ForegroundColor DarkGray
        }
    } catch { }
}

if (-not $log) {
    $prefer48 = Join-Path $Root "logs/soak_48h_experimental.log"
    if (Test-Path $prefer48) {
        $log = $prefer48
    } else {
        $logs = Get-ChildItem -Path (Join-Path $Root $LogGlob) -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
        if (-not $logs) {
            Write-Host "No soak log matching $LogGlob" -ForegroundColor Yellow
            exit 1
        }
        if ($logs.Count -gt 1) {
            Write-Host "WARN: multiple soak logs - run .\scripts\stop_soak_monitors.ps1 -Force then restart_soak_prod_mesh.ps1" -ForegroundColor Yellow
            $logs | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor DarkGray }
        }
        $log = $logs[0].FullName
    }
}

$lines = Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue
$ts = '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
$startLine = ($lines | Select-String -Pattern "$ts health_watch start" | Select-Object -Last 1)
$lastMesh = ($lines | Select-String -Pattern "$ts OK mesh aligned" | Select-Object -Last 1)
$lastFail = ($lines | Select-String -Pattern "$ts FAIL" | Select-Object -Last 1)
$failCount = ($lines | Select-String -Pattern "$ts FAIL").Count
$meshOk = ($lines | Select-String -Pattern "$ts OK mesh aligned").Count
$done = ($lines | Select-String -Pattern "$ts health_watch done" | Select-Object -Last 1)
$monitors = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'soak_monitor\.ps1') })
$alive = $monitors.Count -gt 0

Write-Host "Soak status" -ForegroundColor Cyan
Write-Host "  log: $([System.IO.Path]::GetFileName($log))" -ForegroundColor DarkGray
if ($startLine) { Write-Host "  started: $($startLine.Line)" -ForegroundColor DarkGray }
if ($lastMesh) { Write-Host "  latest:  $($lastMesh.Line)" -ForegroundColor Green }
if ($lastFail -and $failCount -gt 0) { Write-Host "  last_fail: $($lastFail.Line)" -ForegroundColor Yellow }
Write-Host "  mesh_ok_cycles=$meshOk fail_lines=$failCount" -ForegroundColor DarkGray
Write-Host "  monitor: $(if ($alive) { 'ALIVE pid=' + (($monitors | ForEach-Object { $_.ProcessId }) -join ',') } else { 'none' })" -ForegroundColor $(if ($alive) { 'Green' } else { 'Red' })

if ($done) {
    Write-Host "  state: FINISHED" -ForegroundColor Green
} elseif ($alive) {
    Write-Host "  state: IN_PROGRESS" -ForegroundColor Yellow
} else {
    Write-Host "  state: DEAD (monitor gone before health_watch done)" -ForegroundColor Red
}

$reportPath = Join-Path $Root ($ReportFile -replace '/', '\')
if (Test-Path $reportPath) {
    try {
        $rep = Get-Content $reportPath -Raw | ConvertFrom-Json
        Write-Host "  report: $ReportFile hours=$($rep.hours_requested) passed=$($rep.passed)" -ForegroundColor DarkGray
    } catch { }
}

exit 0
