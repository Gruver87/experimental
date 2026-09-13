# Wave E operator self-check (mempool demote Prom + pre-soak needles).
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

Write-Host "WAVE E self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) unit: Wave E demote gauges + Waves C/D regression"
python -m pytest -q tests/unit/test_wave_e_mempool_demote_metric.py tests/unit/test_wave_d_under_mesh_metric.py tests/unit/test_wave_c_peer_probe_retry.py tests/unit/test_wave_c_rocks_pack_fallback.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Wave C/D/E unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave C/D/E unit tests" -ForegroundColor Green
}

Step "2) unit: Markets FX (USD+EUR+BYN) + console nav"
python -m pytest -q tests/unit/test_market_feed.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: market_feed unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: market_feed unit tests" -ForegroundColor Green
}

Step "3) source needles (Prom + Grafana + launcher one-tab)"
$metricsPy = Get-Content -Raw -Path (Join-Path $Root "observability\metrics.py")
$portsPy = Get-Content -Raw -Path (Join-Path $Root "observability\ports.py")
$dash = Get-Content -Raw -Path (Join-Path $Root "deploy\grafana\dashboard.json")
$launcher = Get-Content -Raw -Path (Join-Path $Root "scripts\open_ops_console.ps1")
$glance = Get-Content -Raw -Path (Join-Path $Root "docs\AT_A_GLANCE.md")
if ($metricsPy -notmatch "abs_mempool_store_demoted") {
    Write-Host "FAIL: metrics missing abs_mempool_store_demoted" -ForegroundColor Red
    $fail++
} elseif ($portsPy -notmatch "mempool_store") {
    Write-Host "FAIL: MetricsSnapshot missing mempool_store" -ForegroundColor Red
    $fail++
} elseif ($dash -notmatch "abs_mempool_store_demoted") {
    Write-Host "FAIL: grafana missing demote panel" -ForegroundColor Red
    $fail++
} elseif ($launcher -notmatch [regex]::Escape('$paths = @("/")')) {
    Write-Host "FAIL: launcher default should open one main tab /" -ForegroundColor Red
    $fail++
} elseif ($glance -notmatch "AllTabs") {
    Write-Host "FAIL: AT_A_GLANCE should document -AllTabs" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: Wave E source needles" -ForegroundColor Green
}

if (-not $SkipGate) {
    Step "4) industrial_gate"
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
    Write-Host "RESULT: FAIL Wave E ($fail step(s))" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS Wave E self-check" -ForegroundColor Green
Write-Host "  Optional live scrape (mesh already up):" -ForegroundColor DarkGray
Write-Host "  curl http://127.0.0.1:18180/metrics | findstr abs_mempool_store_" -ForegroundColor DarkGray
Write-Host "  .\scripts\verify_pre_soak.ps1 -SkipMesh" -ForegroundColor DarkGray
Write-Host "  Soak only when ordered: .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
exit 0
