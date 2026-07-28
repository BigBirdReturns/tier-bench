[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$Lab,
    [string]$Cluster,
    [ValidateSet("smoke", "canary", "full")]
    [string]$Profile = "smoke",
    [string]$ExchangeRoot,
    [string]$CoordinatorState = "D:\TierRuns\ConditionalMemory\Coordinator",
    [string]$Python = "python",
    [string]$FlightId,
    [switch]$PublishOnly,
    [switch]$CollectOnly,
    [switch]$ForceCpu
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $Lab) { $Lab = Join-Path $RepoRoot "experiments\conditional_memory\lab.example.json" }
if (-not $Cluster) { $Cluster = Join-Path $RepoRoot "experiments\conditional_memory\cluster.example.json" }
$Lab = (Resolve-Path $Lab).Path
$Cluster = (Resolve-Path $Cluster).Path
if (-not $ExchangeRoot) { $ExchangeRoot = $env:TIER_EXCHANGE_ROOT }
if (-not $ExchangeRoot) { throw "ExchangeRoot or TIER_EXCHANGE_ROOT is required." }
$ExchangeRoot = [System.IO.Path]::GetFullPath($ExchangeRoot)
if (-not $FlightId) { $FlightId = "cmem-$Profile-$(Get-Date -Format 'yyyyMMdd-HHmmss')" }
$FlightRoot = Join-Path $ExchangeRoot "flights\$FlightId"
$Module = "tier_runner.conditional_memory_exchange_cli"

function Invoke-Tier {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Tier command failed with exit code $LASTEXITCODE." }
}

Push-Location $RepoRoot
try {
    if (-not $CollectOnly) {
        $Arguments = @(
            "-m", $Module, "publish",
            "--lab", $Lab,
            "--cluster", $Cluster,
            "--profile", $Profile,
            "--exchange-root", $ExchangeRoot,
            "--flight-id", $FlightId
        )
        if ($ForceCpu) { $Arguments += "--force-cpu" }
        Invoke-Tier -Arguments $Arguments
        Write-Host "Published $FlightId to $FlightRoot"
        Write-Host "The LG Gram worker can claim the flight now."
    }

    if ($PublishOnly) {
        [PSCustomObject]@{
            ok = $true
            flight_id = $FlightId
            flight_root = $FlightRoot
            phase = "published"
        } | ConvertTo-Json -Depth 5
        exit 0
    }

    Write-Host "Waiting for the LG Gram submissions. Press Ctrl+C to stop polling."
    while ($true) {
        $StatusJson = & $Python -m $Module status --flight-root $FlightRoot
        if ($LASTEXITCODE -ne 0) { throw "Exchange status failed." }
        $Status = $StatusJson | ConvertFrom-Json
        $Counts = $Status.counts
        Write-Host ("pending={0} claimed={1} completed={2} failed={3} collected={4}" -f `
            $Counts.pending, $Counts.claimed, $Counts.completed, $Counts.failed, $Counts.collected)
        if ($Counts.failed -gt 0) { throw "A worker packet failed. Inspect the exchange submission." }
        if (($Counts.pending + $Counts.claimed) -eq 0) { break }
        Start-Sleep -Seconds 3
    }

    $CollectArguments = @(
        "-m", $Module, "collect",
        "--flight-root", $FlightRoot,
        "--coordinator-state", $CoordinatorState
    )
    if ($ForceCpu) { $CollectArguments += "--force-cpu" }
    Invoke-Tier -Arguments $CollectArguments
} finally {
    Pop-Location
}
