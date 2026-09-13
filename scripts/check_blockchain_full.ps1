# Full blockchain verification for Absolute Blockchain Ultimate.
#
# Fast full local gate:
#   .\scripts\check_blockchain_full.ps1
#
# Include Rust bridge rebuild if the binary is missing:
#   .\scripts\check_blockchain_full.ps1 -BuildRust
#
# Check a running local node:
#   python main.py
#   .\scripts\check_blockchain_full.ps1 -Live
#
# Check a running multi-node/devnet topology:
#   .\scripts\check_blockchain_full.ps1 -Live -P2P
#
# Validate Docker Compose files:
#   .\scripts\check_blockchain_full.ps1 -Docker
#
# Heavy Docker image build check:
#   .\scripts\check_blockchain_full.ps1 -Docker -DockerBuild
#
# If Windows closes a local test socket once, the full audit is retried once by default.

param(
    [switch]$Live,
    [switch]$P2P,
    [switch]$Docker,
    [switch]$DockerBuild,
    [switch]$BuildRust,
    [switch]$NoClean,
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [int]$PytestTimeout = 900,
    [int]$P2PWait = 300,
    [int]$AuditRetries = 1
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

function Run-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-RustBridgeBinary {
    $candidates = @(
        (Join-Path $ProjectRoot "bridge\abs_bridge_bin.exe"),
        (Join-Path $ProjectRoot "bridge\abs_bridge_bin")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Invoke-JsonEndpoint {
    param(
        [string]$Path,
        [int]$TimeoutSec = 10
    )
    $url = "$BaseUrl$Path"
    Write-Host "GET $url"
    Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec $TimeoutSec | Out-Null
}

function Clear-PythonGeneratedFiles {
    Write-Host "Removing Python cache files..." -ForegroundColor DarkGray
    Get-ChildItem -Path $ProjectRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $ProjectRoot -File -Recurse -Force -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Invoke-FullAuditWithRetry {
    $attempt = 0
    while ($true) {
        $attempt += 1
        Write-Host "Full audit attempt $attempt/$($AuditRetries + 1)" -ForegroundColor Gray
        $global:LASTEXITCODE = 0
        python scripts/full_audit.py --pytest-timeout $PytestTimeout
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -gt $AuditRetries) {
            exit $LASTEXITCODE
        }
        Write-Host "Full audit failed once; cleaning caches and retrying..." -ForegroundColor Yellow
        Clear-PythonGeneratedFiles
        Start-Sleep -Seconds 2
    }
}

Write-Host "Absolute Blockchain Ultimate - FULL BLOCKCHAIN CHECK" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
Write-Host "BaseUrl: $BaseUrl"

Require-Command python

Run-Step "Python version" {
    python --version
}

Run-Step "Secrets scan" {
    python scripts/check_secrets.py
}

Run-Step "Static production gate" {
    python scripts/prod_gate.py
}

Run-Step "Rust bridge binary" {
    $bin = Get-RustBridgeBinary
    if ($BuildRust -or -not $bin) {
        Require-Command cargo
        Write-Host "Building Rust bridge..."
        & (Join-Path $ProjectRoot "scripts\build_bridge.ps1")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $bin = Get-RustBridgeBinary
    }
    if (-not $bin) {
        throw "Rust bridge binary missing. Run: .\scripts\check_blockchain_full.ps1 -BuildRust"
    }
    Write-Host "Rust bridge binary: $bin"
    $payload = '{"command":"status","args":{}}'
    $out = $payload | & $bin
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $json = $out | ConvertFrom-Json
    if ($json.status -ne "ready") {
        throw "Rust bridge status is not ready: $out"
    }
    Write-Host "Rust bridge status: $($json.status) source=$($json.source)"
}

if (-not $NoClean) {
    Run-Step "Clean generated Python cache" {
        Clear-PythonGeneratedFiles
    }
}

Run-Step "Full audit and pytest" {
    Invoke-FullAuditWithRetry
}

if ($Live) {
    Run-Step "Live node endpoints" {
        Invoke-JsonEndpoint "/health/live"
        Invoke-JsonEndpoint "/status"
        Invoke-JsonEndpoint "/sync/status"
        Invoke-JsonEndpoint "/features"
        Invoke-JsonEndpoint "/bridge"
        Invoke-JsonEndpoint "/tokenomics"
        Invoke-JsonEndpoint "/chain/state-root/status"
    }

    $liveArgs = @("scripts/full_audit.py", "--live", "--no-tests", "--base-url", $BaseUrl)
    if ($P2P) {
        $liveArgs += "--p2p"
    }
    Run-Step "Live audit" {
        python @liveArgs
    }
}
elseif ($P2P) {
    Run-Step "P2P auto verification" {
        python scripts/verify_p2p_ci.py --mode auto --wait $P2PWait
    }
}

if ($Docker) {
    Require-Command docker

    Run-Step "Docker devnet compose config" {
        docker compose -f docker-compose.devnet.yml config --quiet
    }

    Run-Step "Docker devnet rust compose config" {
        docker compose -f docker-compose.devnet-rust.yml config --quiet
    }

    Run-Step "Docker 3-node devnet compose config" {
        docker compose -f docker-compose.devnet-3node.yml config --quiet
    }

    Run-Step "Docker 5-validator devnet compose config" {
        docker compose -f docker-compose.devnet-5validator.yml config --quiet
    }

    $oldJwt = $env:JWT_SECRET
    $oldRpc = $env:RPC_API_KEYS
    $oldOracle = $env:BRIDGE_ORACLE_SECRET
    $oldCors = $env:CORS_ORIGINS
    $oldEthRpc = $env:ETH_RPC_URL
    try {
        $placeholder = "composeconfigplaceholder-min-32-bytes!!"
        if (-not $env:JWT_SECRET) { $env:JWT_SECRET = $placeholder }
        if (-not $env:RPC_API_KEYS) { $env:RPC_API_KEYS = $placeholder }
        if (-not $env:BRIDGE_ORACLE_SECRET) { $env:BRIDGE_ORACLE_SECRET = $placeholder }
        if (-not $env:CORS_ORIGINS) { $env:CORS_ORIGINS = "https://explorer.example.com" }
        if (-not $env:ETH_RPC_URL) { $env:ETH_RPC_URL = "https://rpc.example.com" }

        Run-Step "Docker production compose config" {
            docker compose -f docker-compose.prod.yml config --quiet
        }
    }
    finally {
        $env:JWT_SECRET = $oldJwt
        $env:RPC_API_KEYS = $oldRpc
        $env:BRIDGE_ORACLE_SECRET = $oldOracle
        $env:CORS_ORIGINS = $oldCors
        $env:ETH_RPC_URL = $oldEthRpc
    }

    if ($DockerBuild) {
        Run-Step "Docker image build" {
            docker compose -f docker-compose.devnet.yml build
        }
    }
}

Write-Host "`nRESULT: PASS static/full-check (NOT mesh probe / NOT soak)" -ForegroundColor Green
Write-Host "  Reports:"
Write-Host "  data/full_audit_report.json"
Write-Host "  data/final_audit_report.json"
Write-Host "  Live mesh: .\scripts\probe_prod_mesh.ps1 -Quick" -ForegroundColor DarkGray
