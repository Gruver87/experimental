# Harsh 5h prod-mesh soak (not 48h). FAIL on 1-height skew, head mismatch,
# ready-flap, or harness fail. Default 48h scoring is unchanged.
param(
    [int]$Hours = 5,
    [int]$IntervalSec = 60,
    [string]$LogFile = "logs/soak_5h_strict.log",
    [string]$ReportFile = "logs/soak_report_5h_strict.json",
    [switch]$Foreground,
    [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

Write-Host "STRICT 5h prod mesh soak (not a 48h claim)" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s full-harness every cycle" -ForegroundColor DarkGray
Write-Host "  fail closed: mesh_warn=0, fail=0, no 1-height skew, no ready-flap" -ForegroundColor DarkGray
Write-Host "  log=$LogFile report=$ReportFile" -ForegroundColor DarkGray

if (-not $SkipPreflight) {
    python scripts/soak_preflight.py --hours $Hours --interval-sec $IntervalSec --require-p2p-tls
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: soak preflight (mesh not aligned / TLS). Fix mesh, then re-run." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    & (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: probe_prod_mesh -Quick. Do not start soak on a split tip." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$gitTag = "unknown"
try {
    $desc = git describe --tags --abbrev=0 2>$null
    if ($desc) { $gitTag = $desc.Trim() }
} catch { }

$activeMeta = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    strict = $true
    started_at = (Get-Date -Format "o")
    git_tag = $gitTag
    note = "5h STRICT soak - not 48h evidence"
}
$activePath = Join-Path $Root "logs/soak_active.json"
$activeMeta | ConvertTo-Json | Set-Content -Path $activePath -Encoding UTF8

python scripts/record_evidence_run.py `
    --name soak_monitor_5h_strict `
    --result IN_PROGRESS `
    --command ".\scripts\start_soak_prod_mesh_5h_strict.ps1" `
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

# Do NOT RedirectStandardOutput: that forces UseShellExecute=false and the
# child stays in the Cursor/CI job. When the parent shell exits, Windows
# kills the soak (~minutes), which is not a mesh FAIL.
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

Write-Host "OK: STRICT 5h soak started in background PID=$($created.ProcessId) (not 48h)" -ForegroundColor Green
Write-Host "  check:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  status: .\scripts\soak_status.ps1" -ForegroundColor DarkGray
Write-Host "  tail:   Get-Content $LogFile -Wait -Tail 30" -ForegroundColor DarkGray
Write-Host "  stop:   .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
Write-Host "  report after 5h: $ReportFile (passed=true only if fail=0 and mesh_warn=0)" -ForegroundColor DarkGray
exit 0
