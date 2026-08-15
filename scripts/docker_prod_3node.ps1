# Three-node production mesh (ceremony manifest + per-validator wallets)
param(
    [string]$CeremonyDir = "data/ceremony_keys",
    [switch]$NoCloneDb,
    [switch]$SkipBuild,
    [switch]$KeepVolumes,
    [switch]$PullLatest,
    [switch]$RecoveryDrill,
    # P2P TLS is ON by default for prod mesh. Use -NoP2pTls only for local plaintext labs.
    [switch]$P2pTls,
    [switch]$NoP2pTls,
    [string]$ProdImage = "ghcr.io/gruver87/abs-blockchain-node:latest"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot
. "$ScriptDir\ceremony_env.ps1"

function Import-DotEnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $val = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
    return $true
}

function Test-PlaceholderEthRpc {
    param([string]$Url)
    $result = python -c "import sys; from bridge.l1_rpc import is_placeholder_l1_rpc_url; print('1' if is_placeholder_l1_rpc_url(sys.argv[1]) else '0')" $Url 2>$null
    return ($result -eq "1")
}

$dotEnv = Join-Path (Get-Location) ".env"
if (Import-DotEnvFile $dotEnv) {
    Write-Host "Loaded $dotEnv" -ForegroundColor DarkGray
}

if ([string]::IsNullOrWhiteSpace($CeremonyDir)) {
    $CeremonyDir = "data\ceremony_keys"
}
# Prefer backslash path + --flag=value so native python argv cannot eat the path.
$CeremonyDirPath = ($CeremonyDir -replace "/", "\")
python scripts/deploy_ceremony_prod.py --ceremony-dir=$CeremonyDirPath --mesh
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$metaPath = Join-Path (Get-Location) "data\ceremony_deploy.json"
$meta = Get-Content $metaPath -Raw | ConvertFrom-Json
$env:VALIDATORS_MANIFEST_PATH = "data/validators.manifest.json"
$env:GENESIS_CEREMONY_HASH = $meta.ceremony_hash
Sync-CeremonyDeployEnv -ProjectRoot $ProjectRoot -CeremonyHash $meta.ceremony_hash
$env:BRIDGE_ENABLED = "false"
$env:BRIDGE_PROBE_L1_RPC = "false"

$missing = @()
foreach ($name in @("JWT_SECRET", "RPC_API_KEYS", "BRIDGE_ORACLE_SECRET", "CORS_ORIGINS", "ETH_RPC_URL")) {
    if (-not [Environment]::GetEnvironmentVariable($name)) { $missing += $name }
}
if ($missing.Count -gt 0) {
    Write-Host "Missing required prod env vars: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "  .\scripts\setup_prod_env.ps1 -EthRpcUrl `"https://your-real-ethereum-rpc`"" -ForegroundColor Cyan
    exit 1
}

$ethRpc = [Environment]::GetEnvironmentVariable("ETH_RPC_URL")
if (Test-PlaceholderEthRpc $ethRpc) {
    Write-Host "WARN: ETH_RPC_URL is a placeholder; OK while BRIDGE_PROBE_L1_RPC=false." -ForegroundColor Yellow
}

foreach ($wallet in @(
    "data\prod_mesh\wallets\validator-1.wallet.json",
    "data\prod_mesh\wallets\validator-2.wallet.json",
    "data\prod_mesh\wallets\validator-3.wallet.json",
    "data\validators.manifest.json"
)) {
    if (-not (Test-Path $wallet)) {
        Write-Host "FAIL: missing $wallet (run deploy with --mesh)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Running production gate..." -ForegroundColor Cyan
python scripts/prod_gate.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$composeFile = "docker-compose.prod.3node.yml"
$composeTlsFile = "docker-compose.prod.3node.p2ptls.yml"
$ComposeProject = "abs-prod-mesh3"
$composeArgs = @("-p", $ComposeProject, "-f", $composeFile)

# Default: P2P TLS + mTLS overlay. Opt out with -NoP2pTls.
$enableP2pTls = -not $NoP2pTls
if ($P2pTls) { $enableP2pTls = $true }

if ($enableP2pTls) {
    $tlsRoot = Join-Path (Get-Location) "data\p2p_tls_prod_mesh\node1\node.pem"
    if (-not (Test-Path $tlsRoot)) {
        Write-Host "Generating prod mesh P2P TLS material..." -ForegroundColor Cyan
        python scripts/gen_p2p_mesh_tls.py
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if (-not (Test-Path $composeTlsFile)) {
        Write-Host "FAIL: missing $composeTlsFile" -ForegroundColor Red
        exit 1
    }
    $composeArgs += @("-f", $composeTlsFile)
    $env:P2P_TLS_REQUIRE_CLIENT_CERT = "true"
    Write-Host "P2P wire TLS+mTLS enabled (overlay $composeTlsFile)" -ForegroundColor Cyan
} else {
    Write-Host "WARN: P2P TLS disabled (-NoP2pTls) - plaintext mesh for lab only" -ForegroundColor Yellow
}

function Invoke-MeshCompose {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$ComposeCommand
    )
    # Docker writes progress to stderr. With $ErrorActionPreference=Stop (e.g. from
    # start_all.ps1) PowerShell turns that into a terminating NativeCommandError.
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $oldNative = $null
    if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
        $oldNative = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        & docker compose @composeArgs @ComposeCommand
    } finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $oldNative) {
            $PSNativeCommandUseErrorActionPreference = $oldNative
        }
    }
}
$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_DOCKER_CLI_BUILD = "1"

