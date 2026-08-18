# Full 48h soak preflight for Experimental prod mesh. Does NOT start the soak.
# 5h STRICT is a different bar. Historical Hybrid/tip-v2 48h PASS is a different tree.
param(
    [int]$Hours = 48,
    [int]$IntervalSec = 300,
    [int]$MinerHarnessSamples = 5,
    [int]$MinFreeGb = 15,
    [switch]$RequireP2pTls,
    [switch]$SkipP2pTlsCheck,
    [switch]$SkipMinerHarness
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$wantTls = $true
if ($SkipP2pTlsCheck) { $wantTls = $false }
elseif ($PSBoundParameters.ContainsKey("RequireP2pTls") -and -not $RequireP2pTls) { $wantTls = $false }

$fail = 0
$gitSha = ""
$gitDirty = $false
$imageId = ""
function Fail-Step([string]$Msg) {
    Write-Host "FAIL: $Msg" -ForegroundColor Red
    $script:fail = 1
}

Write-Host "48h soak PREPARE (Experimental) - does not start soak" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s TLS=$(if ($wantTls) { 'required' } else { 'skipped' })" -ForegroundColor DarkGray
Write-Host "  scoring: default 48h (hard_fails=0). Not 5h STRICT. Not Hybrid historical PASS." -ForegroundColor DarkGray

Write-Host "1) leftover soak monitors" -ForegroundColor Cyan
& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force
if ($LASTEXITCODE -ne 0) { Fail-Step "stop_soak_monitors" }

Write-Host "2) disk free (need >= ${MinFreeGb} GB on C:)" -ForegroundColor Cyan
try {
    $freeGb = [Math]::Round((Get-PSDrive C).Free / 1GB, 1)
    Write-Host "  C: free=${freeGb} GB" -ForegroundColor DarkGray
    if ($freeGb -lt $MinFreeGb) { Fail-Step "disk free ${freeGb} GB < ${MinFreeGb} GB" }
} catch {
    Fail-Step "disk check: $($_.Exception.Message)"
}
Write-Host "  keep Windows Sleep=Never on AC for 48h (do not let the PC sleep)" -ForegroundColor Yellow

Write-Host "2b) docker disk (warn)" -ForegroundColor Cyan
docker system df 2>$null | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

Write-Host "3) docker prod mesh healthy" -ForegroundColor Cyan
$need = @("abs-prod-mesh3-node1-1", "abs-prod-mesh3-node2-1", "abs-prod-mesh3-node3-1", "abs-prod-mesh3-redis-1")
try {
    $rows = @(docker ps --format "{{.Names}}|{{.Status}}" 2>$null)
    foreach ($name in $need) {
        $hit = $rows | Where-Object { $_ -like "$name|*" } | Select-Object -First 1
        if (-not $hit) {
            Fail-Step "container $name not running"
            continue
        }
        Write-Host "  $hit" -ForegroundColor DarkGray
        if ($hit -match '\(unhealthy\)') {
            Fail-Step "container $name unhealthy ($hit)"
        } elseif ($hit -notmatch '\(healthy\)') {
            Fail-Step "container $name not healthy ($hit)"
        }
    }
} catch {
    Fail-Step "docker ps: $($_.Exception.Message)"
}

Write-Host "3b) baked image pin (committed state_root + container==local tag)" -ForegroundColor Cyan
$imageId = ""
$containerImage = ""
$gitSha = ""
$gitDirty = $false
try {
    $gitSha = (git rev-parse HEAD 2>$null | Out-String).Trim()
    $gitDirty = [bool](git status --porcelain 2>$null)
    Write-Host "  git=$gitSha dirty=$gitDirty" -ForegroundColor DarkGray
    if ($gitDirty) {
        Write-Host "  WARN: working tree dirty - uncommitted host files are not in soak unless baked into the image" -ForegroundColor Yellow
    }
} catch { }
try {
    $imageId = (docker inspect abs-blockchain-prod:local --format "{{.Id}}" 2>$null | Out-String).Trim()
    $containerImage = (docker inspect abs-prod-mesh3-node1-1 --format "{{.Image}}" 2>$null | Out-String).Trim()
    Write-Host "  image=$imageId" -ForegroundColor DarkGray
    if (-not $imageId) { Fail-Step "image abs-blockchain-prod:local missing" }
    elseif ($containerImage -and ($containerImage -ne $imageId)) {
        Fail-Step "node1 Image != abs-blockchain-prod:local (recreate mesh with docker_prod_3node.ps1 -KeepVolumes)"
    }
} catch {
    Fail-Step "docker inspect image pin: $($_.Exception.Message)"
}
$needleOut = ""
try {
    $needleSrc = Join-Path $Root "scripts\check_baked_state_root.py"
    docker cp $needleSrc abs-prod-mesh3-node1-1:/tmp/check_baked_state_root.py | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "docker cp check_baked_state_root.py into node1"
    } else {
        $needleOut = docker exec -w /app -e PYTHONPATH=/app abs-prod-mesh3-node1-1 python /tmp/check_baked_state_root.py
        Write-Host "  get_state_root=$($needleOut.Trim())" -ForegroundColor DarkGray
        if ($LASTEXITCODE -ne 0 -or $needleOut.Trim() -ne "COMMITTED_STATE_ROOT_OK") {
            Fail-Step "image missing committed state_root fix; rebuild: .\scripts\docker_prod_3node.ps1 -KeepVolumes"
        }
    }
} catch {
    Fail-Step "docker exec state_root needle: $($_.Exception.Message)"
}

