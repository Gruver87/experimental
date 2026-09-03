# Shared health_watch probes (parallel worker + main loop).
# Mesh align uses a parallel height snapshot — sequential port polling caused
# false mesh_warn on live libp2p soak (46× gap=2, 1× gap=4 with ready_fallback).

$Script:SoftHarnessChecks = @(
    "status_slow",
    "ready_flap",
    "peer_probe_ok",
    "p2p_state_consistent",
    "harness_timeout"
)

function Get-StatusProbeUri {
    param([int]$Port)
    return "http://127.0.0.1:$Port/status?probe=1"
}

function Invoke-Ready503Recovery {
    param(
        [int]$Port,
        [bool]$ProdMesh,
        $ReadyBody
    )
    $probeSec = if ($ProdMesh) { 18 } else { 10 }
    Start-Sleep -Seconds 4
    try {
        $stProbe = Invoke-RestMethod -Uri (Get-StatusProbeUri -Port $Port) -TimeoutSec $probeSec
        if ($null -ne $stProbe) {
            return @{
                Ok = $true
                Port = $Port
                Height = [int]$stProbe.height
                Head = $stProbe.head_hash
                Peers = [int]$stProbe.peers
                P2P = $stProbe.p2p_sync_status
                Aligned = $true
                HarnessHealthy = $false
                Failed = @("ready_flap")
                FullHarness = $false
                ReadyFlap = $true
                ReadyError = "ready_503_recovered"
            }
        }
    } catch { }
    if ($null -ne $ReadyBody) {
        $h503 = 0
        $peers503 = 0
        if ($null -ne $ReadyBody.height) { $h503 = [int]$ReadyBody.height }
        if ($null -ne $ReadyBody.peer_count) { $peers503 = [int]$ReadyBody.peer_count }
        $deepOk = $false
        if ($null -ne $ReadyBody.deep_ready) { $deepOk = [bool]$ReadyBody.deep_ready }
        if ($h503 -ge 0 -and ($deepOk -or $h503 -gt 0)) {
            try {
                $live = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 8
                if ($live -and $live.status -eq "alive") {
                    return @{
                        Ok = $true
                        Port = $Port
                        Height = $h503
                        Head = ""
                        Peers = $peers503
                        P2P = "ready_503_body"
                        Aligned = $true
                        HarnessHealthy = $false
                        Failed = @("ready_flap")
                        FullHarness = $false
                        ReadyFlap = $true
                        ReadyError = "ready_503_body"
                    }
                }
            } catch { }
        }
    }
    return $null
}

