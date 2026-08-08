[CmdletBinding()]
param(
    [ValidateSet("planner", "critic")]
    [string]$Role,
    [string]$SeatId,
    [string]$GpuUuidEnv,
    [string]$ExpectedNameContains = "3090",
    [Parameter(Mandatory = $true)]
    [string]$ModelCommand,
    [string]$RepoRoot,
    [string]$ExchangeRoot,
    [string]$Python = "python",
    [switch]$Once,
    [switch]$InstallScheduledTask,
    [string]$TaskName
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $Role) { $Role = "planner" }
if (-not $SeatId) {
    $SeatId = if ($Role -eq "planner") { "gpu.3090-a" } else { "gpu.3090-b" }
}
if (-not $GpuUuidEnv) {
    $GpuUuidEnv = if ($Role -eq "planner") { "TIER_GPU_3090_A_UUID" } else { "TIER_GPU_3090_B_UUID" }
}
if (-not $TaskName) { $TaskName = "TierTaskComputer-$Role-$SeatId" }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $ExchangeRoot) { $ExchangeRoot = $env:TIER_EXCHANGE_ROOT }
if (-not $ExchangeRoot) { throw "ExchangeRoot or TIER_EXCHANGE_ROOT is required." }
$ExchangeRoot = [System.IO.Path]::GetFullPath($ExchangeRoot)
if (-not [Environment]::GetEnvironmentVariable($GpuUuidEnv)) {
    throw "$GpuUuidEnv must contain the exact nvidia-smi UUID for $SeatId."
}

if ($InstallScheduledTask) {
    $ScriptPath = $MyInvocation.MyCommand.Path
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $ScriptPath + '"'),
        "-Role", $Role,
        "-SeatId", $SeatId,
        "-GpuUuidEnv", $GpuUuidEnv,
        "-ExpectedNameContains", $ExpectedNameContains,
        "-ModelCommand", ('"' + $ModelCommand.Replace('"', '\"') + '"'),
        "-RepoRoot", ('"' + $RepoRoot + '"'),
        "-ExchangeRoot", ('"' + $ExchangeRoot + '"')
    ) -join " "
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
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

$Arguments = @(
    "-m", "tier_runner.task_computer_worker_cli",
    "--exchange-root", $ExchangeRoot,
    "--role", $Role,
    "--seat-id", $SeatId,
    "--command", $ModelCommand,
    "--gpu-uuid-env", $GpuUuidEnv,
    "--expected-name-contains", $ExpectedNameContains,
    "--poll-seconds", "1",
    "--reclaim-after-seconds", "600"
)
if ($Once) { $Arguments += "--once" }

Push-Location $RepoRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
