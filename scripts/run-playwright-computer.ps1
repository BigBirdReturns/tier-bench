[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$Config,
    [string]$ComputerRoot = "D:\TierRuns\BrowserComputers\desktop-playwright-computer-01",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8788,
    [string]$Python = "python",
    [switch]$InstallScheduledTask,
    [string]$TaskName = "TierBrowser-Desktop-Computer"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $Config) { $Config = Join-Path $RepoRoot "experiments\task_computer\playwright.example.json" }
$Config = (Resolve-Path $Config).Path
$ComputerRoot = [System.IO.Path]::GetFullPath($ComputerRoot)
New-Item -ItemType Directory -Path $ComputerRoot -Force | Out-Null

if (-not $env:TIER_BROWSER_TOKEN) {
    throw "TIER_BROWSER_TOKEN must contain the control-plane token."
}
if (-not $env:TIER_BROWSER_APPROVAL_TOKEN) {
    Write-Warning "TIER_BROWSER_APPROVAL_TOKEN is unset. External writes and sensitive inputs will remain blocked."
}

if ($InstallScheduledTask) {
    $ScriptPath = $MyInvocation.MyCommand.Path
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $ScriptPath + '"'),
        "-RepoRoot", ('"' + $RepoRoot + '"'),
        "-Config", ('"' + $Config + '"'),
        "-ComputerRoot", ('"' + $ComputerRoot + '"'),
        "-HostAddress", $HostAddress,
        "-Port", $Port
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
    "-m", "tier_runner.playwright_computer_cli", "serve",
    "--config", $Config,
    "--root", $ComputerRoot,
    "--host", $HostAddress,
    "--port", $Port
)
if ($HostAddress -notin @("127.0.0.1", "localhost", "::1")) {
    $Arguments += "--unsafe-network"
}

Push-Location $RepoRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
