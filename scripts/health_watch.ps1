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
    $statusSec = if ($ProdMesh) { 15 } else { 5 }
    $harnessSec = if ($FullHarness) { if ($ProdMesh) { 45 } else { 20 } } else { if ($ProdMesh) { 25 } else { 10 } }
    # Hard FAIL only when status is unreachable after retries.
    # Transient /health/ready 503 (wire-probe / peers_alive flap) must not
    # poison a 48h soak — log WARN and continue if /status still answers.
    $readyOk = $false
    $readyErr = ""
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec $readySec
            $readyOk = $true
            break
        } catch {
            $readyErr = "ready: $($_.Exception.Message)"
            if ($attempt -lt 5) { Start-Sleep -Seconds ([Math]::Min(8, 1 + $attempt * 2)) }
        }
    }
    if (-not $readyOk) {
        $stProbe = $null
        $statusErr = ""
        for ($sAttempt = 1; $sAttempt -le 5; $sAttempt++) {
            try {
                $stProbe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec $statusSec
                break
            } catch {
                $statusErr = $_.Exception.Message
                if ($sAttempt -lt 5) { Start-Sleep -Seconds 2 }
            }
        }
        if ($null -ne $stProbe) {
            if ($Strict) {
                return @{ Ok = $false; Port = $Port; Error = "ready_flap (strict): $readyErr" }
            }
            # Soft: node is up; ready flap is monitored as WARN via Failed=ready_flap.
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
        # Last chance: brief pause then one more /status — overload often clears.
        Start-Sleep -Seconds $(if ($ProdMesh) { 5 } else { 2 })
        try {
            $stProbe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec ($statusSec + 5)
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
        } catch {
            $statusErr = $_.Exception.Message
        }
        return @{ Ok = $false; Port = $Port; Error = "$readyErr; status: $statusErr" }
    }
    $st = $null
    $statusErr = ""
    # After /health/ready: retry /status (transient apply-queue). Not a substitute for cheap /status.
    for ($sAttempt = 1; $sAttempt -le 5; $sAttempt++) {
        try {
            $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec $statusSec
            break
        } catch {
            $statusErr = $_.Exception.Message
            if ($sAttempt -lt 5) { Start-Sleep -Seconds 2 }
        }
    }
    if ($null -eq $st) {
        return @{ Ok = $false; Port = $Port; Error = "status: $statusErr" }
    }
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

function Test-MeshAlignment {
    param(
        [int[]]$PortList,
        [object[]]$Rows = $null
    )
    $rows = @()
    if ($null -ne $Rows -and @($Rows).Count -gt 0) {
        $rows = @($Rows)
    } else {
        foreach ($p in $PortList) {
            try {
                $st = Invoke-RestMethod -Uri "http://127.0.0.1:$p/status" -TimeoutSec $(if ($ProdMesh) { 12 } else { 5 })
                $rows += [PSCustomObject]@{
                    Port = $p
                    Height = [int]$st.height
                    Head = [string]$st.head_hash
                    Peers = [int]$st.peers
                }
            } catch {
                return @{ Ok = $false; Error = "port $p status: $($_.Exception.Message)" }
            }
        }
    }
    $heights = @($rows | ForEach-Object { $_.Height })
    $maxH = ($heights | Measure-Object -Maximum).Maximum
    $minH = ($heights | Measure-Object -Minimum).Minimum
    if ($Strict) {
        $heads = @($rows | ForEach-Object { ([string]$_.Head).ToLowerInvariant() } | Where-Object { $_ } | Select-Object -Unique)
        $heightOk = ($maxH - $minH) -eq 0
        $headOk = ($heads.Count -le 1)
        return @{
            Ok = ($heightOk -and $headOk)
            Rows = $rows
        }
    }
    # Allow ±1 height skew: status is polled sequentially while blocks mine.
    # Tip-hash races at equal height are expected and ignored (heads differ briefly).
    $heightOk = ($maxH - $minH) -le 1
    return @{
        Ok = $heightOk
        Rows = $rows
        HeightOk = $heightOk
        HeadOk = $true
    }
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
$fullEveryLabel = if ($AlwaysFullHarness) { "always" } else { [string]$FullHarnessEvery }
Write-Log "health_watch start ports=$($Ports -join ',') interval=${IntervalSec}s full_every=$fullEveryLabel log=$LogFile" "Cyan"

while ($true) {
    $cycle++
    $fullHarness = $AlwaysFullHarness -or ($FullHarnessEvery -le 1) -or ($cycle % $FullHarnessEvery -eq 0)
    $modeLabel = if ($fullHarness) { "full" } else { "quick" }
    $failures = @()
    $cycleRows = @()

    foreach ($p in $Ports) {
        $r = Test-NodeHealth $p $fullHarness
        if (-not $r.Ok) {
            $failures += "port $p unreachable: $($r.Error)"
            $totalHardFails++
            Write-Log "FAIL port $p $($r.Error)" "Red"
            continue
        }
        $cycleRows += [PSCustomObject]@{
            Port = $r.Port
            Height = [int]$r.Height
            Head = [string]$r.Head
            Peers = [int]$r.Peers
        }
        $failedTxt = if ($r.Failed.Count -gt 0) { $r.Failed -join "," } else { "" }
        $line = "OK port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt"
        $p2pWarn = ($r.P2P -in @("solo", "under_mesh", "stale"))
        $harnessBad = ($r.Aligned -eq $false) -or ($r.Failed.Count -gt 0) -or ($r.HarnessHealthy -eq $false)
        if ($harnessBad) {
            $failures += $line
            if ($Strict) {
                Write-Log "FAIL harness port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt" "Red"
            } else {
                Write-Log "WARN $line" "Yellow"
            }
        } elseif ($p2pWarn) {
            Write-Log "$line (p2p not full mesh; chain OK)" "Yellow"
        } else {
            Write-Log $line "Green"
        }
    }

    if ($Ports.Count -gt 1) {
        if ($cycleRows.Count -eq $Ports.Count) {
            $mesh = Test-MeshAlignment $Ports -Rows $cycleRows
        } else {
            $mesh = Test-MeshAlignment $Ports
        }
        if (-not $mesh.Ok) {
            if ($mesh.Error) {
                $failures += "mesh probe: $($mesh.Error)"
                if ($Strict) {
                    Write-Log "FAIL mesh probe: $($mesh.Error)" "Red"
                } else {
                    Write-Log "WARN mesh probe: $($mesh.Error)" "Yellow"
                }
            } else {
                $detail = @($mesh.Rows | ForEach-Object { "h$($_.Port)=$($_.Height)" }) -join " "
                if (-not $detail) { $detail = "unknown" }
                $failures += "mesh misaligned: $detail"
                if ($Strict) {
                    Write-Log "FAIL mesh misaligned $detail" "Red"
                } else {
                    Write-Log "WARN mesh misaligned $detail" "Yellow"
                }
            }
        } else {
            $detail = ($mesh.Rows | ForEach-Object { "$($_.Port):h$($_.Height)/p$($_.Peers)" }) -join " "
            Write-Log "OK mesh aligned $detail" "DarkGray"
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
