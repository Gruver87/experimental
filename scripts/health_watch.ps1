# Poll prod/dev mesh health and optionally POST to a webhook on failure.
param(
    [int[]]$Ports = @(18180, 18181, 18182),
    [switch]$ProdMesh,
    [int]$IntervalSec = 300,
    [int]$DurationMin = 0,
    [int]$FullHarnessEvery = 6,
    [switch]$AlwaysFullHarness,
    [string]$LogFile = "logs/health_watch.log",
    [string]$WebhookUrl = $env:HEALTH_WEBHOOK_URL,
    [switch]$Strict,
    # Long-Range lab: hard-FAIL if max tip height does not advance for this many seconds (0=off).
    [int]$TipStagnantFailAfterSec = 0
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root
. (Join-Path $ScriptDir "health_watch_core.ps1")

if ($ProdMesh) {
    $Ports = @(18180, 18181, 18182)
}

# Multi-node lab meshes (Long-Range :29080–29082) must use prod-grade HTTP
# timeouts. lr48pass1: 13× ready+status dual-timeout FAIL under 5s lab defaults
# — those fail_lines kill STRICT (fail=0). Solo lab keeps short timeouts.
$HeavyProbe = [bool]($ProdMesh -or ($Ports.Count -ge 2))

if ($DurationMin -gt 0 -and -not $PSBoundParameters.ContainsKey("IntervalSec")) {
    $IntervalSec = [Math]::Max(10, [Math]::Min(60, [int](($DurationMin * 60) / 3)))
}

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}
Set-Content -Path $LogFile -Value "" -Encoding UTF8

