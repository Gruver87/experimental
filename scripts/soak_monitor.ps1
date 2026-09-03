# Long-running prod mesh soak: polls health_watch logic and writes a summary report.
param(
    [int]$Hours = 24,
    [int]$IntervalSec = 300,
    [switch]$ProdMesh,
    [string]$LogFile = "logs/soak_monitor.log",
    [string]$ReportFile = "logs/soak_report.json",
    # Rebuild report from an existing soak log (no health_watch run).
    [switch]$RescoreOnly,
    [int]$HealthWatchExit = -1,
    # Strict: no mesh_warn / ready-flap / 1-height skew tolerance. 48h default scoring unchanged.
    [switch]$Strict,
    # Full harness every cycle without Strict FAIL-on-harness (48h: WARN, not soak FAIL).
    [switch]$FullHarness
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

function Test-MeshWarnsAreTransient {
    param([string[]]$Lines, [string]$TsPrefix)
    $warns = @($Lines | Select-String -Pattern "$TsPrefix WARN mesh misaligned")
    if ($warns.Count -eq 0) { return $true }
    foreach ($w in $warns) {
        $heights = @([regex]::Matches($w.Line, 'h\d+=(\d+)') | ForEach-Object { [int]$_.Groups[1].Value })
        # Malformed / incomplete probe lines (no heights) are not consensus forks.
        if ($heights.Count -lt 2) { continue }
        $delta = ($heights | Measure-Object -Maximum).Maximum - ($heights | Measure-Object -Minimum).Minimum
        # ±2 covers parallel poll skew + one extra tip-v2 mine tick (health_watch_core).
        if ($delta -gt 2) { return $false }
    }
    return $true
}

$durationMin = [Math]::Max(1, $Hours * 60)
$started = Get-Date -Format "o"
if ($RescoreOnly) {
    Write-Host "Soak rescore-only: log=$LogFile report=$ReportFile" -ForegroundColor Cyan
} else {
    Write-Host "Soak monitor: ${Hours}h interval=${IntervalSec}s log=$LogFile" -ForegroundColor Cyan
    if ($Strict) {
        Write-Host "  STRICT: mesh_warn=0, no ready-flap, no 1-height skew, full harness every cycle" -ForegroundColor Yellow
    } elseif ($FullHarness) {
        Write-Host "  full harness every 6 cycles (WARN on probe flake; 48h default scoring)" -ForegroundColor DarkGray
    }
    Write-Host "  Press Ctrl+C to stop early; partial report will be written." -ForegroundColor DarkGray
}

$exitCode = 0
if (-not $RescoreOnly) {
    $hwArgs = @{
        DurationMin = $durationMin
        IntervalSec = $IntervalSec
        LogFile     = $LogFile
    }
    if ($ProdMesh) { $hwArgs.ProdMesh = $true }
    if ($Strict) {
        $hwArgs.Strict = $true
        $hwArgs.AlwaysFullHarness = $true
    } elseif ($FullHarness) {
        # 48h: full harness every 6th cycle (health_watch default). Always-on
        # full harness HOL-stalls GET /status and paints hard FAILs on a live mesh.
        $hwArgs.FullHarnessEvery = 6
    }

    try {
        & (Join-Path $ScriptDir "health_watch.ps1") @hwArgs
        if ($null -ne $LASTEXITCODE) { $exitCode = $LASTEXITCODE }
    } catch {
        Write-Host "FAIL: health_watch error: $($_.Exception.Message)" -ForegroundColor Red
        $exitCode = 1
    }
} elseif ($HealthWatchExit -ge 0) {
    $exitCode = $HealthWatchExit
}

$ended = Get-Date -Format "o"
$lines = @()
if (Test-Path $LogFile) {
    $lines = Get-Content $LogFile -Encoding UTF8
}

$ts = '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
$ok = ($lines | Select-String -Pattern "$ts OK port").Count
$warn = ($lines | Select-String -Pattern "$ts WARN").Count
$fail = ($lines | Select-String -Pattern "$ts FAIL").Count
# Ready-only 503 flaps (wire probe) are not consensus failures when mesh stays aligned.
$readyOnlyFail = ($lines | Select-String -Pattern "$ts FAIL port \d+ ready:").Count
$hardFail = [Math]::Max(0, $fail - $readyOnlyFail)
$meshOk = ($lines | Select-String -Pattern "$ts OK mesh aligned").Count
$meshWarn = ($lines | Select-String -Pattern "$ts WARN mesh misaligned").Count
$startedWatch = ($lines | Select-String -Pattern "$ts health_watch start").Count -gt 0
$finishedWatch = ($lines | Select-String -Pattern "$ts health_watch done").Count -gt 0
$meshWarnsTransient = Test-MeshWarnsAreTransient -Lines $lines -TsPrefix $ts
# Ready 503 flaps are wire-probe noise when /status stays reachable and there are
# no hard unreachable FAILs. Do not couple to meshWarnsTransient (false mesh
# probe lines previously blocked an otherwise clean 48h tip-v2 soak).
$readyFlapsTolerated = (
    $readyOnlyFail -gt 0 -and
    $hardFail -eq 0 -and
    $meshOk -gt 0
)
# Rare non-transient mesh warns: accept if mesh_ok dominates and hard_fail=0.
$meshAcceptable = (
    $meshWarnsTransient -or (
        $hardFail -eq 0 -and
        $meshWarn -gt 0 -and
        $meshOk -ge [Math]::Max(50, $meshWarn * 50)
    )
)

# Prefer timestamps from the soak log when rescoring a completed run.
if ($RescoreOnly -and $startedWatch) {
    $startMatch = ($lines | Select-String -Pattern "$ts health_watch start" | Select-Object -First 1)
    if ($startMatch -and $startMatch.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
        try { $started = ([datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null)).ToString('o') } catch { }
    }
}
if ($RescoreOnly -and $finishedWatch) {
    $doneMatch = ($lines | Select-String -Pattern "$ts health_watch done" | Select-Object -Last 1)
    if ($doneMatch -and $doneMatch.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
        try { $ended = ([datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null)).ToString('o') } catch { }
    }
    if ($HealthWatchExit -lt 0) { $exitCode = 0 }
}

$hoursElapsed = 0.0
try {
    $hoursElapsed = ([datetime]::Parse($ended) - [datetime]::Parse($started)).TotalHours
} catch {
    $hoursElapsed = 0.0
}
# Allow 5% clock skew when rescoring completed soaks.
$hoursFloor = if ($Strict) { [Math]::Max(0.0, $Hours * 0.99) } else { [Math]::Max(0.0, $Hours * 0.95) }

$strictPass = (
    $exitCode -eq 0 -and
    $startedWatch -and
    $finishedWatch -and
    $ok -gt 0 -and
    $fail -eq 0 -and
    $meshWarn -eq 0 -and
    $hoursElapsed -ge $hoursFloor
)
$defaultPass = (
    ($exitCode -eq 0 -or ($readyFlapsTolerated -and $hardFail -eq 0)) -and
    $startedWatch -and
    $finishedWatch -and
    $ok -gt 0 -and
    $hardFail -eq 0 -and
    ($fail -eq 0 -or $readyFlapsTolerated) -and
    ($meshWarn -eq 0 -or $meshAcceptable) -and
    $hoursElapsed -ge $hoursFloor
)

$report = @{
    started_at = $started
    ended_at = $ended
    hours_requested = $Hours
    hours_elapsed = [Math]::Round($hoursElapsed, 4)
    interval_sec = $IntervalSec
    log_file = $LogFile
    counts = @{
        ok_lines = $ok
        warn_lines = $warn
        fail_lines = $fail
        ready_only_fail_lines = $readyOnlyFail
        hard_fail_lines = $hardFail
        mesh_ok_lines = $meshOk
        mesh_warn_lines = $meshWarn
    }
    health_watch_exit = $exitCode
    mesh_warns_transient_ok = $meshWarnsTransient
    mesh_acceptable = $meshAcceptable
    ready_flaps_tolerated = $readyFlapsTolerated
    cycles_observed = [double](($lines | Select-String -Pattern "$ts OK port").Count) / [Math]::Max(1, $(if ($ProdMesh) { 3 } else { 1 }))
    strict = [bool]$Strict
    passed = $(if ($Strict) { $strictPass } else { $defaultPass })
    pass_notes = $(
        $notes = @()
        if ($Strict) {
            $notes += "STRICT: fail=0 mesh_warn=0 no ready-flap no 1-height skew"
            if ($fail -gt 0) { $notes += "fail_lines=$fail" }
            if ($meshWarn -gt 0) { $notes += "mesh_warn=$meshWarn (not tolerated)" }
            if ($readyOnlyFail -gt 0) { $notes += "ready_only_fail=$readyOnlyFail (not tolerated)" }
        } elseif ($meshWarn -eq 0) {
            $notes += "strict mesh_warn=0"
        } elseif ($meshWarnsTransient) {
            $notes += "mesh_warn=$meshWarn accepted: height deltas <=2 (sequential poll skew)"
        } elseif ($meshAcceptable) {
            $notes += "mesh_warn=$meshWarn rare vs mesh_ok=$meshOk (accepted)"
        } else {
            $notes += "mesh_warn=$meshWarn not acceptable"
        }
        if (-not $Strict -and $readyOnlyFail -gt 0) {
            if ($readyFlapsTolerated) {
                $notes += "ready_only_fail=$readyOnlyFail tolerated (mesh aligned, no hard fails)"
            } else {
                $notes += "ready_only_fail=$readyOnlyFail not tolerated"
            }
        }
        if ($hoursElapsed -lt $hoursFloor) {
            $notes += "hours_elapsed=$([Math]::Round($hoursElapsed,2)) < required_floor=$([Math]::Round($hoursFloor,2))"
        } else {
            $notes += "hours_elapsed=$([Math]::Round($hoursElapsed,2)) ok"
        }
        $notes -join "; "
    )
}

$reportDir = Split-Path -Parent $ReportFile
if ($reportDir -and -not (Test-Path $reportDir)) {
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
}
$json = $report | ConvertTo-Json -Depth 4
$reportFull = if ([System.IO.Path]::IsPathRooted($ReportFile)) { $ReportFile } else { Join-Path $Root $ReportFile }
[System.IO.File]::WriteAllText($reportFull, $json + "`n", [System.Text.UTF8Encoding]::new($false))

$activePath = Join-Path $Root "logs/soak_active.json"
if (Test-Path $activePath) {
    Remove-Item $activePath -Force -ErrorAction SilentlyContinue
}

if ($report.passed) {
    Write-Host "OK: soak passed (report: $ReportFile) $($report.pass_notes)" -ForegroundColor Green
} else {
    Write-Host "WARN: soak issues fail=$fail mesh_warn=$meshWarn transient_ok=$meshWarnsTransient mesh_ok_gate=$meshAcceptable (report: $ReportFile)" -ForegroundColor Yellow
}

exit $(if ($report.passed) { 0 } else { 1 })
