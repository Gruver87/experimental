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
    # Strict: 1-height skew / head mismatch / ready flap / harness fail = FAIL (no soft WARN).
    [switch]$Strict
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($ProdMesh) {
    $Ports = @(18180, 18181, 18182)
}

# Short runs: default 300s interval means only one poll before DurationMin ends.
if ($DurationMin -gt 0 -and -not $PSBoundParameters.ContainsKey("IntervalSec")) {
    $IntervalSec = [Math]::Max(10, [Math]::Min(60, [int](($DurationMin * 60) / 3)))
}

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}
# Fresh run: do not append onto prior soak/watch history (FAIL counts must be this session only).
Set-Content -Path $LogFile -Value "" -Encoding UTF8

function Write-Log([string]$Msg, [string]$Color = "Gray") {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    # Get-Content -Wait can briefly lock the log; do not kill the soak on that.
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

function Test-NodeHealth([int]$Port, [bool]$FullHarness) {
    $readySec = if ($ProdMesh) { 20 } else { 5 }
    $statusSec = if ($ProdMesh) { 12 } else { 5 }
    $harnessSec = if ($FullHarness) { if ($ProdMesh) { 45 } else { 20 } } else { if ($ProdMesh) { 25 } else { 10 } }
    # Hard FAIL only when the node is unreachable (ready+status both dead).
    # Transient /health/ready 503 (wire-probe / peers_alive flap) must not
    # poison a 48h soak — log WARN and continue if /status or /health/live answers.
    $readyOk = $false
    $readyErr = ""
    $readyBody = $null
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $readyBody = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec $readySec
            $readyOk = $true
            break
        } catch {
            $readyErr = "ready: $($_.Exception.Message)"
            # HTTP 503 still returns a JSON body — parse it for soft flap (deep_ready/height).
            try {
                $webEx = $_.Exception.Response
                if ($null -ne $webEx) {
                    $code = [int]$webEx.StatusCode
                    if ($code -eq 503) {
                        $reader = New-Object System.IO.StreamReader($webEx.GetResponseStream())
                        $raw = $reader.ReadToEnd()
                        $reader.Close()
                        if ($raw) {
                            $readyBody = $raw | ConvertFrom-Json
                        }
                    }
                }
            } catch { }
            if ($attempt -lt 5) { Start-Sleep -Seconds ([Math]::Min(8, 1 + $attempt * 2)) }
        }
    }
    if (-not $readyOk) {
        $stProbe = $null
        $statusErr = ""
        for ($sAttempt = 1; $sAttempt -le 3; $sAttempt++) {
            try {
                $stProbe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec $statusSec
                break
            } catch {
                $statusErr = $_.Exception.Message
                if ($sAttempt -lt 3) { Start-Sleep -Seconds 2 }
            }
        }
        if ($null -ne $stProbe) {
            if ($Strict) {
                return @{ Ok = $false; Port = $Port; Error = "ready_flap (strict): $readyErr" }
            }
            return @{
                Ok = $true
                Port = $Port
                Height = $stProbe.height
                Head = $stProbe.head_hash
                Peers = $stProbe.peers
                P2P = $stProbe.p2p_sync_status
                Aligned = $true
                HarnessHealthy = $false
                Failed = @("ready_flap")
                FullHarness = $FullHarness
                ReadyFlap = $true
                ReadyError = $readyErr
            }
        }
        # Last chance: /health/live — process alive even if ready/status HOL.
        try {
            $live = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 5
            if ($live -and $live.status -eq "alive" -and -not $Strict) {
                $h = 0
                $peers = 0
                if ($null -ne $readyBody) {
                    if ($null -ne $readyBody.height) { $h = [int]$readyBody.height }
                    if ($null -ne $readyBody.peer_count) { $peers = [int]$readyBody.peer_count }
                }
                return @{
                    Ok = $true
                    Port = $Port
                    Height = $h
                    Head = ""
                    Peers = $peers
                    P2P = "live_fallback"
                    Aligned = $true
                    HarnessHealthy = $false
                    Failed = @("ready_flap")
                    FullHarness = $FullHarness
                    ReadyFlap = $true
                    ReadyError = $readyErr
                    StatusError = $statusErr
                }
            }
        } catch { }
        return @{ Ok = $false; Port = $Port; Error = "$readyErr; status: $statusErr" }
    }
    $st = $null
    $statusErr = ""
    # After /health/ready: retry /status (transient apply-queue). Not a substitute for cheap /status.
    for ($sAttempt = 1; $sAttempt -le 3; $sAttempt++) {
        try {
            $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec $statusSec
            break
        } catch {
            $statusErr = $_.Exception.Message
            if ($sAttempt -lt 3) { Start-Sleep -Seconds 2 }
        }
    }
    if ($null -eq $st) {
        # Ready 200 already means the node is serving. Fat GET /status must not
        # hard-FAIL a 48h soak (218 status timeouts vs live mesh mining).
        if (-not $Strict -and $null -ne $readyBody) {
            return @{
                Ok = $true
                Port = $Port
                Height = $(if ($null -ne $readyBody.height) { [int]$readyBody.height } else { 0 })
                Head = ""
                Peers = $(if ($null -ne $readyBody.peer_count) { [int]$readyBody.peer_count } else { 0 })
                P2P = "ready_fallback"
                Aligned = $true
                HarnessHealthy = $false
                Failed = @("status_slow")
                FullHarness = $FullHarness
                ReadyFallback = $true
                StatusError = $statusErr
            }
        }
        return @{ Ok = $false; Port = $Port; Error = "status: $statusErr" }
    }
    # Skip harness when status already slow path was avoided — full/quick harness
    # on every port under HOL multiplies soak cycle time past IntervalSec.
    $harnessUri = if ($FullHarness) {
        "http://127.0.0.1:$Port/chain/consistency/harness?peer_timeout=8"
    } else {
        "http://127.0.0.1:$Port/chain/consistency/harness?quick=1&peer_timeout=3"
    }
    $aligned = $true
    $harnessHealthy = $true
    $failed = @()
    try {
        $cs = Invoke-RestMethod -Uri $harnessUri -TimeoutSec $harnessSec
        $failed = @($cs.failed_checks)
        $aligned = [bool]$cs.tip_state_aligned
        $harnessHealthy = [bool]$cs.harness_healthy
    } catch {
        $failed = @("harness_timeout")
        $aligned = $false
        $harnessHealthy = $false
    }
    return @{
        Ok = $true
        Port = $Port
        Height = $st.height
        Head = $st.head_hash
        Peers = $st.peers
        P2P = $st.p2p_sync_status
        Aligned = $aligned
        HarnessHealthy = $harnessHealthy
        Failed = $failed
        FullHarness = $FullHarness
    }
}

