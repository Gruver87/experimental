# ONE hard Experimental project check (fail-closed).
#
# Does NOT start 48h soak. Does NOT rebuild Docker. Does NOT claim mainnet.
# Refuses skip flags. Cargo, live mesh :18180-18182, and baked state_root are required.
# Last Experimental 48h soak is reported honestly; it is NOT a PASS bar for this script.
#
# From repo root:
#   .\scripts\verify_hard_all.ps1
#
# Same as:
#   python scripts/verify_full_blockchain.py --hard
#
# Covers:
#   native crypto self-test
#   cargo test abs_native
#   cargo test rust_bridge
#   secrets scan
#   prod_gate, k8s_prod_gate, verify_prod_stack, industrial_gate
#   industrial waves needles
#   experimental R&D units + labs
#   pytest tests/ (full tree)
#   soak honesty (read-only; soak is NOT started)
#   live mesh probe, harness, catch-up, /status SLO, soak preflight, p2p_ci
#   baked committed state_root inside the running image
#
# Not included (separate command, needs Cargo feature libp2p):
#   .\scripts\verify_adr0019_libp2p_hard.ps1
#
# Report: logs\verify_full_blockchain.json
# Exit: 0 OK, 1 FAIL (mesh down is FAIL, not a soft exit 2)

param(
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($Help) {
    Write-Host ""
    Write-Host "verify_hard_all.ps1 - fail-closed full Experimental project check"
    Write-Host ""
    Write-Host "  .\scripts\verify_hard_all.ps1"
    Write-Host ""
    Write-Host "  Does NOT start 48h soak. Does NOT rebuild Docker."
    Write-Host "  OK != public mainnet. 48h soak PASS is not required by this script."
    Write-Host "  Report: logs\verify_full_blockchain.json"
    Write-Host "  Exit: 0 OK, 1 FAIL"
    Write-Host ""
    exit 0
}

Write-Host "HARD ALL: python scripts/verify_full_blockchain.py --hard"
Write-Host "Honesty: soak is NOT started. Docker is NOT rebuilt. PASS != public mainnet."
python scripts/verify_full_blockchain.py --hard
exit $LASTEXITCODE
