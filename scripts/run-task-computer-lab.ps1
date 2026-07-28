[CmdletBinding()]
param(
    [ValidateSet("list", "run", "suite", "verify", "fixture")]
    [string]$Command = "suite",
    [string]$RepoRoot,
    [string]$Catalog,
    [string]$Scenario = "axm-chat-pull-latest",
    [string]$Variant = "base",
    [string]$OutRoot = "D:\TierRuns\TaskComputer",
    [string]$RunDir,
    [string]$PlannerCommand,
    [string]$PlannerExchange,
    [string]$CriticCommand,
    [string]$CriticExchange,
    [string]$Python = "python",
    [switch]$Headed,
    [switch]$Trace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $Catalog) { $Catalog = Join-Path $RepoRoot "experiments\task_computer\project_scenarios.json" }
$Catalog = (Resolve-Path $Catalog).Path
$Module = "tier_runner.task_computer_cli"

$Arguments = @("-m", $Module)
switch ($Command) {
    "list" {
        $Arguments += @("list", "--catalog", $Catalog)
    }
    "run" {
        $Arguments += @(
            "run", "--catalog", $Catalog,
            "--scenario", $Scenario,
            "--variant", $Variant,
            "--out-root", $OutRoot
        )
        if ($Headed) { $Arguments += "--headed" }
        if (-not $Trace) { $Arguments += "--no-trace" }
        if ($PlannerCommand) { $Arguments += @("--planner-command", $PlannerCommand) }
        if ($PlannerExchange) { $Arguments += @("--planner-exchange", $PlannerExchange) }
        if ($CriticCommand) { $Arguments += @("--critic-command", $CriticCommand) }
        if ($CriticExchange) { $Arguments += @("--critic-exchange", $CriticExchange) }
    }
    "suite" {
        $Arguments += @("suite", "--catalog", $Catalog, "--out-root", $OutRoot)
        if ($Headed) { $Arguments += "--headed" }
        if ($Trace) { $Arguments += "--trace" }
    }
    "verify" {
        if (-not $RunDir) { throw "RunDir is required for verify." }
        $Arguments += @("verify", "--run-dir", $RunDir)
    }
    "fixture" {
        $Arguments += @(
            "serve-fixture", "--catalog", $Catalog,
            "--scenario", $Scenario,
            "--variant", $Variant
        )
    }
}

Push-Location $RepoRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
