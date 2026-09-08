# ADR 0017 — Long-Range lab chaos pulse (intensify 2h only).
# Forces follower reconnects + watches miner peer/ban honesty while soak runs.
# Appends to the soak log. Not a 48h claim. Not prod mesh.
#
#   .\scripts\long_range_lab_chaos_pulse.ps1 -Hours 2 -LogFile logs/soak_2h_long_range_lab.intensify.log

param(
    [int]$Hours = 2,
    [int]$CheckSec = 15,
    [int]$BounceEverySec = 480,
    [int]$BanPeersFailAfterCycles = 4,
    [int[]]$Ports = @(29080, 29081, 29082),
    [string]$LogFile = "logs/soak_2h_long_range_lab.intensify.log",
    [string]$ComposeProject = "abs-lr-lab",
    [string]$ComposeFile = "docker-compose.long_range.lab.yml"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

foreach ($p in $Ports) {
    if ($p -in @(18180, 18181, 18182)) {
        throw "REFUSE: chaos pulse must not touch prod mesh ports"
    }
}

function Write-ChaosLog([string]$Msg, [string]$Color = "DarkGray") {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line -ForegroundColor $Color
}

function Get-LabStatus([int]$Port) {
    $j = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec 8
    $bans = 0
    if ($j.p2p_summary -and $j.p2p_summary.security) {
        $bans = [int]($j.p2p_summary.security.active_bans)
    }
    return @{
        Height = [int]$j.height
        Peers  = [int]$j.peers
        Bans   = $bans
        NodeId = [string]$j.node_id
    }
}

$followers = @("lr1", "lr2")
$deadline = (Get-Date).AddHours([Math]::Max(0.25, $Hours))
$nextBounce = (Get-Date).AddSeconds([Math]::Max(120, $BounceEverySec))
$bounceIdx = 0
$badCycles = 0
$hardFail = 0

Write-ChaosLog "chaos_pulse start hours=$Hours check=${CheckSec}s bounce_every=${BounceEverySec}s ports=$($Ports -join ',')" "Cyan"

while ((Get-Date) -lt $deadline) {
    try {
        $rows = @()
        foreach ($p in $Ports) {
            $rows += (Get-LabStatus -Port $p)
        }
        $miner = $rows[0]
        $maxBan = ($rows | ForEach-Object { [int]$_.Bans } | Measure-Object -Maximum).Maximum
        $heights = @($rows | ForEach-Object { [int]$_.Height })
        $delta = ($heights | Measure-Object -Maximum).Maximum - ($heights | Measure-Object -Minimum).Minimum
        $detail = (0..($Ports.Count - 1) | ForEach-Object {
            "$($Ports[$_]):h$($rows[$_].Height)/p$($rows[$_].Peers)/b$($rows[$_].Bans)"
        }) -join " "

        $bad = ($miner.Peers -lt 2) -or ($maxBan -gt 0) -or ($delta -gt 2)
        if ($bad) {
            $badCycles++
            Write-ChaosLog "WARN chaos mesh $detail delta=$delta bad_cycles=$badCycles" "Yellow"
            if ($badCycles -ge [Math]::Max(2, $BanPeersFailAfterCycles)) {
                Write-ChaosLog "FAIL chaos isolation miner_peers=$($miner.Peers) max_ban=$maxBan delta=$delta (persist ${badCycles}x)" "Red"
                $hardFail++
                $badCycles = 0
            }
        } else {
            $badCycles = 0
            Write-ChaosLog "OK chaos mesh $detail delta=$delta" "DarkGray"
        }
    } catch {
        $badCycles++
        Write-ChaosLog "WARN chaos status error: $($_.Exception.Message) bad_cycles=$badCycles" "Yellow"
    }

    if ((Get-Date) -ge $nextBounce) {
        $svc = $followers[$bounceIdx % $followers.Count]
        $bounceIdx++
        Write-ChaosLog "chaos bounce restart $svc (force reconnect / mesh_min path)" "Yellow"
        try {
            docker compose -p $ComposeProject -f $ComposeFile restart $svc | Out-Null
            Start-Sleep -Seconds 20
        } catch {
            Write-ChaosLog "WARN chaos bounce failed $svc: $($_.Exception.Message)" "Yellow"
        }
        $nextBounce = (Get-Date).AddSeconds([Math]::Max(120, $BounceEverySec))
    }

    Start-Sleep -Seconds ([Math]::Max(5, $CheckSec))
}

Write-ChaosLog "chaos_pulse done hard_fails=$hardFail" $(if ($hardFail -gt 0) { "Red" } else { "Green" })
exit $(if ($hardFail -gt 0) { 1 } else { 0 })