function Write-Log([string]$Msg, [string]$Color = "Gray") {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    for ($i = 0; $i -lt 5; $i++) {
        try {
            Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction Stop
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    Write-Host $line -ForegroundColor $Color
}

function Send-Webhook([string]$Text) {
    if (-not $WebhookUrl) { return }
    try {
        $body = @{ text = $Text } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $WebhookUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
    } catch {
        Write-Log "webhook failed: $($_.Exception.Message)" "Yellow"
    }
}

$end = if ($DurationMin -gt 0) { (Get-Date).AddMinutes($DurationMin) } else { $null }
$cycle = 0
$totalHardFails = 0
$totalReadyOnlyFails = 0
$tipLastMax = -1
$tipLastAdvanceAt = Get-Date
$fullEveryLabel = if ($AlwaysFullHarness) { "always" } else { [string]$FullHarnessEvery }
$tipStagLabel = if ($TipStagnantFailAfterSec -gt 0) { " tip_stagnant_fail_after=${TipStagnantFailAfterSec}s" } else { "" }
$heavyLabel = if ($HeavyProbe -and -not $ProdMesh) { " heavy_probe=1" } else { "" }
Write-Log "health_watch start ports=$($Ports -join ',') interval=${IntervalSec}s full_every=$fullEveryLabel log=$LogFile parallel=1$tipStagLabel$heavyLabel" "Cyan"

while ($true) {
    $cycle++
    $fullHarness = $AlwaysFullHarness -or ($FullHarnessEvery -le 1) -or ($cycle % $FullHarnessEvery -eq 0)
    $modeLabel = if ($fullHarness) { "full" } else { "quick" }
    $failures = @()
    $cycleRows = [System.Collections.Generic.List[object]]::new()

    $nodeResults = Invoke-ParallelNodeHealth -Ports $Ports -FullHarness:$fullHarness -ProdMesh:$HeavyProbe -Strict:$Strict -ScriptDir $ScriptDir
    foreach ($r in $nodeResults) {
        if (-not $r.Ok) {
            $err = if ($r.Error) { [string]$r.Error } else { "unreachable" }
            $port = if ($r.Port) { [int]$r.Port } else { 0 }
            $failures += "port $port unreachable: $err"
            if ($err -match '^ready:') {
                $totalReadyOnlyFails++
            } else {
                $totalHardFails++
            }
            Write-Log "FAIL port $port $err" "Red"
            continue
        }
        # Soft ready_flap / live_fallback without a real tip must NOT enter mesh
        # rows — Height=0 (or empty head after status HOL) poisons Strict delta
        # into a false multi-thousand-block FAIL after soft-flap conversion.
        $headStr = [string]$r.Head
        $p2pStr = [string]$r.P2P
        $readyFlap = $false
        try { $readyFlap = [bool]$r.ReadyFlap } catch { $readyFlap = $false }
        $unreliableTip = (
            ($p2pStr -eq "live_fallback") -or
            ($readyFlap -and (-not $headStr)) -or
            (($p2pStr -eq "ready_503_body") -and (-not $headStr))
        )
        if (-not $unreliableTip) {
            [void]$cycleRows.Add([PSCustomObject]@{
                Port = [int]$r.Port
                Height = [int]$r.Height
                Head = $headStr
                Peers = [int]$r.Peers
            })
        }
        $failedList = @($r.Failed)
        $failedTxt = if ($failedList.Count -gt 0) { $failedList -join "," } else { "" }
        $line = "OK port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt"
        if ($unreliableTip) { $line = "$line mesh_exclude=1" }
        # Solo is expected for single-node lab soaks (Long-Range :29080); warn only on multi-node mesh.
        $soloExpected = (-not $ProdMesh) -and ($Ports.Count -eq 1) -and ($p2pStr -eq "solo")
        # tip_skew (<=2 height) is tip-v2 mine-window noise — not WARN.
        # tip_lagging / inconsistent / under_mesh / solo / stale still WARN.
        $p2pWarn = (
            ($p2pStr -in @(
                "solo",
                "under_mesh",
                "under_mesh_lagging",
                "stale",
                "inconsistent",
                "tip_lagging"
            )) -and (-not $soloExpected)
        )
        # Wave G: demote is soft-WARN only (never hard_fail / soak score).
        $demoteWarn = $false
        try { $demoteWarn = [bool]$r.MempoolDemoted } catch { $demoteWarn = $false }
        $softFailed = @($failedList | Where-Object { $_ -in $Script:SoftHarnessChecks })
        $hardFailed = @($failedList | Where-Object { $_ -notin $Script:SoftHarnessChecks })
        # Soft-only flakes (peer_probe_ok / harness_timeout / ready_flap / …) must
        # never become Strict hard-FAIL even when tip_state_aligned is sticky-false
        # under GIL load — mempool48pass1 / libp2p STRICT contract.
        if ($softFailed.Count -gt 0 -and $hardFailed.Count -eq 0) {
            $harnessBad = $false
        } else {
            $harnessBad = ($r.Aligned -eq $false) -or ($hardFailed.Count -gt 0) -or (
                ($r.HarnessHealthy -eq $false) -and ($softFailed.Count -eq 0)
            )
        }
        if ($harnessBad) {
            $failures += $line
            if ($Strict) {
                $totalHardFails++
                Write-Log "FAIL harness port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt" "Red"
            } else {
                Write-Log "WARN $line" "Yellow"
            }
        } elseif ($p2pWarn -or $demoteWarn) {
            if ($demoteWarn) { $line = "$line mempool_demoted=1" }
            Write-Log "WARN $line" "Yellow"
        } elseif ($softFailed.Count -gt 0) {
            # Soft-only flakes still count as OK lines for default soak scoring (hard_fail gate unchanged).
            if ($Strict) {
                Write-Log "WARN $line" "Yellow"
            } else {
                Write-Log $line "Green"
            }
        } else {
            Write-Log $line "Green"
        }
    }

    if ($Ports.Count -gt 1) {
        $meshRows = @($cycleRows)
        # Soft mesh_exclude can drop below 2 tip rows under AlwaysFullHarness HOL.
        # Re-snapshot all ports before Strict Partial FAIL (false "insufficient rows").
        if ($meshRows.Count -lt 2) {
            $snap = Invoke-ParallelMeshResnapshot -Ports $Ports -ProdMesh:$HeavyProbe
            $meshRows = @(
                $snap |
                    Where-Object { $_.Ok -and [int]$_.Height -ge 0 -and ([string]$_.Head) } |
                    ForEach-Object {
                        [PSCustomObject]@{
                            Port = [int]$_.Port
                            Height = [int]$_.Height
                            Head = [string]$_.Head
                            Peers = 0
                        }
                    }
            )
            if ($meshRows.Count -lt 2) {
                Write-Log "WARN mesh tip rows thin after exclude+resnapshot count=$($meshRows.Count)" "Yellow"
            }
        }
        $mesh = Test-MeshCycleAligned -Rows $meshRows -Strict:$Strict -Ports $Ports -ProdMesh:$HeavyProbe
        if ($mesh.Partial) {
            # Insufficient tip rows after HOL exclude+resnapshot is soft (lr48pass1
            # ×13 mesh partial). Strict FAIL only on real height skew below.
            $failures += $mesh.Detail
            Write-Log "WARN mesh probe: $($mesh.Detail)" "Yellow"
        } elseif ($mesh.Ok) {
            $detail = ($meshRows | ForEach-Object { "$($_.Port):h$($_.Height)/p$($_.Peers)" }) -join " "
            $suffix = ""
            if ($mesh.Resnapshot) { $suffix = " resnapshot=1" }
            if ($mesh.Transient) { $suffix += " transient_delta=$($mesh.Delta)" }
            if ($mesh.ConfirmedClear) { $suffix += " strict_confirm=1" }
            if ($meshRows.Count -lt $Ports.Count) {
                Write-Log "WARN mesh partial aligned $detail$suffix" "Yellow"
            } else {
                Write-Log "OK mesh aligned $detail$suffix" "DarkGray"
            }
        } else {
            $detail = ($meshRows | ForEach-Object { "h$($_.Port)=$($_.Height)" }) -join " "
            $failures += "mesh misaligned: $detail delta=$($mesh.Delta)"
            if ($Strict) {
                $totalHardFails++
                Write-Log "FAIL mesh misaligned $detail delta=$($mesh.Delta)" "Red"
            } else {
                Write-Log "WARN mesh misaligned $detail delta=$($mesh.Delta)" "Yellow"
            }
        }
    }

    # Long-Range / lab mesh: tip-dead + health-green is a false PASS. Hard-FAIL
    # when max observed height does not advance for TipStagnantFailAfterSec.
    if ($TipStagnantFailAfterSec -gt 0 -and $cycleRows.Count -gt 0) {
        $maxH = ($cycleRows | ForEach-Object { [int]$_.Height } | Measure-Object -Maximum).Maximum
        if ($null -eq $maxH) { $maxH = -1 }
        if ([int]$maxH -gt [int]$tipLastMax) {
            $tipLastMax = [int]$maxH
            $tipLastAdvanceAt = Get-Date
        } else {
            $staleSec = [int]((Get-Date) - $tipLastAdvanceAt).TotalSeconds
            if ($staleSec -ge $TipStagnantFailAfterSec) {
                $msg = "tip stagnant max_h=$tipLastMax for ${staleSec}s (limit=${TipStagnantFailAfterSec}s)"
                $failures += $msg
                $totalHardFails++
                Write-Log "FAIL $msg" "Red"
            } elseif (($cycle % 6) -eq 0) {
                Write-Log "WARN tip stagnant max_h=$tipLastMax age=${staleSec}s" "Yellow"
            }
        }
    }

    if ($failures.Count -gt 0) {
        Send-Webhook ("Absolute mesh alert (cycle $cycle):`n" + ($failures -join "`n"))
    }

    if ($end -and (Get-Date) -ge $end) {
        Write-Log "health_watch done (duration ${DurationMin}m cycles=$cycle hard_fails=$totalHardFails ready_only=$totalReadyOnlyFails)" "Cyan"
        break
    }
    $sleepFor = $IntervalSec
    if ($end) {
        $remaining = [int](($end - (Get-Date)).TotalSeconds)
        if ($remaining -le 0) {
            Write-Log "health_watch done (duration ${DurationMin}m cycles=$cycle hard_fails=$totalHardFails ready_only=$totalReadyOnlyFails)" "Cyan"
            break
        }
        if ($remaining -lt $sleepFor) { $sleepFor = $remaining }
    }
    Start-Sleep -Seconds $sleepFor
}

if ($totalHardFails -gt 0) {
    Write-Log "health_watch exit=1 hard_fails=$totalHardFails ready_only=$totalReadyOnlyFails" "Red"
    exit 1
}
if ($totalReadyOnlyFails -gt 0) {
    Write-Log "health_watch exit=0 ready_only_fails=$totalReadyOnlyFails (48h tolerated when mesh aligned)" "Yellow"
}
exit 0
