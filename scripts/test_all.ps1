# Full blockchain verification - single entry point.
# Delegates to test_blockchain_full.ps1 (see that file for all flags).
#
# Quick local gate (recommended before push):
#   .\scripts\test_all.ps1
#   .\scripts\test_all.ps1 -SkipNativeBuild
#
# Maximum coverage:
#   .\scripts\test_all.ps1 -Docker -DockerBuild -Live -P2P
#
# Prod mesh already up on :18180-18182:
#   .\scripts\test_all.ps1 -SkipNativeBuild -ProdMesh
#
# Operator one-command (pytest tests/ + industrial_gate, no soak start):
#   .\scripts\run_all_tests.ps1
#   .\scripts\run_all_tests.ps1 -SkipNative

param(
    [switch]$Live,
    [switch]$P2P,
    [switch]$ProdMesh,
    [switch]$ProdMeshFull,
    [switch]$ProdMeshSpawn,
    [switch]$RecordEvidence,
    [switch]$Docker,
    [switch]$DockerBuild,
    [switch]$BuildRust,
    [switch]$SkipNativeBuild,
    [switch]$NoClean,
    [switch]$BridgeCutover,
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [int]$PytestTimeout = 900,
    [int]$P2PWait = 300,
    [int]$ProdMeshWait = 360,
    [int]$ProdMeshFailoverWait = 360,
    [string]$EvidenceGitTag = "v1.2.54",
    [int]$AuditRetries = 1
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ScriptDir "test_blockchain_full.ps1") @PSBoundParameters
exit $LASTEXITCODE