if ($PullLatest) {
    Write-Host "PullLatest: pulling $ProdImage" -ForegroundColor Cyan
    docker pull $ProdImage
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: could not pull $ProdImage" -ForegroundColor Red
        Write-Host "  Image is published after CI workflow 'Docker prod image' succeeds on master." -ForegroundColor Yellow
        Write-Host "  Check: https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid/actions" -ForegroundColor Yellow
        Write-Host "  Or build locally: .\scripts\docker_prod_3node.ps1" -ForegroundColor Yellow
        exit 1
    }
    $env:ABS_PROD_IMAGE = $ProdImage
    $SkipBuild = $true
}

if ($NoCloneDb) {
    $env:SKIP_DB_SEED = "1"
} else {
    Remove-Item Env:SKIP_DB_SEED -ErrorAction SilentlyContinue
}

if ($KeepVolumes -and -not $NoCloneDb) {
    Write-Host "KeepVolumes: skipping DB seed (preserved RocksDB volumes)" -ForegroundColor Yellow
    $NoCloneDb = $true
    $env:SKIP_DB_SEED = "1"
}

Write-Host "Recreating prod 3-node mesh (18180/18181/18182)..." -ForegroundColor Cyan
if ($SkipBuild) {
    Write-Host "SkipBuild: using existing Docker image (no compose build)" -ForegroundColor Yellow
}
if ($KeepVolumes) {
    Write-Host "KeepVolumes: docker down without -v (RocksDB data preserved)" -ForegroundColor Yellow
}

if ($KeepVolumes) {
    Invoke-MeshCompose -- down --remove-orphans
} else {
    # Use --volumes (not -v): PowerShell would steal -v as a function parameter.
    Invoke-MeshCompose -- down --volumes --remove-orphans
}
if (-not $SkipBuild) {
    # One image is shared by node1/node2/node3. Parallel `build node1 node2 node3`
    # races on the same tag (Bake: image already exists).
    Invoke-MeshCompose build node1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($NoCloneDb) {
    Write-Host "Starting 3-node mesh (no DB seed)..." -ForegroundColor Gray
    # Use --detach (not -d): PowerShell steals -d from ValueFromRemainingArguments.
    Invoke-MeshCompose up --detach --force-recreate node1 node2 node3
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Invoke-MeshCompose up --detach --force-recreate node1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Solo node1 cannot pass /health/ready (peers_alive / quorum_height need the mesh).
    # Wait for /health/live before RocksDB seed, then bring peers up together.
    Write-Host "Waiting for node1 /health/live (solo pre-seed)..." -ForegroundColor Gray
    $deadline = (Get-Date).AddMinutes(3)
    $ready1 = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:18180/health/live" -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -eq 200) { $ready1 = $true; break }
        } catch { Start-Sleep -Seconds 5 }
    }
    if (-not $ready1) {
        Write-Host "FAIL: node1 /health/live not ready for seed" -ForegroundColor Red
        Invoke-MeshCompose logs node1 --tail 40
        exit 1
    }

    try {
        $preSeed = Invoke-RestMethod -Uri "http://127.0.0.1:18180/status" -TimeoutSec 5
        $preH = [int]($preSeed.height)
        if ($preH -gt 1) {
            Write-Host "FAIL: node1 height=$preH before seed (expected at most 1). Mining ran before mesh peers." -ForegroundColor Red
            exit 1
        }
        Write-Host "OK: node1 height=$preH before seed" -ForegroundColor DarkGray
    } catch {
        Write-Host "WARN: could not read node1 height before seed" -ForegroundColor Yellow
    }
    Write-Host "Stopping node1 for consistent RocksDB seed..." -ForegroundColor Gray
    Invoke-MeshCompose stop node1 | Out-Null
    Invoke-MeshCompose --profile seed run --rm node2-db-seed
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-MeshCompose --profile seed run --rm node3-db-seed
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Starting 3-node mesh together (avoid solo mining before followers)..." -ForegroundColor Gray
    Invoke-MeshCompose up --detach --force-recreate node1 node2 node3
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Waiting for node1 HTTP..." -ForegroundColor Gray
$deadline = (Get-Date).AddMinutes(3)
$ready1 = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:18180/health/ready" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $ready1 = $true; break }
    } catch { Start-Sleep -Seconds 3 }
}
if (-not $ready1) {
    Invoke-MeshCompose logs node1 --tail 40
    exit 1
}

