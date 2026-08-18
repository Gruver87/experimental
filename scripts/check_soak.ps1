# Periodic soak checker (5h STRICT or 48h). No wait. Safe to run anytime.
# Exit: 0 running/finished-pass, 1 dead/unexpected, 2 finished-fail.
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Get-SoakMonitor {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'soak_monitor\.ps1') }
}

function Write-KV([string]$K, [string]$V, [string]$Color = "Gray") {
    if ($Quiet) { return }
    Write-Host ("  {0,-16} {1}" -f $K, $V) -ForegroundColor $Color
}

$activePath = Join-Path $Root "logs/soak_active.json"
$active = $null
if (Test-Path $activePath) {
    try { $active = Get-Content $activePath -Raw | ConvertFrom-Json } catch { }
}

$log = $null
$reportFile = $null
$hoursRequested = $null
$startedAt = $null
$strict = $false
$intervalSec = 300

if ($active) {
    $candidate = Join-Path $Root (($active.log_file -replace '/', '\'))
    if (Test-Path $candidate) { $log = $candidate }
    if ($active.report_file) { $reportFile = $active.report_file }
    $hoursRequested = $active.hours
    $startedAt = $active.started_at
    $strict = [bool]$active.strict
    if ($active.interval_sec) { $intervalSec = [int]$active.interval_sec }
}

if (-not $log) {
    $preferred = @(
        (Join-Path $Root "logs\soak_48h_experimental.log"),
        (Join-Path $Root "logs\soak_5h_strict.log")
    )
    $logs = @(Get-ChildItem -Path (Join-Path $Root "logs\soak_*h*.log") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if ($logs) { $log = $logs[0].FullName }
    elseif (Test-Path $preferred[0]) { $log = $preferred[0] }
}

if (-not $reportFile) {
    if ($log -and ($log -match '5h_strict')) {
        $reportFile = "logs/soak_report_5h_strict.json"
    } elseif ($log -and ($log -match '48h_experimental')) {
        $reportFile = "logs/soak_report_48h_experimental.json"
    } else {
        $reportFile = "logs/soak_report_48h.json"
    }
}

$procs = @(Get-SoakMonitor)
$alive = $procs.Count -gt 0
$pidList = @($procs | ForEach-Object { $_.ProcessId }) -join ","

if (-not $Quiet) {
    Write-Host "Soak check" -ForegroundColor Cyan
}

if (-not $log) {
    Write-KV "state" "NO_LOG" "Yellow"
    Write-KV "monitor" $(if ($alive) { "ALIVE pid=$pidList" } else { "none" })
    if (-not $Quiet) {
        Write-Host "  start: .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
    }
    exit 1
}

$lines = @(Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue)
$ts = '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
$startLine = ($lines | Select-String -Pattern "$ts health_watch start" | Select-Object -Last 1)
$lastMesh = ($lines | Select-String -Pattern "$ts OK mesh aligned" | Select-Object -Last 1)
$lastFail = ($lines | Select-String -Pattern "$ts FAIL" | Select-Object -Last 1)
$done = ($lines | Select-String -Pattern "$ts health_watch done" | Select-Object -Last 1)
$failCount = @($lines | Select-String -Pattern "$ts FAIL").Count
$meshOk = @($lines | Select-String -Pattern "$ts OK mesh aligned").Count
$lastWrite = (Get-Item $log).LastWriteTime
$ageSec = [int]((Get-Date) - $lastWrite).TotalSeconds

$elapsedH = $null
if ($startedAt) {
    try { $elapsedH = [Math]::Round(((Get-Date) - [datetime]::Parse($startedAt)).TotalHours, 2) } catch { }
} elseif ($startLine -and $startLine.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
    try { $elapsedH = [Math]::Round(((Get-Date) - [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null)).TotalHours, 2) } catch { }
}

$remainH = $null
if ($null -ne $elapsedH -and $hoursRequested) {
    $remainH = [Math]::Round([Math]::Max(0, [double]$hoursRequested - $elapsedH), 2)
}

$state = "UNKNOWN"
$color = "Gray"
$exitCode = 0
$staleSec = [Math]::Max(180, ([int]$intervalSec * 2) + 60)
if ($done) {
    $reportPath = Join-Path $Root ($reportFile -replace '/', '\')
    $passed = $null
    if (Test-Path $reportPath) {
        try { $passed = (Get-Content $reportPath -Raw | ConvertFrom-Json).passed } catch { }
    }
    if ($passed -eq $true) {
        $state = "FINISHED_PASS"
        $color = "Green"
        $exitCode = 0
    } else {
        $state = "FINISHED_FAIL"
        $color = "Yellow"
        $exitCode = 2
    }
} elseif ($alive) {
    if ($ageSec -gt $staleSec) {
        $state = "RUNNING_STALE_LOG"
        $color = "Yellow"
        $exitCode = 1
    } else {
        $state = "RUNNING"
        $color = "Green"
        $exitCode = 0
    }
} elseif (Test-Path $activePath) {
    $state = "DEAD"
    $color = "Red"
    $exitCode = 1
} else {
    $state = "STOPPED"
    $color = "Yellow"
    $exitCode = 1
}

Write-KV "state" $state $color
Write-KV "strict" $(if ($strict) { "true (5h bar: fail=0 mesh_warn=0)" } else { "false (default 48h scoring)" })
if ($active -and $active.git_sha) { Write-KV "git_sha" $active.git_sha }
if ($active -and $null -ne $active.git_dirty) { Write-KV "git_dirty" $active.git_dirty }
if ($active -and $active.image_id) { Write-KV "image_id" $active.image_id }
Write-KV "monitor" $(if ($alive) { "ALIVE pid=$pidList" } else { "none" }) $(if ($alive) { "Green" } else { "Red" })
Write-KV "log" ([System.IO.Path]::GetFileName($log))
if ($hoursRequested) { Write-KV "hours" "$hoursRequested requested / elapsed=$elapsedH remain=$remainH" }
elseif ($null -ne $elapsedH) { Write-KV "elapsed_h" "$elapsedH" }
Write-KV "interval_sec" $intervalSec
Write-KV "stale_after_sec" $staleSec
Write-KV "log_age_sec" $ageSec
Write-KV "mesh_ok_cycles" $meshOk
Write-KV "fail_lines" $failCount $(if ($failCount -gt 0) { "Yellow" } else { "Gray" })
if ($startLine) { Write-KV "started" $startLine.Line.Trim() }
if ($lastMesh) { Write-KV "latest_mesh" $lastMesh.Line.Trim() "Green" }
if ($lastFail -and $failCount -gt 0) { Write-KV "last_fail" $lastFail.Line.Trim() "Yellow" }
if ($done) { Write-KV "done" $done.Line.Trim() }

$reportPath = Join-Path $Root ($reportFile -replace '/', '\')
if (Test-Path $reportPath) {
    try {
        $rep = Get-Content $reportPath -Raw | ConvertFrom-Json
        Write-KV "report" "$reportFile passed=$($rep.passed) hours=$($rep.hours_elapsed)/$($rep.hours_requested)"
    } catch { }
}

if (-not $Quiet) {
    Write-Host ""
    Write-Host "  re-check: .\scripts\check_soak.ps1" -ForegroundColor DarkGray
    Write-Host "  tail:     Get-Content $log -Tail 30" -ForegroundColor DarkGray
    Write-Host "  stop:     .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
    Write-Host "  note:     5h STRICT is not 48h evidence even if passed=true" -ForegroundColor DarkGray
    Write-Host "  48h:      .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
}

exit $exitCode