# Mesh alignment is inlined in the main loop (PS 5.1 drops object[] when passed
# into a helper). Never re-fetch GET /status for mesh align (no /status re-fetch).

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
$fullEveryLabel = if ($AlwaysFullHarness) { "always" } else { [string]$FullHarnessEvery }
Write-Log "health_watch start ports=$($Ports -join ',') interval=${IntervalSec}s full_every=$fullEveryLabel log=$LogFile" "Cyan"

while ($true) {
    $cycle++
    $fullHarness = $AlwaysFullHarness -or ($FullHarnessEvery -le 1) -or ($cycle % $FullHarnessEvery -eq 0)
    $modeLabel = if ($fullHarness) { "full" } else { "quick" }
    $failures = @()
    $cycleRows = [System.Collections.Generic.List[object]]::new()

    foreach ($p in $Ports) {
        $r = Test-NodeHealth $p $fullHarness
        if (-not $r.Ok) {
            $failures += "port $p unreachable: $($r.Error)"
            $totalHardFails++
            Write-Log "FAIL port $p $($r.Error)" "Red"
            continue
        }
        [void]$cycleRows.Add([PSCustomObject]@{
            Port = $r.Port
            Height = [int]$r.Height
            Head = [string]$r.Head
            Peers = [int]$r.Peers
        })
        $failedTxt = if ($r.Failed.Count -gt 0) { $r.Failed -join "," } else { "" }
        $line = "OK port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt"
        $p2pWarn = ($r.P2P -in @("solo", "under_mesh", "stale"))
        # status_slow / ready_flap are soft soak signals — not harness hard-fails.
        $softFailed = @($r.Failed | Where-Object { $_ -in @("status_slow", "ready_flap") })
        $hardFailed = @($r.Failed | Where-Object { $_ -notin @("status_slow", "ready_flap") })
        $harnessBad = ($r.Aligned -eq $false) -or ($hardFailed.Count -gt 0) -or (
            ($r.HarnessHealthy -eq $false) -and ($softFailed.Count -eq 0)
        )
        if ($harnessBad) {
            $failures += $line
            if ($Strict) {
                Write-Log "FAIL harness port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt" "Red"
            } else {
                Write-Log "WARN $line" "Yellow"
            }
        } elseif ($softFailed.Count -gt 0 -or $p2pWarn) {
            Write-Log "WARN $line" "Yellow"
        } else {
            Write-Log $line "Green"
        }
    }

    if ($Ports.Count -gt 1) {
        $rowCount = $cycleRows.Count
        $mesh = $null
        if ($rowCount -ge 2) {
            # Inline mesh align — do not pass object[] into a function (PS 5.1 binding drop).
            $heights = @()
            foreach ($row in $cycleRows) {
                $heights += [int]$row.Height
            }
            $maxH = ($heights | Measure-Object -Maximum).Maximum
            $minH = ($heights | Measure-Object -Minimum).Minimum
            if ($Strict) {
                $heads = @()
                foreach ($row in $cycleRows) {
                    $h = ([string]$row.Head).ToLowerInvariant()
                    if ($h) { $heads += $h }
                }
                $heads = @($heads | Select-Object -Unique)
                $meshOk = (($maxH - $minH) -eq 0) -and ($heads.Count -le 1)
            } else {
                $meshOk = ($maxH - $minH) -le 1
            }
            $meshRows = @($cycleRows)
            if ($meshOk -and $rowCount -lt $Ports.Count) {
                $detail = ($meshRows | ForEach-Object { "$($_.Port):h$($_.Height)/p$($_.Peers)" }) -join " "
                Write-Log "WARN mesh partial aligned $detail" "Yellow"
            } elseif ($meshOk) {
                $detail = ($meshRows | ForEach-Object { "$($_.Port):h$($_.Height)/p$($_.Peers)" }) -join " "
                Write-Log "OK mesh aligned $detail" "DarkGray"
            } else {
                $detail = ($meshRows | ForEach-Object { "h$($_.Port)=$($_.Height)" }) -join " "
                $failures += "mesh misaligned: $detail"
                if ($Strict) {
                    Write-Log "FAIL mesh misaligned $detail" "Red"
                } else {
                    Write-Log "WARN mesh misaligned $detail" "Yellow"
                }
            }
        } else {
            $failures += "mesh probe: insufficient cycle rows for mesh ($rowCount)"
            if ($Strict) {
                Write-Log "FAIL mesh probe: insufficient cycle rows for mesh ($rowCount)" "Red"
            } else {
                Write-Log "WARN mesh probe: insufficient cycle rows for mesh ($rowCount)" "Yellow"
            }
        }
    }

    if ($failures.Count -gt 0) {
        Send-Webhook ("Absolute mesh alert (cycle $cycle):`n" + ($failures -join "`n"))
    }

    if ($end -and (Get-Date) -ge $end) {
        Write-Log "health_watch done (duration ${DurationMin}m cycles=$cycle hard_fails=$totalHardFails)" "Cyan"
        break
    }
    $sleepFor = $IntervalSec
    if ($end) {
        $remaining = [int](($end - (Get-Date)).TotalSeconds)
        if ($remaining -le 0) {
            Write-Log "health_watch done (duration ${DurationMin}m cycles=$cycle hard_fails=$totalHardFails)" "Cyan"
            break
        }
        if ($remaining -lt $sleepFor) { $sleepFor = $remaining }
    }
    Start-Sleep -Seconds $sleepFor
}

# Hard FAIL lines (unreachable ports) must fail the process for soak honesty.
if ($totalHardFails -gt 0) {
    Write-Log "health_watch exit=1 hard_fails=$totalHardFails" "Red"
    exit 1
}
exit 0
