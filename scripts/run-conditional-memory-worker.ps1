[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ExchangeRoot,
    [string]$WorkRoot = "C:\TierWorker\ConditionalMemory",
    [string]$NodeId = "lg-gram-dual3090",
    [string]$Python = "python",
    [switch]$Once,
    [switch]$ReclaimStale,
    [switch]$ForceCpu,
    [switch]$InstallScheduledTask,
    [string]$TaskName = "TierMemory-LG-Gram-Worker"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $ExchangeRoot) { $ExchangeRoot = $env:TIER_EXCHANGE_ROOT }
if (-not $ExchangeRoot) { throw "ExchangeRoot or TIER_EXCHANGE_ROOT is required." }
$ExchangeRoot = [System.IO.Path]::GetFullPath($ExchangeRoot)
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

if ($InstallScheduledTask) {
    $ScriptPath = $MyInvocation.MyCommand.Path
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $ScriptPath + '"'),
        "-RepoRoot", ('"' + $RepoRoot + '"'),
        "-ExchangeRoot", ('"' + $ExchangeRoot + '"'),
        "-WorkRoot", ('"' + $WorkRoot + '"'),
        "-NodeId", $NodeId
    ) -join " "
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Days 7)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -RunLevel Highest `
        -Force | Out-Null
    Write-Host "Installed scheduled task $TaskName"
    exit 0
}

$Module = "tier_runner.conditional_memory_exchange_cli"
$Arguments = @(
    "-m", $Module, "worker-loop",
    "--exchange-root", $ExchangeRoot,
    "--node", $NodeId,
    "--work-root", $WorkRoot,
    "--poll-seconds", "5",
    "--max-wait-seconds", "86400"
)
if ($Once) { $Arguments += "--once" }
if ($ReclaimStale) { $Arguments += "--reclaim-stale" }
if ($ForceCpu) { $Arguments += "--force-cpu" }

Push-Location $RepoRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
