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
    [switch]$Strict
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root
. (Join-Path $ScriptDir "health_watch_core.ps1")

if ($ProdMesh) {
    $Ports = @(18180, 18181, 18182)
}

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
$fullEveryLabel = if ($AlwaysFullHarness) { "always" } else { [string]$FullHarnessEvery }
Write-Log "health_watch start ports=$($Ports -join ',') interval=${IntervalSec}s full_every=$fullEveryLabel log=$LogFile parallel=1" "Cyan"

while ($true) {
    $cycle++
    $fullHarness = $AlwaysFullHarness -or ($FullHarnessEvery -le 1) -or ($cycle % $FullHarnessEvery -eq 0)
    $modeLabel = if ($fullHarness) { "full" } else { "quick" }
    $failures = @()
    $cycleRows = [System.Collections.Generic.List[object]]::new()

    $nodeResults = Invoke-ParallelNodeHealth -Ports $Ports -FullHarness:$fullHarness -ProdMesh:$ProdMesh -Strict:$Strict -ScriptDir $ScriptDir
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
        [void]$cycleRows.Add([PSCustomObject]@{
            Port = [int]$r.Port
            Height = [int]$r.Height
            Head = [string]$r.Head
            Peers = [int]$r.Peers
        })
        $failedList = @($r.Failed)
        $failedTxt = if ($failedList.Count -gt 0) { $failedList -join "," } else { "" }
        $line = "OK port $($r.Port) [$modeLabel] height=$($r.Height) peers=$($r.Peers) p2p=$($r.P2P) aligned=$($r.Aligned) failed=$failedTxt"
        # Solo is expected for single-node lab soaks (Long-Range :29080); warn only on multi-node mesh.
        $soloExpected = (-not $ProdMesh) -and ($Ports.Count -eq 1) -and ([string]$r.P2P -eq "solo")
        $p2pWarn = (([string]$r.P2P -in @("solo", "under_mesh", "stale")) -and (-not $soloExpected))
        $softFailed = @($failedList | Where-Object { $_ -in $Script:SoftHarnessChecks })
        $hardFailed = @($failedList | Where-Object { $_ -notin $Script:SoftHarnessChecks })
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
        } elseif ($p2pWarn) {
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
        $mesh = Test-MeshCycleAligned -Rows $cycleRows -Strict:$Strict -Ports $Ports -ProdMesh:$ProdMesh
        if ($mesh.Partial) {
            $failures += $mesh.Detail
            if ($Strict) {
                Write-Log "FAIL mesh probe: $($mesh.Detail)" "Red"
            } else {
                Write-Log "WARN mesh probe: $($mesh.Detail)" "Yellow"
            }
        } elseif ($mesh.Ok) {
            $detail = ($cycleRows | ForEach-Object { "$($_.Port):h$($_.Height)/p$($_.Peers)" }) -join " "
            $suffix = ""
            if ($mesh.Resnapshot) { $suffix = " resnapshot=1" }
            if ($mesh.Transient) { $suffix += " transient_delta=$($mesh.Delta)" }
            if ($cycleRows.Count -lt $Ports.Count) {
                Write-Log "WARN mesh partial aligned $detail$suffix" "Yellow"
            } else {
                Write-Log "OK mesh aligned $detail$suffix" "DarkGray"
            }
        } else {
            $detail = ($cycleRows | ForEach-Object { "h$($_.Port)=$($_.Height)" }) -join " "
            $failures += "mesh misaligned: $detail delta=$($mesh.Delta)"
            if ($Strict) {
                Write-Log "FAIL mesh misaligned $detail delta=$($mesh.Delta)" "Red"
            } else {
                Write-Log "WARN mesh misaligned $detail delta=$($mesh.Delta)" "Yellow"
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
