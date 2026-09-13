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

# Pin lab env: a leftover DEPLOYMENT_MODE=prod from setup_prod_env / .env overrides
# node.shard*.json (deployment_mode=dev), forces require_wallet_file, and hard-offs
# FEATURE_SHARDING — nodes then die before HTTP is up ("not ready yet").
$env:DEPLOYMENT_MODE = "dev"
$env:FEATURE_SHARDING = "true"
$env:FEATURE_ORACLES = "false"
$env:FEATURE_LONG_RANGE = "false"
$env:BRIDGE_ENABLED = "false"

Write-Host "Lab env pin: DEPLOYMENT_MODE=dev FEATURE_SHARDING=true (prod shell leftovers ignored)" -ForegroundColor DarkGray

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
