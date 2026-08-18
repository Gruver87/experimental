# Experimental ONE command: full project tests.
#
# Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.
#
# From repo root:
#   .\scripts\run_all_tests.ps1
#   .\scripts\run_all_tests.ps1 -SkipNative
#   .\scripts\run_all_tests.ps1 -SkipNative -RequireMesh
#   .\scripts\run_all_tests.ps1 -RebuildNative
#   .\scripts\run_all_tests.ps1 -FullAudit
#   .\scripts\run_all_tests.ps1 -Help
#
# Deep scan (native + cargo + all gates + live harness/catchup/status SLO):
#   .\scripts\verify_full_blockchain.ps1
#
# Hard fail-closed (no skips; cargo + live mesh + baked root required):
#   .\scripts\verify_hard_all.ps1
#
# Default: native self-test, pytest tests/, industrial_gate, soak honesty.
# Live mesh :18180-18182 is probed; down mesh is WARN unless -RequireMesh.
#
# -FullAudit also runs test_blockchain_full.ps1 (prod_gate, full_audit, extra pytest).
# That path still does NOT start soak.

param(
    [switch]$SkipNative,
    [switch]$RebuildNative,
    [switch]$SkipLive,
    [switch]$RequireMesh,
    [switch]$FullAudit,
    [int]$PytestTimeout = 900,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($Help) {
    Write-Host ""
    Write-Host "run_all_tests.ps1 - Experimental full project tests"
    Write-Host ""
    Write-Host "  Default:"
    Write-Host "    native self-test"
    Write-Host "    python -m pytest tests/"
    Write-Host "    python scripts/industrial_gate.py"
    Write-Host "    soak honesty (read-only; soak is NOT started)"
    Write-Host "    live mesh probe WARN if down"
    Write-Host ""
    Write-Host "  .\scripts\run_all_tests.ps1"
    Write-Host "  .\scripts\run_all_tests.ps1 -SkipNative"
    Write-Host "  .\scripts\run_all_tests.ps1 -SkipNative -RequireMesh"
    Write-Host "  .\scripts\run_all_tests.ps1 -RebuildNative"
    Write-Host "  .\scripts\run_all_tests.ps1 -FullAudit"
    Write-Host "  .\scripts\verify_hard_all.ps1          (fail-closed, no skips, no soak start)"
    Write-Host "  .\scripts\verify_full_blockchain.ps1   (deep scan, still no soak)"
    Write-Host ""
    Write-Host "  Does NOT start 48h soak. Does NOT rebuild Docker."
    Write-Host "  OK != public mainnet. Last Experimental 48h is FAIL until a new PASS."
    Write-Host "  Exit: 0 OK, 1 FAIL, 2 mesh required but unreachable"
    Write-Host ""
    exit 0
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host (" {0}" -f $Name)
    Write-Host ("=" * 72)
    $global:LASTEXITCODE = 0
    & $Command
    if ($null -eq $global:LASTEXITCODE) { $global:LASTEXITCODE = 0 }
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Write-Host ""
Write-Host "Experimental full project tests"
Write-Host " Repo: $Root"
Write-Host " Honesty: PASS != public mainnet. Soak is NOT started. Docker is NOT rebuilt."

if ($RebuildNative) {
    $SkipNative = $false
}

try {
    if ($RebuildNative) {
        Invoke-Step "native rebuild" {
            & (Join-Path $Root "scripts\build_native.ps1")
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }

    if (-not $SkipNative) {
        Invoke-Step "native crypto self-test" {
            python -c "from crypto import native; st=native.native_crypto_status(required=True); assert st['available'] and st['self_test'], st; print('OK native:', st)"
        }
    }

    if ($FullAudit) {
        $fullArgs = @{}
        if (-not $RebuildNative) { $fullArgs["SkipNativeBuild"] = $true }
        $fullArgs["PytestTimeout"] = $PytestTimeout
        Invoke-Step "full audit gate (test_blockchain_full.ps1)" {
            & (Join-Path $Root "scripts\test_blockchain_full.ps1") @fullArgs
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
    else {
        Invoke-Step "pytest tests/ (all project tests)" {
            python -m pytest -q --tb=line tests/
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Invoke-Step "industrial_gate" {
            python scripts/industrial_gate.py
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }

    $cbArgs = @(
        "scripts/check_blockchain.py",
        "--skip-tests",
        "--skip-gate"
    )
    if ($SkipLive) {
        $cbArgs += "--skip-live"
        Invoke-Step "soak honesty (read-only)" {
            python @cbArgs
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
    elseif ($RequireMesh) {
        Invoke-Step "live mesh + soak honesty" {
            python @cbArgs
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
    else {
        Invoke-Step "live mesh probe + soak honesty (mesh down = WARN)" {
            python @cbArgs
            if ($LASTEXITCODE -eq 2) {
                Write-Host "WARN: live mesh unreachable. Tests/gate already passed." -ForegroundColor Yellow
                Write-Host "  start mesh (does not start soak):" -ForegroundColor Yellow
                Write-Host "    .\scripts\docker_prod_3node.ps1 -KeepVolumes" -ForegroundColor Yellow
                Write-Host "    .\scripts\probe_prod_mesh.ps1 -Quick" -ForegroundColor Yellow
                $global:LASTEXITCODE = 0
                return
            }
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
}
catch {
    Write-Host ""
    Write-Host "RESULT: FAIL"
    Write-Host $_.Exception.Message
    exit 1
}

Write-Host ""
Write-Host "RESULT: OK"
Write-Host " Honesty: this is not a 48h soak PASS and not public mainnet."
Write-Host " Report: logs\check_blockchain.json"
exit 0
