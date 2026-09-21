# Industrial HIGH honesty - operator self-check (#18 slash, #19-20 demote,
# #24 bridge emit, #22 libp2p dial).
# Does NOT start soak. Does NOT rebuild Docker / mesh.
# Run:
#   .\scripts\verify_industrial_high_honesty.ps1
#   .\scripts\verify_industrial_high_honesty.ps1 -SkipGate
param(
    [switch]$SkipGate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0

function Write-Step([string]$Name) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Industrial HIGH honesty - operator self-check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Repo: $Root" -ForegroundColor DarkGray
Write-Host "  NOT soak / NOT mesh probe / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray
Write-Host ""

Write-Step "1 - unit: industrial HIGH honesty"
python -m pytest -v --tb=line tests/unit/test_industrial_high_honesty.py tests/unit/test_adr0021_phase2_store.py::test_store_fault_demotes_to_python tests/unit/test_wave_h_honesty_fixes.py::test_demote_forbidden_under_require
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: industrial HIGH unit pack" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: industrial HIGH unit pack" -ForegroundColor Green
}

Write-Step "2 - libp2p lab smoke (dial refuse without rust / fail-closed with rust)"
python scripts/libp2p_lab_smoke.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: libp2p_lab_smoke" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: libp2p_lab_smoke" -ForegroundColor Green
}

Write-Step "3 - source needles"
$reg = Get-Content -Raw -Path (Join-Path $Root "consensus\registry_adapter.py")
$mp = Get-Content -Raw -Path (Join-Path $Root "blockchain\mempool.py")
$br = Get-Content -Raw -Path (Join-Path $Root "bridge\adapter.py")
$lp = Get-Content -Raw -Path (Join-Path $Root "network\transport\libp2p_adapter\adapter.py")
$sm = Get-Content -Raw -Path (Join-Path $Root "consensus\bft\service.py")
if ($reg -notmatch "mark_slashed failed") {
    Write-Host "FAIL: mark_slashed must raise (no best-effort)" -ForegroundColor Red
    $fail++
} elseif ($mp -notmatch "Fail closed first: registry.demote") {
    Write-Host "FAIL: mempool demote must refuse under require before mutate" -ForegroundColor Red
    $fail++
} elseif ($br -notmatch "event_bus_emit_failed") {
    Write-Host "FAIL: bridge reject must surface bus emit failure" -ForegroundColor Red
    $fail++
} elseif ($lp -notmatch "stub dial removed") {
    Write-Host "FAIL: libp2p stub dial must be removed" -ForegroundColor Red
    $fail++
} elseif ($sm -notmatch "mark_slashed failed" -or $sm -notmatch "logger.exception\(`"\[RoundSM\] mark_slashed failed`"\)\s*\n\s*raise") {
    # PowerShell -match is single-line; check explicit raise-after-log block
    if ($sm -notmatch "(?s)mark_slashed failed.*?\r?\n\s*raise") {
        Write-Host "FAIL: RoundSM must re-raise mark_slashed failure" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: source needles" -ForegroundColor Green
    }
} else {
    Write-Host "OK: source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Write-Step "4 - industrial_gate"
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
    Write-Host ("RESULT: FAIL industrial HIGH ({0} step(s))" -f $fail) -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS industrial HIGH self-check" -ForegroundColor Green
Write-Host "  Soak only when ordered" -ForegroundColor DarkGray
exit 0
