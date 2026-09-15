# Stop background soak_monitor / LR chaos_pulse / sidecar (duplicate soaks).
# Does NOT match start_* orchestrators — those call this script and would
# self-kill if listed (false abort before mesh rebuild).
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$selfPid = $PID
$parentPid = $null
try {
    $parentPid = (Get-CimInstance Win32_Process -Filter "ProcessId=$selfPid" -ErrorAction SilentlyContinue).ParentProcessId
} catch { }

$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.ProcessId -ne $selfPid -and
        ($null -eq $parentPid -or $_.ProcessId -ne $parentPid) -and
        (
            ($_.Name -eq 'powershell.exe' -and (
                $_.CommandLine -match 'soak_monitor\.ps1' -or
                $_.CommandLine -match 'long_range_lab_chaos_pulse\.ps1' -or
                $_.CommandLine -match 'health_watch\.ps1'
            )) -or
            (($_.Name -eq 'python.exe' -or $_.Name -eq 'python') -and (
                $_.CommandLine -match 'mempool_validation_sidecar\.py'
            ))
        )
    }

if (-not $procs) {
    Write-Host "OK: no soak_monitor/chaos_pulse/sidecar processes found" -ForegroundColor Green
    if (Test-Path (Join-Path $Root "logs/soak_active.json")) {
        Remove-Item (Join-Path $Root "logs/soak_active.json") -Force
    }
    exit 0
}

Write-Host "Found $($procs.Count) soak/chaos process(es):" -ForegroundColor Yellow
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if ($cmd.Length -gt 120) { $cmd = $cmd.Substring(0, 120) + "..." }
    Write-Host "  PID $($p.ProcessId): $cmd" -ForegroundColor DarkGray
}

if (-not $Force) {
    Write-Host "Re-run with -Force to stop them." -ForegroundColor Yellow
    exit 1
}

foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID $($p.ProcessId)" -ForegroundColor Green
}

$active = Join-Path $Root "logs/soak_active.json"
if (Test-Path $active) { Remove-Item $active -Force }
Write-Host "OK: soak monitors stopped" -ForegroundColor Green
exit 0
