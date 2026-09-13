# Start 2-node distributed shard devnet (shard 0 + shard 1, separate DBs).
# Lab-only Profile E helper. Does NOT arm prod 778888 feature_sharding.
param(
    [switch]$Fresh
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:ABS_REQUIRE_NATIVE_CRYPTO = "true"

# Pin lab env for child node processes only — restore after spawn so this
# session cannot poison industrial_gate / verify_pre_soak (FEATURE_SHARDING).
$prevEnv = @{
    DEPLOYMENT_MODE     = $env:DEPLOYMENT_MODE
    FEATURE_SHARDING    = $env:FEATURE_SHARDING
    FEATURE_ORACLES     = $env:FEATURE_ORACLES
    FEATURE_LONG_RANGE  = $env:FEATURE_LONG_RANGE
    BRIDGE_ENABLED      = $env:BRIDGE_ENABLED
}
function Restore-LabEnvPin {
    foreach ($k in $prevEnv.Keys) {
        $v = $prevEnv[$k]
        if ($null -eq $v -or $v -eq "") {
            Remove-Item "Env:$k" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$k" -Value $v
        }
    }
}

# Leftover DEPLOYMENT_MODE=prod overrides node.shard*.json (dev), forces
# require_wallet_file, and hard-offs FEATURE_SHARDING — nodes die before HTTP.
$env:DEPLOYMENT_MODE = "dev"
$env:FEATURE_SHARDING = "true"
$env:FEATURE_ORACLES = "false"
$env:FEATURE_LONG_RANGE = "false"
$env:BRIDGE_ENABLED = "false"

Write-Host "Lab env pin: DEPLOYMENT_MODE=dev FEATURE_SHARDING=true (restored after spawn)" -ForegroundColor DarkGray

try {
& (Join-Path $ProjectRoot "scripts\stop_node.ps1") 2>$null | Out-Null

if ($Fresh) {
    foreach ($f in @("data\shard0.db", "data\shard1.db", "data\shard0.log", "data\shard1.log")) {
        if (Test-Path $f) { Remove-Item $f -Force }
    }
}

$log0 = Join-Path $ProjectRoot "data\shard0.boot.err.log"
$log1 = Join-Path $ProjectRoot "data\shard1.boot.err.log"

Write-Host "Starting shard-0 (assigned_shard_id=0)..." -ForegroundColor Cyan
Start-Process python -ArgumentList @("main.py", "--config", "node.shard0.json") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardError $log0 `
    -WindowStyle Hidden

Start-Sleep -Seconds 5

Write-Host "Starting shard-1 (assigned_shard_id=1)..." -ForegroundColor Cyan
Start-Process python -ArgumentList @("main.py", "--config", "node.shard1.json") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardError $log1 `
    -WindowStyle Hidden
} finally {
    Restore-LabEnvPin
}

Start-Sleep -Seconds 8

$ready = 0
foreach ($pair in @(
    @{ Url = "http://127.0.0.1:8080/sharding/stats"; Name = "shard-0"; Log = $log0 },
    @{ Url = "http://127.0.0.1:8081/sharding/stats"; Name = "shard-1"; Log = $log1 }
)) {
    try {
        $st = Invoke-RestMethod -Uri $pair.Url -TimeoutSec 5
        Write-Host "$($pair.Name): mode=$($st.mode) assigned=$($st.assigned_shard_id) shards=$($st.total_shards)" -ForegroundColor Green
        $ready++
    }
    catch {
        Write-Host "$($pair.Name): not ready ($($_.Exception.Message))" -ForegroundColor Red
        if (Test-Path $pair.Log) {
            Write-Host "  boot stderr ($($pair.Log)):" -ForegroundColor DarkGray
            Get-Content $pair.Log -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "    $_" -ForegroundColor DarkGray
            }
        }
    }
}

Write-Host ""
Write-Host "Shard devnet:" -ForegroundColor Cyan
Write-Host "  shard-0  http://127.0.0.1:8080  P2P :5000  DB data/shard0.db"
Write-Host "  shard-1  http://127.0.0.1:8081  P2P :5001  DB data/shard1.db"
Write-Host "Stop: .\scripts\stop_node.ps1"

if ($ready -lt 2) {
    Write-Host "RESULT: FAIL shard devnet ($ready/2 ready). Check DEPLOYMENT_MODE and data/shard*.boot.err.log" -ForegroundColor Red
    exit 1
}

Write-Host "RESULT: PASS shard devnet (2/2 ready)" -ForegroundColor Green
exit 0
