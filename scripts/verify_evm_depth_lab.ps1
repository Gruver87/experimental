# EVM depth lab operator self-check (Profile A / ADR 0010).
# Wraps host labs + focused unit + industrial_gate. Does NOT start soak.
# Mesh smoke is optional (-WithMesh) via evm_pre_48h_harness without --skip-mesh.
param(
    [switch]$SkipGate,
    [switch]$WithMesh
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0
$started = Get-Date
$steps = @()

function Invoke-Check([string]$Name, [scriptblock]$Command) {
    Write-Host ""
    Write-Host (">>> " + $Name) -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $Command
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }
    $ok = ($rc -eq 0)
    $script:steps += @{ name = $Name; ok = $ok; exit_code = $rc }
    if ($ok) {
        Write-Host ("OK: " + $Name) -ForegroundColor Green
    } else {
        Write-Host ("FAIL: " + $Name + " (exit " + $rc + ")") -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "EVM DEPTH LAB verify (pre-soak)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT EVM-only 48h claim / NOT mainnet / NOT BLS" -ForegroundColor DarkGray

if ($WithMesh) {
    Invoke-Check "evm_pre_48h_harness.py" {
        python scripts/evm_pre_48h_harness.py
    }
} else {
    Invoke-Check "evm_pre_48h_harness.py --skip-mesh" {
        python scripts/evm_pre_48h_harness.py --skip-mesh
    }
}

Invoke-Check "evm_lab_scripts_present" {
    python -c "from pathlib import Path; labs=['evm_precompile_lab.py','evm_rpc_lab.py','evm_nested_lab.py','evm_reorg_lab.py','evm_logs_lab.py','evm_filters_lab.py'];
root=Path('scripts');
missing=[n for n in labs if not (root/n).is_file()];
assert not missing, missing;
print('evm_labs', len(labs))"
}

Invoke-Check "compat_matrix_honesty_needles" {
    python -c "from pathlib import Path; t=(Path('docs')/'sprouts'/'EVM_COMPAT_MATRIX.md').read_text(encoding='utf-8');
assert 'eth_estimateGas' in t and 'Partial' in t;
assert 'eth_subscribe' not in t or 'not WS' in t.lower() or 'polling' in t.lower();
print('compat_matrix_needles_ok')"
}

if (-not $SkipGate) {
    Invoke-Check "industrial_gate_evm_depth_needles" {
        python -c "from pathlib import Path; t=(Path('scripts')/'industrial_gate.py').read_text(encoding='utf-8');
assert 'evm_rpc_lab.py' in t;
assert 'evm_pre_48h_harness.py' in t;
print('evm_gate_needles_ok')"
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "pre-soak-evm-depth-lab"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    with_mesh = [bool]$WithMesh
    steps = $steps
    honesty = @(
        "NOT soak",
        "NOT EVM-only 48h claim",
        "NOT mainnet / NOT BLS",
        "host labs via evm_pre_48h_harness (mesh optional -WithMesh)"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_evm_depth_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS EVM depth lab verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL EVM depth lab verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
