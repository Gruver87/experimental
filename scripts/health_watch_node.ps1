# Single-port health_watch worker (Start-Job). Outputs one JSON object per line.
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [bool]$FullHarness = $false,
    [bool]$ProdMesh = $false,
    [bool]$Strict = $false,
    [string]$ScriptDir = ""
)

$ErrorActionPreference = "Continue"
if (-not $ScriptDir) {
    $ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
}
. (Join-Path $ScriptDir "health_watch_core.ps1")
$r = Test-NodeHealth -Port $Port -FullHarness:$FullHarness -ProdMesh:$ProdMesh -Strict:($Strict -eq $true)
@{
    Ok = [bool]$r.Ok
    Port = [int]$r.Port
    Height = $(if ($null -ne $r.Height) { [int]$r.Height } else { 0 })
    Head = [string]$r.Head
    Peers = $(if ($null -ne $r.Peers) { [int]$r.Peers } else { 0 })
    P2P = [string]$r.P2P
    Aligned = $(if ($null -ne $r.Aligned) { [bool]$r.Aligned } else { $false })
    HarnessHealthy = $(if ($null -ne $r.HarnessHealthy) { [bool]$r.HarnessHealthy } else { $false })
    Failed = @($r.Failed)
    FullHarness = [bool]$r.FullHarness
    ReadyFlap = [bool]$r.ReadyFlap
    ReadyFallback = [bool]$r.ReadyFallback
    Error = [string]$r.Error
} | ConvertTo-Json -Compress -Depth 5
