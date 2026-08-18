# Deep Experimental blockchain check (host tests + live 3-node mesh).
#
# Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.
# Scan-all: a FAIL does not skip later steps. Scoreboard at the end.
#
# Hard (one command, no skips):
#   .\scripts\verify_hard_all.ps1
#   .\scripts\verify_full_blockchain.ps1 -Hard
#
# From repo root:
#   .\scripts\verify_full_blockchain.ps1
#   .\scripts\verify_full_blockchain.ps1 -SkipLive
#   .\scripts\verify_full_blockchain.ps1 -QuickPytest
#   .\scripts\verify_full_blockchain.ps1 -SkipCargo -SkipNative
#   .\scripts\verify_full_blockchain.ps1 -Help
#
# Report: logs\verify_full_blockchain.json
# Exit: 0 OK, 1 FAIL, 2 live mesh unreachable (static steps may still have passed)
# Hard exit: 0 OK, 1 FAIL (no soft exit 2)

param(
    [switch]$Hard,
    [switch]$SkipLive,
    [switch]$SkipNative,
    [switch]$SkipCargo,
    [switch]$SkipPytest,
    [switch]$QuickPytest,
    [switch]$SkipGate,
    [switch]$RequireSoak48h,
    [switch]$RequireBakedRoot,
    [int]$PytestTimeout = 1200,
    [int]$P2pWait = 90,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($Help) {
    Write-Host ""
    Write-Host "verify_full_blockchain.ps1 - deep Experimental check"
    Write-Host ""
    Write-Host "  Host:"
    Write-Host "    native crypto self-test"
    Write-Host "    cargo test abs_native (skip if cargo missing)"
    Write-Host "    secrets scan, prod_gate, k8s_prod_gate, verify_prod_stack"
    Write-Host "    industrial_gate"
    Write-Host "    pytest tests/  (or -QuickPytest industrial slice)"
    Write-Host "    soak honesty (read-only; soak is NOT started)"
    Write-Host ""
    Write-Host "  Live mesh :18180-:18182:"
    Write-Host "    probe, harness, catch-up, /status SLO, soak preflight, p2p_ci"
    Write-Host "    baked committed state_root inside node1 (WARN if image stale)"
    Write-Host ""
    Write-Host "  .\scripts\verify_hard_all.ps1          (fail-closed, no skips)"
    Write-Host "  .\scripts\verify_full_blockchain.ps1 -Hard"
    Write-Host "  .\scripts\verify_full_blockchain.ps1"
    Write-Host "  .\scripts\verify_full_blockchain.ps1 -SkipLive"
    Write-Host "  .\scripts\verify_full_blockchain.ps1 -QuickPytest"
    Write-Host "  .\scripts\verify_full_blockchain.ps1 -SkipCargo -SkipNative"
    Write-Host ""
    Write-Host "  Does NOT start 48h soak. Does NOT rebuild Docker."
    Write-Host "  OK != public mainnet. Last Experimental 48h is FAIL until a new PASS."
    Write-Host "  Report: logs\verify_full_blockchain.json"
    Write-Host "  Exit: 0 OK, 1 FAIL, 2 mesh unreachable"
    Write-Host ""
    exit 0
}

$pyArgs = @("scripts/verify_full_blockchain.py")
if ($Hard) { $pyArgs += "--hard" }
if ($SkipLive) { $pyArgs += "--skip-live" }
if ($SkipNative) { $pyArgs += "--skip-native" }
if ($SkipCargo) { $pyArgs += "--skip-cargo" }
if ($SkipPytest) { $pyArgs += "--skip-pytest" }
if ($QuickPytest) { $pyArgs += "--quick-pytest" }
if ($SkipGate) { $pyArgs += "--skip-gate" }
if ($RequireSoak48h) { $pyArgs += "--require-soak-48h" }
if ($RequireBakedRoot) { $pyArgs += "--require-baked-root" }
$pyArgs += @("--pytest-timeout", "$PytestTimeout")
$pyArgs += @("--p2p-wait", "$P2pWait")

python @pyArgs
exit $LASTEXITCODE
