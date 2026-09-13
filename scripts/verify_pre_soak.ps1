# Pre-soak operator self-check (ADR 0021 harden + live mesh).
# Does NOT start 48h soak. Does NOT rebuild Docker.
param(
    [switch]$SkipMesh,
    [switch]$SkipPrepare
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$fail = 0

function Step([string]$Name) {
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

Write-Host "PRE-SOAK self-check (Experimental)" -ForegroundColor Cyan
Write-Host "  NOT soak / NOT mainnet / NOT Hybrid pin" -ForegroundColor DarkGray

Step "1) ADR 0021 host kernels+store (require rust)"
python scripts/verify_adr0021_phase1.py --require-rust --skip-mesh
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: ADR 0021 host verify" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: ADR 0021 host verify" -ForegroundColor Green
}

Step "2) demote harden present in source"
$mp = Join-Path $Root "blockchain\mempool.py"
$txt = Get-Content -Raw -Path $mp
if ($txt -notmatch "_demote_store") {
    Write-Host "FAIL: blockchain/mempool.py missing _demote_store" -ForegroundColor Red
    $fail++
} elseif ($txt -notmatch "insert:") {
    Write-Host "FAIL: demote path not wired on insert" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: demote harden in mempool.py" -ForegroundColor Green
}

Step "2b) fee_satoshi dual-write (store/sort key)"
$storeRs = Join-Path $Root "native\abs_native\src\mempool_store.rs"
$storeTxt = Get-Content -Raw -Path $storeRs
if ($txt -notmatch "fee_satoshi" -or $txt -notmatch "min_fee_satoshi") {
    Write-Host "FAIL: mempool.py missing fee_satoshi / min_fee_satoshi dual-write" -ForegroundColor Red
    $fail++
} elseif ($storeTxt -notmatch "fee_satoshi" -or $storeTxt -notmatch "min_fee_satoshi") {
    Write-Host "FAIL: mempool_store.rs missing fee_satoshi sort key" -ForegroundColor Red
    $fail++
} elseif ($storeTxt -match "partial_cmp\(&a\.fee\)") {
    Write-Host "FAIL: mempool_store.rs still sorts on float fee" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: fee_satoshi dual-write in Python + Rust store" -ForegroundColor Green
}

Step "3) unit: demote + port shape"
python -m pytest -q tests/unit/test_adr0021_phase2_store.py tests/unit/test_mempool_port.py --tb=line
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: demote/port unit tests" -ForegroundColor Red
    $fail++
} else {
    Write-Host "OK: demote/port unit tests" -ForegroundColor Green
}

if (-not $SkipMesh) {
    Step "4) container has demote + rust store"
    # Use only single quotes inside Python so PowerShell/docker do not strip them.
    docker exec abs-prod-mesh3-node1-1 python -c "import inspect; from blockchain.mempool import Mempool; s=inspect.getsource(Mempool._demote_store); assert 'demote rust store' in s; st=Mempool(4,0.0).get_stats(); print('store_backend=', st.get('store_backend')); print('demote_ok=True')"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: container demote/store check (is mesh up?)" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: container demote + store" -ForegroundColor Green
    }

    Step "5) probe_prod_mesh -Quick"
    & (Join-Path $Root "scripts\probe_prod_mesh.ps1") -Quick
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: mesh probe" -ForegroundColor Red
        $fail++
    } else {
        Write-Host "OK: mesh probe" -ForegroundColor Green
    }

    if (-not $SkipPrepare) {
        Step "6) prepare_48h_soak (fresh pin; does not start soak)"
        & (Join-Path $Root "scripts\prepare_48h_soak.ps1")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAIL: prepare_48h_soak NOT READY" -ForegroundColor Red
            $fail++
        } else {
            Write-Host "OK: prepare READY for 48h" -ForegroundColor Green
        }
    }
} else {
    Write-Host "SKIP mesh/prepare (-SkipMesh)" -ForegroundColor Yellow
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "RESULT: FAIL ($fail step(s)) - do not start soak" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: PASS pre-soak checks" -ForegroundColor Green
Write-Host "  To start soak ONLY when you order it:" -ForegroundColor DarkGray
Write-Host "  .\scripts\start_soak_prod_mesh_48h.ps1" -ForegroundColor DarkGray
exit 0
