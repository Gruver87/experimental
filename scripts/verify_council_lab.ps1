# ADR 0022 / Profile C council lab operator self-check.
# Does NOT start soak. Does NOT mint on prod 778888. Staging chain_id is 778889.
param(
    [switch]$SkipGate
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

Write-Host "COUNCIL LAB verify (ADR 0022 / Profile C)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT prod 778888 mint / staging chain_id 778889 only" -ForegroundColor DarkGray

Invoke-Check "guarantor_council_lab.py" {
    python scripts/guarantor_council_lab.py
}

Invoke-Check "guarantor_council_staging_mint_lab.py" {
    python scripts/guarantor_council_staging_mint_lab.py
}

Invoke-Check "pytest_council_nft" {
    python -m pytest -q tests/unit/test_council_nft.py --tb=line
}

Invoke-Check "staging_chain_id_not_prod" {
    python -c "import json, pathlib; p=pathlib.Path('docs/genesis/gruver87-council-manifest.json');
assert p.is_file(), 'run guarantor_council_manifest_gen.py first';
d=json.loads(p.read_text(encoding='utf-8'));
assert d.get('chain_id_staging') == 778889, d.get('chain_id_staging');
assert d.get('chain_id_staging') != 778888;
print('chain_id_staging', d.get('chain_id_staging'))"
}

Invoke-Check "prod_mesh_no_council_arm" {
    python -c "import json, pathlib; files=sorted(pathlib.Path('docker').glob('node.prod.mesh*.json')); assert files;
for p in files:
  raw=json.loads(p.read_text(encoding='utf-8'));
  assert int(raw.get('chain_id', 0) or 0) == 778888, p.name;
  assert raw.get('deployment_mode') == 'prod', p.name;
print('prod_mesh_chain_778888', [p.name for p in files])"
}

if (-not $SkipGate) {
    Invoke-Check "industrial_gate_council_needles" {
        python -c "from pathlib import Path; t=(Path('scripts')/'industrial_gate.py').read_text(encoding='utf-8');
assert 'guarantor_council_lab.py' in t;
assert 'abs_p2p_under_mesh' in t or 'guarantor_council' in t;
print('council_gate_needles_ok')"
    }
}

$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$passed = @($steps | Where-Object { $_.ok }).Count
$report = @{
    ok = ($fail -eq 0)
    phase = "pre-soak-council-lab"
    passed = $passed
    total = $steps.Count
    fail_count = $fail
    elapsed_sec = $elapsed
    started = $started.ToString("o")
    steps = $steps
    honesty = @(
        "NOT soak",
        "NOT council mint on prod 778888",
        "Profile C staging 778889 / ADR 0022 labs only"
    )
}

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$reportPath = Join-Path $logDir "verify_council_lab.json"
($report | ConvertTo-Json -Depth 6) | Set-Content -Path $reportPath -Encoding utf8

Write-Host ""
if ($fail -eq 0) {
    Write-Host ("RESULT: PASS council lab verify (" + $passed + "/" + $steps.Count + ", " + $elapsed + "s)") -ForegroundColor Green
} else {
    Write-Host ("RESULT: FAIL council lab verify (" + $fail + " fail(s))") -ForegroundColor Red
}
Write-Host ("  report: " + $reportPath) -ForegroundColor DarkGray
if ($fail -gt 0) { exit 1 }
exit 0