function Test-NodeHealth {
    param(
        [int]$Port,
        [bool]$FullHarness,
        [bool]$ProdMesh = $false,
        [switch]$Strict
    )
    $readySec = if ($ProdMesh) { 20 } else { 5 }
    $statusSec = if ($ProdMesh) { 12 } else { 5 }
    $harnessSec = if ($FullHarness) { if ($ProdMesh) { 45 } else { 20 } } else { if ($ProdMesh) { 25 } else { 10 } }
    $peerTimeout = if ($FullHarness) { 8 } else { if ($ProdMesh) { 6 } else { 3 } }

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
        $statusUri = Get-StatusProbeUri -Port $Port
        for ($sAttempt = 1; $sAttempt -le 3; $sAttempt++) {
            try {
                $stProbe = Invoke-RestMethod -Uri $statusUri -TimeoutSec $statusSec
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
        if (-not $Strict) {
            $recovered = Invoke-Ready503Recovery -Port $Port -ProdMesh:$ProdMesh -ReadyBody $readyBody
            if ($null -ne $recovered) {
                $recovered.FullHarness = $FullHarness
                return $recovered
            }
        }
        try {
            $live = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 8
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
    $statusUri = Get-StatusProbeUri -Port $Port
    for ($sAttempt = 1; $sAttempt -le 3; $sAttempt++) {
        try {
            $st = Invoke-RestMethod -Uri $statusUri -TimeoutSec $statusSec
            break
        } catch {
            $statusErr = $_.Exception.Message
            if ($sAttempt -lt 3) { Start-Sleep -Seconds 2 }
        }
    }
    if ($null -eq $st) {
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

    $harnessUri = if ($FullHarness) {
        "http://127.0.0.1:$Port/chain/consistency/harness?peer_timeout=$peerTimeout"
    } else {
        "http://127.0.0.1:$Port/chain/consistency/harness?quick=1&peer_timeout=$peerTimeout"
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

function Invoke-ParallelMeshResnapshot {
    param(
        [int[]]$Ports,
        [bool]$ProdMesh = $false
    )
    $timeoutSec = if ($ProdMesh) { 10 } else { 6 }
    $jobs = @()
    foreach ($p in $Ports) {
        $jobs += Start-Job -ScriptBlock {
            param($Port, $TimeoutSec)
            $ErrorActionPreference = "SilentlyContinue"
            try {
                $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status?probe=1" -TimeoutSec $TimeoutSec
                return @{
                    Port = [int]$Port
                    Height = [int]$st.height
                    Head = [string]$st.head_hash
                    Ok = $true
                }
            } catch { }
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec $TimeoutSec
                return @{
                    Port = [int]$Port
                    Height = $(if ($null -ne $r.height) { [int]$r.height } else { 0 })
                    Head = ""
                    Ok = $true
                }
            } catch { }
            return @{ Port = [int]$Port; Height = -1; Head = ""; Ok = $false }
        } -ArgumentList $p, $timeoutSec
    }
    Wait-Job $jobs | Out-Null
    $rows = @()
    foreach ($j in $jobs) {
        $row = Receive-Job $j
        Remove-Job $j -Force -ErrorAction SilentlyContinue
        if ($row) { $rows += $row }
    }
    return @($rows)
}

function Test-MeshCycleAligned {
    param(
        $Rows,
        [switch]$Strict,
        [int[]]$Ports,
        [bool]$ProdMesh = $false
    )
    $rowCount = @($Rows).Count
    if ($rowCount -lt 2) {
        return @{
            Ok = $false
            Partial = $true
            Detail = "insufficient cycle rows for mesh ($rowCount)"
            Delta = -1
        }
    }

    $heights = @()
    $heads = @()
    foreach ($row in $Rows) {
        $heights += [int]$row.Height
        $h = ([string]$row.Head).ToLowerInvariant()
        if ($h) { $heads += $h }
    }
    $maxH = ($heights | Measure-Object -Maximum).Maximum
    $minH = ($heights | Measure-Object -Minimum).Minimum
    $delta = [int]($maxH - $minH)
    $uniqueHeads = @($heads | Select-Object -Unique)

    if ($Strict) {
        $ok = ($delta -eq 0) -and ($uniqueHeads.Count -le 1)
        return @{ Ok = $ok; Delta = $delta; Resnapshot = $false }
    }

    # Prod mesh: ±2 blocks covers parallel poll + one tip-v2 mine tick (soak evidence).
    if ($delta -le 2) {
        return @{ Ok = $true; Delta = $delta; Transient = ($delta -gt 0); Resnapshot = $false }
    }
    if ($heads.Count -ge 2 -and $uniqueHeads.Count -le 1) {
        return @{ Ok = $true; Delta = $delta; HeadConsensus = $true; Resnapshot = $false }
    }

    # Mixed ready_fallback heights vs /status: parallel re-snapshot before WARN.
    $snap = Invoke-ParallelMeshResnapshot -Ports $Ports -ProdMesh:$ProdMesh
    if (@($snap).Count -ge 2) {
        $snapHeights = @($snap | Where-Object { $_.Ok -and [int]$_.Height -ge 0 } | ForEach-Object { [int]$_.Height })
        $snapHeads = @(
            $snap | Where-Object { $_.Ok -and ([string]$_.Head) } |
                ForEach-Object { ([string]$_.Head).ToLowerInvariant() } |
                Select-Object -Unique
        )
        if ($snapHeights.Count -ge 2) {
            $snapDelta = ($snapHeights | Measure-Object -Maximum).Maximum - ($snapHeights | Measure-Object -Minimum).Minimum
            if ($snapDelta -le 2) {
                return @{
                    Ok = $true
                    Delta = [int]$snapDelta
                    Resnapshot = $true
                    Transient = ($snapDelta -gt 0)
                }
            }
            $headRows = @($snap | Where-Object { $_.Ok -and ([string]$_.Head) })
            if ($snapHeights.Count -ge 2 -and $headRows.Count -ge 2) {
                $uh = @($headRows | ForEach-Object { ([string]$_.Head).ToLowerInvariant() } | Select-Object -Unique)
                if ($uh.Count -le 1) {
                    return @{ Ok = $true; Delta = [int]$snapDelta; Resnapshot = $true; HeadConsensus = $true }
                }
            }
            $delta = [int]$snapDelta
        }
    }

    return @{ Ok = $false; Delta = $delta; Resnapshot = $true }
}

function Invoke-ParallelNodeHealth {
    param(
        [int[]]$Ports,
        [bool]$FullHarness,
        [bool]$ProdMesh = $false,
        [switch]$Strict,
        [string]$ScriptDir
    )
    $worker = Join-Path $ScriptDir "health_watch_node.ps1"
    if (-not (Test-Path $worker)) {
        $seq = @()
        foreach ($p in $Ports) {
            $seq += Test-NodeHealth -Port $p -FullHarness:$FullHarness -ProdMesh:$ProdMesh -Strict:$Strict
        }
        return $seq
    }

    $jobs = @()
    foreach ($p in $Ports) {
        $jobs += Start-Job -FilePath $worker -ArgumentList @(
            [int]$p,
            [bool]$FullHarness,
            [bool]$ProdMesh,
            [bool]$Strict.IsPresent,
            [string]$ScriptDir
        )
    }
    Wait-Job $jobs | Out-Null
    $results = @()
    foreach ($j in $jobs) {
        $raw = Receive-Job $j
        Remove-Job $j -Force -ErrorAction SilentlyContinue
        if (-not $raw) { continue }
        try {
            $obj = $raw | ConvertFrom-Json
            if ($obj.Failed -is [string]) {
                $obj | Add-Member -NotePropertyName Failed -NotePropertyValue @($obj.Failed) -Force
            }
            $results += $obj
        } catch {
            $results += [PSCustomObject]@{ Ok = $false; Port = 0; Error = "worker_json_parse: $($_.Exception.Message)" }
        }
    }
    return @($results)
}