Write-Host "4) soak_preflight (TLS + wire probe on all 3 nodes)" -ForegroundColor Cyan
$pf = @("scripts/soak_preflight.py", "--hours", $Hours, "--interval-sec", $IntervalSec, "--require-wire-probe")
if ($wantTls) { $pf += "--require-p2p-tls" }
python @pf
if ($LASTEXITCODE -ne 0) { Fail-Step "soak_preflight" }

Write-Host "5) probe_prod_mesh -Quick" -ForegroundColor Cyan
& (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick
if ($LASTEXITCODE -ne 0) { Fail-Step "probe_prod_mesh -Quick" }

Write-Host "6) check_mesh_catchup live (ready + consist/topo/wire)" -ForegroundColor Cyan
& (Join-Path $ScriptDir "check_mesh_catchup.ps1")
$catchupRc = $LASTEXITCODE
for ($ci = 2; $ci -le 3 -and $catchupRc -ne 0; $ci++) {
    Write-Host "  catchup live retry $ci/3 (SkipUnit; transient consist/topo flap)" -ForegroundColor Yellow
    Start-Sleep -Seconds 8
    & (Join-Path $ScriptDir "check_mesh_catchup.ps1") -SkipUnit
    $catchupRc = $LASTEXITCODE
}
if ($catchupRc -ne 0) { Fail-Step "check_mesh_catchup" }

if (-not $SkipMinerHarness) {
    Write-Host "7) miner full harness x$MinerHarnessSamples (peer_probe_ok must pass)" -ForegroundColor Cyan
    $ok = 0
    $bad = 0
    for ($i = 1; $i -le $MinerHarnessSamples; $i++) {
        try {
            $h = Invoke-RestMethod "http://127.0.0.1:18180/chain/consistency/harness?peer_timeout=8" -TimeoutSec 45
            $st = Invoke-RestMethod "http://127.0.0.1:18180/status" -TimeoutSec 15
            $healthy = [bool]$h.harness_healthy
            if ($healthy) { $ok++ } else { $bad++ }
            Write-Host ("  try{0} h={1} healthy={2} failed={3} err={4}" -f $i, $st.height, $h.harness_healthy, ($h.failed_checks -join ","), $h.peer_probe_error)
        } catch {
            $bad++
            Write-Host "  try$i harness exception: $($_.Exception.Message)" -ForegroundColor Yellow
        }
        if ($i -lt $MinerHarnessSamples) { Start-Sleep -Seconds 12 }
    }
    Write-Host "  miner harness ok=$ok fail=$bad" -ForegroundColor DarkGray
    if ($bad -gt 0) { Fail-Step "miner full harness failed $bad/$MinerHarnessSamples" }
}

$prep = @{
    ok = ($fail -eq 0)
    hours = $Hours
    interval_sec = $IntervalSec
    prepared_at = (Get-Date -Format "o")
    git_sha = $gitSha
    git_dirty = $gitDirty
    image_id = $imageId
    note = "Experimental 48h prep. Not a soak PASS. Do not rebuild Docker until soak ends."
    start_command = ".\scripts\start_soak_prod_mesh_48h.ps1 -Hours $Hours -IntervalSec $IntervalSec"
}
$prepPath = Join-Path $Root "logs/soak_48h_prep.json"
$prep | ConvertTo-Json | Set-Content -Path $prepPath -Encoding UTF8

if ($fail -ne 0) {
    Write-Host "RESULT: NOT READY for 48h soak (see failures above)" -ForegroundColor Red
    Write-Host "  report: $prepPath" -ForegroundColor DarkGray
    exit 1
}

Write-Host "RESULT: READY for 48h soak" -ForegroundColor Green
Write-Host "  report: $prepPath" -ForegroundColor DarkGray
Write-Host "  start:  $($prep.start_command)" -ForegroundColor DarkGray
Write-Host "  check:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  stop:   .\scripts\stop_soak_monitors.ps1 -Force" -ForegroundColor DarkGray
Write-Host "  keep PC awake; avoid docker rebuild / -KeepVolumes until 48h ends" -ForegroundColor Yellow
exit 0
