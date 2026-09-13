# Global Experimental R&D audit - one operator entry for "full project" check.
#
# Covers the ADR 0021 + mesh + EVM path we landed. Does NOT start 48h soak.
# Does NOT claim mainnet / Hybrid pin / soak PASS.
#
# Usage (repo root):
#   .\scripts\verify_global_rd_audit.ps1
#   .\scripts\verify_global_rd_audit.ps1 -Mode Host
#   .\scripts\verify_global_rd_audit.ps1 -Mode Live
#   .\scripts\verify_global_rd_audit.ps1 -Mode FullLaunch
#   .\scripts\verify_global_rd_audit.ps1 -Mode FullLaunch -Rebuild
#
# Modes:
#   Host        offline only (native status, ADR0021, industrial_gate, units)
#   Live        Host + running mesh (probe, demote-in-image, EVM smoke, load, prepare)
#   FullLaunch  bring up 3-node mesh then Live (default -SkipBuild; -Rebuild forces image bake)
#
# Report: logs\verify_global_rd_audit.json

param(
    [ValidateSet("Host", "Live", "FullLaunch")]
    [string]$Mode = "Live",
    [switch]$Rebuild,
    [switch]$SkipPrepare,
    [switch]$SkipEvm,
    [switch]$Help
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

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
            Set-Item -Path ("env:" + $key) -Value $val
        }
    }
    return $true
}

if ($Help) {
    Write-Host ""
    Write-Host "verify_global_rd_audit.ps1 - global Experimental self-check"
    Write-Host ""
    Write-Host "  Host        offline gates + ADR 0021"
    Write-Host "  Live        Host + live prod mesh :18180-18182 (default)"
    Write-Host "  FullLaunch  docker_prod_3node then Live"
    Write-Host ""
    Write-Host "  -Rebuild       FullLaunch rebuilds image (no -SkipBuild)"
    Write-Host "  -SkipPrepare   skip prepare_48h_soak"
    Write-Host "  -SkipEvm       skip prod_evm_smoke + load harness"
    Write-Host ""
    Write-Host "  Does NOT start soak. PASS != mainnet."
    Write-Host "  Report: logs\verify_global_rd_audit.json"
    Write-Host ""
    exit 0
}

$started = Get-Date
$steps = New-Object System.Collections.Generic.List[object]
$fail = 0

function Write-Step([string]$Name) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Cyan
    Write-Host ("  " + $Name) -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor Cyan
}

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Command,
        [switch]$Soft
    )
    Write-Host ""
    Write-Host (">>> " + $Name) -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $Command
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }
    $ok = ($rc -eq 0)
    $entry = @{
        name = $Name
        ok = $ok
        exit_code = $rc
        soft = [bool]$Soft
    }
    [void]$steps.Add($entry)
    if ($ok) {
        Write-Host ("OK: " + $Name) -ForegroundColor Green
    } else {
        if ($Soft) {
            Write-Host ("WARN: " + $Name + " (soft, exit " + $rc + ")") -ForegroundColor Yellow
        } else {
            Write-Host ("FAIL: " + $Name + " (exit " + $rc + ")") -ForegroundColor Red
            $script:fail++
        }
    }
}

Write-Host ""
Write-Host "GLOBAL R&D AUDIT (Experimental)" -ForegroundColor Cyan
Write-Host ("  mode=" + $Mode + " rebuild=" + [bool]$Rebuild) -ForegroundColor DarkGray
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid audit pin" -ForegroundColor DarkGray
Write-Host ("  started " + $started.ToString("o")) -ForegroundColor DarkGray

$dotEnv = Join-Path $Root ".env"
if (Import-DotEnvFile $dotEnv) {
    Write-Host ("  loaded .env (RPC_API_KEYS set=" + (-not [string]::IsNullOrWhiteSpace($env:RPC_API_KEYS)) + ")") -ForegroundColor DarkGray
} else {
    Write-Host "  WARN: .env missing - EVM smoke may fail without RPC_API_KEYS" -ForegroundColor Yellow
}

# ----- Host path -----
Write-Step "A) HOST - native + ADR 0021 + gates"

Invoke-Check "native_crypto_status" {
    python -c "from crypto.native import native_crypto_status, native_capabilities_status; s=native_crypto_status(required=False); c=native_capabilities_status(); print('crypto', s); fam=c.get('families') or {}; print('mempool_kernel', fam.get('mempool_kernel')); print('mempool_store', fam.get('mempool_store')); assert fam.get('mempool_kernel',{}).get('backend')=='rust'; assert fam.get('mempool_store',{}).get('backend')=='rust'"
}

Invoke-Check "verify_adr0021_require_rust" {
    python scripts/verify_adr0021_phase1.py --require-rust --skip-mesh
}

Invoke-Check "demote_source_present" {
    python -c "from pathlib import Path; t=Path('blockchain/mempool.py').read_text(encoding='utf-8'); assert '_demote_store' in t; assert 'insert:' in t; print('demote_ok')"
}

Invoke-Check "pytest_adr0021_mempool" {
    python -m pytest -q tests/unit/test_adr0021_phase1_fixtures.py tests/unit/test_adr0021_phase2_store.py tests/unit/test_mempool_port.py --tb=line
}

Invoke-Check "industrial_gate" {
    python scripts/industrial_gate.py
}

Invoke-Check "prod_gate" {
    python scripts/prod_gate.py
}

