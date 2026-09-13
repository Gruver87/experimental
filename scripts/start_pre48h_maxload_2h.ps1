# Pre-48h MAX-LOAD 2h STRICT audit (Experimental prod mesh).
#
# Operator-ordered stress: host gates + live mesh probe + extreme load + 2h STRICT soak.
# Does NOT claim 48h PASS / mainnet / Hybrid pin / BLS.
# PASS bar for the 2h window: hard_fails=0, mesh_warn=0 (STRICT), no ready-flap.
#
# Usage (repo root):
#   .\scripts\start_pre48h_maxload_2h.ps1
#   .\scripts\start_pre48h_maxload_2h.ps1 -Rebuild          # bake image with latest code
#   .\scripts\start_pre48h_maxload_2h.ps1 -SkipRebuild       # use running mesh (faster)
#   .\scripts\start_pre48h_maxload_2h.ps1 -PreflightOnly     # no soak start
#   .\scripts\start_pre48h_maxload_2h.ps1 -Foreground        # soak in this console
#
# Monitor:
#   Get-Content logs\soak_2h_pre48h_maxload.log -Wait -Tail 40
#   .\scripts\check_soak.ps1
#   Get-Content logs\soak_report_2h_pre48h_maxload.json

param(
    [switch]$Rebuild,
    [switch]$SkipRebuild,
    [switch]$SkipHostAudit,
    [switch]$SkipLoad,
    [switch]$PreflightOnly,
    [switch]$Foreground,
    [int]$Hours = 2,
    [int]$IntervalSec = 30,
    [int]$LoadRounds = 80,
    [int]$LoadWorkers = 12,
    [int]$HttpWorkers = 32,
    [int]$HttpRequests = 40
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$LogFile = "logs/soak_2h_pre48h_maxload.log"
$ReportFile = "logs/soak_report_2h_pre48h_maxload.json"
$AuditReport = "logs/pre48h_maxload_2h_audit.json"
$fail = 0
$steps = New-Object System.Collections.Generic.List[object]
$started = Get-Date

function Step([string]$Name) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Cyan
    Write-Host ("  " + $Name) -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor Cyan
}

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Command,
        [switch]$Soft
    )
    Write-Host ""
    Write-Host (">>> " + $Name) -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $Command
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }
    $ok = ($rc -eq 0)
    [void]$steps.Add(@{ name = $Name; ok = $ok; exit_code = $rc; soft = [bool]$Soft })
    if ($ok) {
        Write-Host ("OK: " + $Name) -ForegroundColor Green
    } elseif ($Soft) {
        Write-Host ("WARN: " + $Name + " (soft, exit $rc)") -ForegroundColor Yellow
    } else {
        Write-Host ("FAIL: " + $Name + " (exit $rc)") -ForegroundColor Red
        $script:fail++
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

Write-Host ""
Write-Host "PRE-48h MAX-LOAD 2h STRICT (Experimental)" -ForegroundColor Cyan
Write-Host "  hours=$Hours interval=${IntervalSec}s load rounds=$LoadRounds workers=$LoadWorkers" -ForegroundColor DarkGray
Write-Host "  NOT 48h claim / NOT mainnet / NOT Hybrid pin / NOT BLS" -ForegroundColor DarkGray
Write-Host ("  started " + $started.ToString("o")) -ForegroundColor DarkGray

# ── 0) stop leftover monitors ─────────────────────────────────────────────
Step "0) stop leftover soak monitors"
& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force

# ── 1) HOST max audit ─────────────────────────────────────────────────────
if (-not $SkipHostAudit) {
    Step "1) HOST max audit (static + units + industrial_gate)"

    Invoke-Check "industrial_gate" { python scripts/industrial_gate.py }
    Invoke-Check "ADR0021 require-rust" { python scripts/verify_adr0021_phase1.py --require-rust --skip-mesh }
    Invoke-Check "final_audit" { python scripts/final_audit.py }
    Invoke-Check "mega_audit" { python scripts/mega_audit.py } -Soft
    Invoke-Check "verify_experimental_rd" { python scripts/verify_experimental_rd.py } -Soft

    Invoke-Check "wave honesty H-R units" {
        python -m pytest -q `
            tests/unit/test_wave_h_honesty_fixes.py `
            tests/unit/test_wave_i_honesty_fixes.py `
            tests/unit/test_wave_j_honesty_fixes.py `
            tests/unit/test_wave_k_honesty_fixes.py `
            tests/unit/test_wave_l_honesty_fixes.py `
            tests/unit/test_wave_m_honesty_fixes.py `
            tests/unit/test_wave_n_honesty_fixes.py `
            tests/unit/test_wave_o_honesty_fixes.py `
            tests/unit/test_wave_p_honesty_fixes.py `
            tests/unit/test_wave_q_honesty_fixes.py `
            tests/unit/test_wave_r_honesty_fixes.py `
            --tb=line
    }

    Invoke-Check "core/evm/mempool unit pack" {
        python -m pytest -q `
            tests/unit/test_evm_runtime.py `
            tests/unit/test_evm_rpc_compat.py `
            tests/unit/test_adr0021_phase2_store.py `
            tests/unit/test_mempool_port.py `
            tests/unit/test_native_consensus_select.py `
            tests/unit/test_native_p2p_wire.py `
            tests/unit/test_eth_raw_tx.py `
            --tb=line
    }
} else {
    Write-Host "SKIP host audit (-SkipHostAudit)" -ForegroundColor Yellow
}

if ($fail -gt 0) {
    Write-Host "ABORT: host audit failed ($fail). Fix before mesh soak." -ForegroundColor Red
    exit 1
}

# ── 2) MESH bring-up / pin ────────────────────────────────────────────────
$doRebuild = $false
if ($Rebuild) { $doRebuild = $true }
if ($SkipRebuild) { $doRebuild = $false }
elseif (-not $Rebuild -and -not $SkipRebuild) {
    # Default: rebuild so Wave R+ honesty is in the image under audit.
    $doRebuild = $true
}

Step "2) prod 3-node mesh (Rebuild=$doRebuild)"
if ($doRebuild) {
    Invoke-Check "docker_prod_3node rebuild" {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -KeepVolumes
    }
} else {
    Invoke-Check "docker_prod_3node keep volumes skip build" {
        & (Join-Path $ScriptDir "docker_prod_3node.ps1") -SkipBuild -KeepVolumes
    } -Soft
}

# ── 3) LIVE probe + prepare ───────────────────────────────────────────────
Step "3) live mesh probe + 48h prepare (does not start 48h)"
Invoke-Check "probe_prod_mesh -Quick" {
    & (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick
}
Invoke-Check "prepare_48h_soak" {
    & (Join-Path $ScriptDir "prepare_48h_soak.ps1")
}
Invoke-Check "evm_pre_48h_harness" {
    python scripts/evm_pre_48h_harness.py
}

if ($fail -gt 0) {
    Write-Host "ABORT: mesh/preflight failed ($fail). Do not start 2h soak." -ForegroundColor Red
    exit 1
}

# ── 4) MAX LOAD (before soak window) ──────────────────────────────────────
if (-not $SkipLoad) {
    Step "4) MAX LOAD burst (EVM/mempool + HTTP fan-out)"

    Invoke-Check "evm_mempool_load_harness extreme" {
        python scripts/evm_mempool_load_harness.py --rounds $LoadRounds --workers $LoadWorkers --batch 16
    }

    foreach ($port in @(18180, 18181, 18182)) {
        $p = $port
        Invoke-Check ("HTTP load :$p /health/live") {
            python scripts/load_test.py --url "http://127.0.0.1:$p/health/live" --workers $HttpWorkers --requests $HttpRequests
        }
        Invoke-Check ("HTTP load :$p /status") {
            python scripts/load_test.py --url "http://127.0.0.1:$p/status" --workers ([Math]::Max(8, $HttpWorkers / 2)) --requests ([Math]::Max(10, $HttpRequests / 2))
        } -Soft
    }

    Invoke-Check "prod_evm_smoke" {
        python scripts/prod_evm_smoke.py
    }
} else {
    Write-Host "SKIP load burst (-SkipLoad)" -ForegroundColor Yellow
}

# Re-probe after load (catch tip skew / crash)
Step "4b) post-load probe"
Invoke-Check "probe_prod_mesh -Quick (post-load)" {
    & (Join-Path $ScriptDir "probe_prod_mesh.ps1") -Quick
}

# Write audit summary so far (PS 5.1-safe: no nested Generic.List in hashtable literal)
$preEnded = Get-Date
$stepRows = @()
foreach ($s in $steps) {
    $stepRows += [pscustomobject]@{
        name      = [string]$s.name
        ok        = [bool]$s.ok
        exit_code = [int]$s.exit_code
        soft      = [bool]$s.soft
    }
}
$audit = [ordered]@{
    kind                = "pre48h_maxload_2h"
    honesty             = @(
        "NOT 48h soak claim",
        "NOT mainnet",
        "NOT Hybrid pin",
        "2h STRICT stress only - gate before optional 48h"
    )
    started_at          = $started.ToString("o")
    preflight_ended_at  = $preEnded.ToString("o")
    hours               = $Hours
    interval_sec        = $IntervalSec
    rebuild             = [bool]$doRebuild
    fail_count          = [int]$fail
    steps               = $stepRows
    log_file            = $LogFile
    report_file         = $ReportFile
}
try {
    ($audit | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $Root $AuditReport) -Encoding UTF8
    Write-Host ("Preflight audit written: " + $AuditReport) -ForegroundColor DarkGray
} catch {
    Write-Host ("WARN: could not write audit json: " + $_.Exception.Message) -ForegroundColor Yellow
}

if ($fail -gt 0) {
    Write-Host "ABORT: post-load failures ($fail). Soak not started." -ForegroundColor Red
    exit 1
}

if ($PreflightOnly) {
    Write-Host ""
    Write-Host "RESULT: PASS preflight-only (soak NOT started)" -ForegroundColor Green
    Write-Host "  Next: re-run without -PreflightOnly to start 2h STRICT" -ForegroundColor DarkGray
    exit 0
}

# ── 5) 2h STRICT soak ─────────────────────────────────────────────────────
Step "5) start 2h STRICT soak (full harness every cycle)"
& (Join-Path $ScriptDir "stop_soak_monitors.ps1") -Force | Out-Null

$gitTag = "unknown"
try {
    $desc = git describe --tags --abbrev=0 2>$null
    if ($desc) { $gitTag = $desc.Trim() }
} catch { }
$gitSha = (git rev-parse --short HEAD 2>$null)
if (-not $gitSha) { $gitSha = "unknown" }

$activeMeta = @{
    log_file = $LogFile
    report_file = $ReportFile
    hours = $Hours
    interval_sec = $IntervalSec
    strict = $true
    maxload_pre48h = $true
    started_at = (Get-Date -Format "o")
    git_tag = $gitTag
    git_sha = "$gitSha"
    note = "2h STRICT max-load pre-48h audit - NOT 48h evidence"
}
$activeMeta | ConvertTo-Json | Set-Content -Path (Join-Path $Root "logs/soak_active.json") -Encoding UTF8

python scripts/record_evidence_run.py `
    --name soak_2h_pre48h_maxload `
    --result IN_PROGRESS `
    --command ".\scripts\start_pre48h_maxload_2h.ps1" `
    --artifact $LogFile `
    --git-tag $gitTag `
    2>$null | Out-Null

$soakScript = Join-Path $ScriptDir "soak_monitor.ps1"
$soakArgs = @(
    "-Hours", $Hours,
    "-IntervalSec", $IntervalSec,
    "-ProdMesh",
    "-Strict",
    "-LogFile", $LogFile,
    "-ReportFile", $ReportFile
)

Write-Host "  STRICT 2h: mesh_warn=0, no ready-flap, full harness every ${IntervalSec}s" -ForegroundColor Yellow
Write-Host "  log=$LogFile" -ForegroundColor DarkGray
Write-Host "  report=$ReportFile" -ForegroundColor DarkGray

if ($Foreground) {
    & $soakScript @soakArgs
    exit $LASTEXITCODE
}

$proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", $soakScript,
    "-Hours", "$Hours",
    "-IntervalSec", "$IntervalSec",
    "-ProdMesh",
    "-Strict",
    "-LogFile", $LogFile,
    "-ReportFile", $ReportFile
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

Write-Host ""
Write-Host "RESULT: 2h STRICT max-load soak STARTED (pid=$($proc.Id))" -ForegroundColor Green
Write-Host "  Monitor: Get-Content $LogFile -Wait -Tail 40" -ForegroundColor DarkGray
Write-Host "  Status:  .\scripts\check_soak.ps1" -ForegroundColor DarkGray
Write-Host "  After:   read $ReportFile - claim PASS only if hard_fails=0 / passed=true" -ForegroundColor DarkGray
Write-Host "  Honesty: NOT 48h / NOT mainnet / NOT Hybrid" -ForegroundColor DarkGray
exit 0
