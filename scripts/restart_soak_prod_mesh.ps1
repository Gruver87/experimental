# Compatibility wrapper: Experimental 48h soak lives in start_soak_prod_mesh_48h.ps1.
# Does not reuse historical tip-v2 evidence log names.
param(
    [int]$Hours = 48,
    [int]$IntervalSec = 300,
    [string]$LogFile = "logs/soak_48h_experimental.log",
    [string]$ReportFile = "logs/soak_report_48h_experimental.json",
    [switch]$Foreground,
    [switch]$NoStopExisting,
    [switch]$SkipPreflight
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @(
    "-Hours", $Hours,
    "-IntervalSec", $IntervalSec,
    "-LogFile", $LogFile,
    "-ReportFile", $ReportFile
)
if ($Foreground) { $argsList += "-Foreground" }
if ($SkipPreflight) { $argsList += "-SkipPreflight" }
if ($NoStopExisting) {
    Write-Host "WARN: -NoStopExisting ignored; start_soak_prod_mesh_48h always stops leftover monitors" -ForegroundColor Yellow
}
& (Join-Path $ScriptDir "start_soak_prod_mesh_48h.ps1") @argsList
exit $LASTEXITCODE