Write-Host "Waiting for node2/node3 HTTP..." -ForegroundColor Gray
$portToService = @{ 18181 = "node2"; 18182 = "node3" }
foreach ($port in @(18181, 18182)) {
    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health/ready" -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if (-not $ready) {
        $svc = $portToService[$port]
        Write-Host "FAIL: mesh node not reachable on port $port (/health/ready)" -ForegroundColor Red
        Invoke-MeshCompose ps -a
        Invoke-MeshCompose logs $svc --tail 60
        exit 1
    }
}

Write-Host "Waiting for 3-node mesh sync..." -ForegroundColor Cyan
python scripts/verify_p2p_ci.py --mode prod-mesh3-live --url1 http://127.0.0.1:18180 --url2 http://127.0.0.1:18181 --url3 http://127.0.0.1:18182 --wait 360
if ($LASTEXITCODE -ne 0) {
    Invoke-MeshCompose logs node1 --tail 20
    Invoke-MeshCompose logs node2 --tail 20
    Invoke-MeshCompose logs node3 --tail 20
    exit $LASTEXITCODE
}

python scripts/prod_smoke.py http://127.0.0.1:18180
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($enableP2pTls) {
    Write-Host "Verifying P2P wire TLS on mesh nodes..." -ForegroundColor Cyan
    foreach ($port in @(18180, 18181, 18182)) {
        try {
            $sec = Invoke-RestMethod -Uri "http://127.0.0.1:$port/p2p/security" -TimeoutSec 12
            $tls = $sec.tls
            if (-not $tls.enabled -or -not $tls.ready) {
                Write-Host "FAIL: P2P TLS not ready on :$port (enabled=$($tls.enabled) ready=$($tls.ready))" -ForegroundColor Red
                if ($tls.errors) { Write-Host "  errors: $($tls.errors -join '; ')" -ForegroundColor Red }
                exit 1
            }
            Write-Host "  OK :$port P2P TLS ready" -ForegroundColor DarkGray
        } catch {
            Write-Host "FAIL: could not read /p2p/security on :$port - $_" -ForegroundColor Red
            exit 1
        }
    }
}

if ($RecoveryDrill) {
    Write-Host "Running prod mesh failover recovery drill..." -ForegroundColor Cyan
    python scripts/verify_p2p_ci.py --mode prod-mesh3-recovery `
        --url1 http://127.0.0.1:18180 `
        --url2 http://127.0.0.1:18181 `
        --url3 http://127.0.0.1:18182 `
        --wait 360
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "OK: prod 3-node mesh" -ForegroundColor Green
if ($enableP2pTls) {
    Write-Host "  P2P wire TLS+mTLS: enabled on all nodes" -ForegroundColor Gray
} else {
    Write-Host "  P2P wire TLS: disabled (-NoP2pTls)" -ForegroundColor Yellow
}
Write-Host "  node1 http://127.0.0.1:18180" -ForegroundColor Gray
Write-Host "  node2 http://127.0.0.1:18181" -ForegroundColor Gray
Write-Host "  node3 http://127.0.0.1:18182" -ForegroundColor Gray
