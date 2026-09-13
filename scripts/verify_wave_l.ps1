# Wave L operator self-check.
# Does NOT start soak. Does NOT rebuild Docker / mesh.
param(
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0

function Step([string]$Name) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

Write-Host "WAVE L self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave L honesty pack"
python -m pytest -q tests/unit/test_wave_l_honesty_fixes.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave L unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave L unit tests" -ForegroundColor Green
}

Step "2) source needles"
$bv = Get-Content -Raw -Path (Join-Path $Root "execution\block_validator.py")
$bc = Get-Content -Raw -Path (Join-Path $Root "core\blockchain.py")
$nft = Get-Content -Raw -Path (Join-Path $Root "features\nft.py")
$br = Get-Content -Raw -Path (Join-Path $Root "bridge\store_adapter.py")
$http = Get-Content -Raw -Path (Join-Path $Root "api\http.py")
if ($bv -match 'float\(tx\.get\("value"') {
    Write-Host "FAIL: block_validator still float value" -ForegroundColor Red
    $fail++
} elseif ($bc -notmatch 'getattr\(config, "require_signatures"') {
    Write-Host "FAIL: require_signatures not from config" -ForegroundColor Red
    $fail++
} elseif ($nft -notmatch "balance_delta_satoshi") {
    Write-Host "FAIL: nft not satoshi" -ForegroundColor Red
    $fail++
} elseif ($br -notmatch "confirm_did_not_persist") {
    Write-Host "FAIL: bridge confirm still paints green" -ForegroundColor Red
    $fail++
} elseif ($http -notmatch "_nft_mutation_authorized") {
    Write-Host "FAIL: nft mutation auth missing" -ForegroundColor Red
    $fail++
} elseif ($nft -notmatch "nft_council_gate_unavailable") {
    Write-Host "FAIL: council ImportError still fail-open" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave L source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Step "3) industrial_gate"
    python scripts/industrial_gate.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: industrial_gate" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: industrial_gate" -ForegroundColor Green
    }
} else {
    Write-Host "SKIP industrial_gate (-SkipGate)" -ForegroundColor Yellow
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "RESULT: FAIL Wave L ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave L self-check" -ForegroundColor Green
Write-Host "  Also: .\scripts\verify_wave_k.ps1 -SkipGate" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