if ($Mode -eq "Host") {
    Write-Host ""
    Write-Host "Host-only mode: skipping mesh / EVM / prepare" -ForegroundColor Yellow
} else {
    if ($Mode -eq "FullLaunch") {
        Write-Step "B) FULL LAUNCH - docker prod 3-node"
        if ($Rebuild) {
            Invoke-Check "docker_prod_3node_rebuild" {
                & (Join-Path $Root "scripts\docker_prod_3node.ps1") -KeepVolumes
            }
        } else {
            Invoke-Check "docker_prod_3node_skipbuild" {
                & (Join-Path $Root "scripts\docker_prod_3node.ps1") -SkipBuild -KeepVolumes
            }
        }
    }

    Write-Step "C) LIVE MESH - probe + bake honesty"

    Invoke-Check "http_live_18180_182" {
        python -c "import urllib.request; ports=(18180,18181,18182); [urllib.request.urlopen('http://127.0.0.1:%d/health/live' % p, timeout=8).read() for p in ports]; print('live_ok', ports)"
    }

    Invoke-Check "container_demote_and_store" {
        docker exec abs-prod-mesh3-node1-1 python -c "import inspect; from blockchain.mempool import Mempool; s=inspect.getsource(Mempool._demote_store); assert 'demote rust store' in s; st=Mempool(4,0.0).get_stats(); print('store_backend=', st.get('store_backend')); assert st.get('store_backend') in ('rust','python'); print('demote_ok=True')"
    }

    Invoke-Check "probe_prod_mesh_quick" {
        & (Join-Path $Root "scripts\probe_prod_mesh.ps1") -Quick
    }

    if (-not $SkipEvm) {
        Write-Step "D) EVM + mempool load"

        if ([string]::IsNullOrWhiteSpace($env:RPC_API_KEYS)) {
            Write-Host "FAIL: RPC_API_KEYS empty after .env load - cannot run prod_evm_smoke" -ForegroundColor Red
            Invoke-Check "prod_evm_smoke" { $global:LASTEXITCODE = 1 }
        } else {
            Invoke-Check "prod_evm_smoke" {
                $logDir = Join-Path $Root "logs"
                if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
                $outLog = Join-Path $logDir "prod_evm_smoke_audit.out.log"
                $errLog = Join-Path $logDir "prod_evm_smoke_audit.err.log"
                $rc = 1
                for ($i = 1; $i -le 3; $i++) {
                    Write-Host ("  prod_evm_smoke attempt {0}/3" -f $i) -ForegroundColor DarkGray
                    if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
                    if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }
                    # Inherit process env (RPC_API_KEYS from .env). Do not use -UseNewEnvironment.
                    $p = Start-Process -FilePath "python" `
                        -ArgumentList @("scripts/prod_evm_smoke.py") `
                        -WorkingDirectory $Root `
                        -Wait -PassThru -NoNewWindow `
                        -RedirectStandardOutput $outLog `
                        -RedirectStandardError $errLog
                    $rc = $p.ExitCode
                    if ($null -eq $rc) { $rc = 1 }
                    if (Test-Path $outLog) { Get-Content $outLog | Write-Host }
                    if ((Test-Path $errLog) -and ((Get-Item $errLog).Length -gt 0)) {
                        Write-Host "--- stderr ---" -ForegroundColor DarkYellow
                        Get-Content $errLog | Write-Host
                    }
                    if ($rc -eq 0) { break }
                    Write-Host ("  attempt {0} exit={1}; retry after mesh settle" -f $i, $rc) -ForegroundColor Yellow
                    Start-Sleep -Seconds 8
                }
                $global:LASTEXITCODE = $rc
            }
        }

        Invoke-Check "evm_mempool_load_harness" {
            python scripts/evm_mempool_load_harness.py
        }
    }

    if (-not $SkipPrepare) {
        Write-Step "E) PREPARE 48h (does not start soak)"
        Invoke-Check "prepare_48h_soak" {
            & (Join-Path $Root "scripts\prepare_48h_soak.ps1")
        }
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok -eq $true }).Count
$total = $steps.Count
$failedNames = @($steps | Where-Object { -not $_.ok -and -not $_.soft } | ForEach-Object { $_.name })

$stepRows = @()
foreach ($s in $steps) {
    $stepRows += @{
        name = [string]$s.name
        ok = [bool]$s.ok
        exit_code = [int]$s.exit_code
        soft = [bool]$s.soft
    }
}

$report = @{
    ok = ($fail -eq 0)
    mode = [string]$Mode
    rebuild = [bool]$Rebuild
    fail_count = [int]$fail
    passed = [int]$passed
    total = [int]$total
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    failed_steps = @($failedNames)
    steps = $stepRows
    honesty = @(
        "NOT soak started",
        "NOT mainnet",
        "NOT Hybrid audit pin",
        "PASS here != 48h soak PASS"
    )
}

$reportDir = Join-Path $Root "logs"
if (-not (Test-Path $reportDir)) {
    New-Item -ItemType Directory -Path $reportDir | Out-Null
}
$reportPath = Join-Path $reportDir "verify_global_rd_audit.json"
try {
    ($report | ConvertTo-Json -Depth 8) | Set-Content -Path $reportPath -Encoding utf8
} catch {
    Write-Host ("WARN: could not write report JSON: " + $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor Cyan
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS global R&D audit (" + $passed + "/" + $total + " steps, " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL global R&D audit (" + $fail + " hard fail(s), " + $passed + "/" + $total + ", " + $elapsed + "s)") -ForegroundColor Red
    if ($failedNames.Count -gt 0) {
        Write-Host ("  failed: " + ($failedNames -join ", ")) -ForegroundColor Red
    }
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
Write-Host "  soak (ONLY if you order it): .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
Write-Host ("=" * 72) -ForegroundColor Cyan

if ($fail -gt 0) { exit 1 }
exit 0
