# Absolute Ops Console — start what's needed and open browser tabs.
#
# Default: Solo node on :8080 / :8545 (if not already up), then open console views.
#
# Usage:
#   .\scripts\open_ops_console.ps1
#   .\scripts\open_ops_console.ps1 -OpenOnly
#   .\scripts\open_ops_console.ps1 -BaseUrl http://127.0.0.1:18180
#   .\scripts\open_ops_console.ps1 -NoMarketJson
#   .\scripts\open_ops_console.ps1 -NoExplorer
#
# Honesty: local R&D demo — not soak / not mainnet.

param(
    [string]$BaseUrl = "",
    [switch]$OpenOnly,
    [switch]$NoBrowser,
    [switch]$NoMarketJson,
    [switch]$NoExplorer,
    [switch]$NoDocs,
    [int]$WaitSec = 120,
    [int]$HttpPort = 8080
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

function Write-Banner([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 64) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 64) -ForegroundColor Cyan
}

function Test-UrlReady([string]$Url, [int]$TimeoutSec = 4) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-Url([string]$Url, [int]$Seconds, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    Write-Host "Waiting for $Label ..." -ForegroundColor DarkGray
    while ((Get-Date) -lt $deadline) {
        if (Test-UrlReady -Url $Url) {
            Write-Host "  OK $Label" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Host "  TIMEOUT $Label" -ForegroundColor Red
    return $false
}

function Resolve-BaseUrl {
    if ($BaseUrl -and $BaseUrl.Trim()) {
        return $BaseUrl.Trim().TrimEnd("/")
    }
    foreach ($u in @(
            "http://127.0.0.1:$HttpPort",
            "http://127.0.0.1:18180",
            "http://127.0.0.1:18181",
            "http://127.0.0.1:18182"
        )) {
        if (Test-UrlReady -Url "$u/health/live") {
            return $u
        }
    }
    return "http://127.0.0.1:$HttpPort"
}

function Start-SoloIfNeeded([string]$TargetBase) {
    $live = "$TargetBase/health/live"
    $ready = "$TargetBase/health/ready"
    if (Test-UrlReady -Url $live) {
        Write-Host "Node already up: $TargetBase" -ForegroundColor Green
        return $true
    }
    if ($OpenOnly) {
        Write-Host "OpenOnly: nothing listening at $TargetBase" -ForegroundColor Yellow
        return $false
    }
    if ($TargetBase -notmatch ":$HttpPort`$") {
        Write-Host "Target $TargetBase is down and is not local :$HttpPort — not auto-starting." -ForegroundColor Yellow
        Write-Host "Start mesh/node yourself, then re-run with -OpenOnly -BaseUrl $TargetBase" -ForegroundColor DarkGray
        return $false
    }

    Write-Host "Starting solo node (python main.py) in a new window..." -ForegroundColor Cyan
    if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example" -ForegroundColor Yellow
    }
    if (-not (Test-Path "data")) {
        New-Item -ItemType Directory -Path "data" | Out-Null
    }

    $busy = $false
    foreach ($p in @($HttpPort, 8545)) {
        if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) {
            $busy = $true
            break
        }
    }
    if ($busy -and (Test-Path (Join-Path $ScriptDir "stop_node.ps1"))) {
        Write-Host "Ports busy — stopping previous solo node..." -ForegroundColor Yellow
        & (Join-Path $ScriptDir "stop_node.ps1")
        Start-Sleep -Seconds 2
    }

    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { throw "python not found on PATH" }

    $soloEnvPrefix = ""
    $depMode = $null
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^\s*DEPLOYMENT_MODE\s*=\s*(.+)\s*$') {
                $depMode = $Matches[1].Trim().Trim('"').Trim("'").ToLower()
            }
        }
    }
    if ($depMode -eq "prod") {
        $soloEnvPrefix = "`$env:TIP_SAFETY_ENFORCE='true'; "
    }

    $soloCmd = "Set-Location '$Root'; $soloEnvPrefix" +
        "Write-Host 'Absolute Blockchain - solo (ops console demo)' -ForegroundColor Cyan; python main.py"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-Command", $soloCmd) `
        -WorkingDirectory $Root

    if (-not (Wait-Url -Url $ready -Seconds $WaitSec -Label "solo $ready")) {
        Write-Host "Solo did not become ready. Check the node console window." -ForegroundColor Red
        return $false
    }
    return $true
}

function Open-Tabs([string]$Base, [string[]]$Paths) {
    if ($NoBrowser) {
        Write-Host "Browsers skipped (-NoBrowser). URLs:" -ForegroundColor DarkGray
        foreach ($p in $Paths) { Write-Host ("  " + $Base + $p) -ForegroundColor Gray }
        return
    }
    foreach ($p in $Paths) {
        $u = $Base + $p
        Write-Host "Open  $u" -ForegroundColor Gray
        Start-Process -FilePath $u
        Start-Sleep -Milliseconds 450
    }
}

Write-Banner "Ops Console demo launcher"
Write-Host "  NOT soak / NOT mainnet — local UI tour" -ForegroundColor DarkGray

$base = Resolve-BaseUrl
Write-Host "Base: $base" -ForegroundColor Cyan

if (-not (Start-SoloIfNeeded -TargetBase $base)) {
    exit 1
}

# Soft probes (do not fail the tour if optional feeds are down)
$marketOk = $false
try {
    $ms = Invoke-RestMethod -Uri "$base/market/snapshot" -TimeoutSec 20
    $marketOk = [bool]$ms.ok
    Write-Host ("Market snapshot: ok={0} crypto={1} fx={2} tickers={3}" -f `
            $ms.ok, `
            @($ms.crypto.items).Count, `
            @($ms.fx.items).Count, `
            @($ms.tickers.items).Count) -ForegroundColor $(if ($marketOk) { "Green" } else { "Yellow" })
} catch {
    Write-Host "Market snapshot not ready yet (UI still opens): $($_.Exception.Message)" -ForegroundColor Yellow
}

$paths = @(
    "/#overview",
    "/#markets",
    "/#wallets",
    "/#council",
    "/#metrics",
    "/#mesh",
    "/#mempool",
    "/#security"
)
if (-not $NoExplorer) { $paths += "/explorer" }
if (-not $NoDocs) { $paths += "/docs" }
if (-not $NoMarketJson) { $paths += "/market/snapshot" }
$paths += "/status?probe=1"
$paths += "/health/ready"

Open-Tabs -Base $base -Paths $paths

Write-Host ""
Write-Host "RESULT: browser tabs launched" -ForegroundColor Green
Write-Host "  Console   $base/" -ForegroundColor Gray
Write-Host "  Markets   $base/#markets" -ForegroundColor Gray
Write-Host "  Explorer  $base/explorer" -ForegroundColor Gray
Write-Host "  Stop solo: .\scripts\stop_node.ps1" -ForegroundColor Gray
Write-Host "  Reopen:    .\scripts\open_ops_console.ps1 -OpenOnly" -ForegroundColor Gray
exit 0
