[CmdletBinding()]
param(
    [ValidateSet("quick", "profiles", "driver", "gaps", "assess", "verify")]
    [string]$Command = "quick",
    [string]$RepoRoot,
    [string]$Manifest,
    [string]$Registry,
    [string]$DriverCommand,
    [string]$DriverStateRoot,
    [string]$Bundle,
    [string]$ArtifactRoot,
    [string]$OutRoot = "D:\TierRuns\TaskFloor",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $Manifest) { $Manifest = Join-Path $RepoRoot "experiments\task_floor\reference_manifest.json" }
if (-not $Registry) { $Registry = Join-Path $RepoRoot "experiments\task_floor\oss_registry.json" }
$Manifest = (Resolve-Path $Manifest).Path
$Registry = (Resolve-Path $Registry).Path
$OutRoot = [System.IO.Path]::GetFullPath($OutRoot)
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null
if (-not $DriverStateRoot) { $DriverStateRoot = Join-Path $OutRoot "reference-driver-state" }
if (-not $DriverCommand) {
    $ReferenceDriver = Join-Path $RepoRoot "examples\task_floor\reference_driver.py"
    $DriverCommand = '"' + $Python + '" "' + $ReferenceDriver + '"'
}
$env:TASK_FLOOR_DRIVER_ROOT = [System.IO.Path]::GetFullPath($DriverStateRoot)
$Module = "tier_runner.task_floor_cli"

function Invoke-TierFloor {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Task Floor command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $RepoRoot
try {
    switch ($Command) {
        "profiles" {
            Invoke-TierFloor -Arguments @("-m", $Module, "profiles")
        }
        "driver" {
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "driver-test",
                "--command", $DriverCommand,
                "--cwd", $RepoRoot,
                "--out", (Join-Path $OutRoot "driver-conformance.json")
            )
            Get-Content (Join-Path $OutRoot "driver-conformance.json") -Raw
        }
        "gaps" {
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "registry-validate",
                "--registry", $Registry,
                "--out", (Join-Path $OutRoot "registry-validation.json")
            )
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "gap-report",
                "--registry", $Registry,
                "--out", (Join-Path $OutRoot "gap-report.json")
            )
            Get-Content (Join-Path $OutRoot "gap-report.json") -Raw
        }
        "assess" {
            if (-not $Bundle) { throw "Bundle is required for assess." }
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "bundle-assess",
                "--bundle", ([System.IO.Path]::GetFullPath($Bundle)),
                "--out", (Join-Path $OutRoot "bundle-conformance.json")
            )
            Get-Content (Join-Path $OutRoot "bundle-conformance.json") -Raw
        }
        "verify" {
            if (-not $Bundle) { throw "Bundle is required for verify." }
            $Arguments = @(
                "-m", $Module, "bundle-verify",
                "--bundle", ([System.IO.Path]::GetFullPath($Bundle))
            )
            if ($ArtifactRoot) {
                $Arguments += @("--artifact-root", ([System.IO.Path]::GetFullPath($ArtifactRoot)))
            }
            Invoke-TierFloor -Arguments $Arguments
        }
        "quick" {
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "manifest-validate",
                "--manifest", $Manifest,
                "--out", (Join-Path $OutRoot "manifest-validation.json")
            )
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "registry-validate",
                "--registry", $Registry,
                "--out", (Join-Path $OutRoot "registry-validation.json")
            )
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "gap-report",
                "--registry", $Registry,
                "--out", (Join-Path $OutRoot "gap-report.json")
            )
            Invoke-TierFloor -Arguments @(
                "-m", $Module, "driver-test",
                "--command", $DriverCommand,
                "--cwd", $RepoRoot,
                "--out", (Join-Path $OutRoot "driver-conformance.json")
            )
            $Driver = Get-Content (Join-Path $OutRoot "driver-conformance.json") -Raw | ConvertFrom-Json
            $Gaps = Get-Content (Join-Path $OutRoot "gap-report.json") -Raw | ConvertFrom-Json
            [PSCustomObject]@{
                ok = [bool]$Driver.passed
                highest_live_driver_profile = $Driver.highest_contiguous_profile
                registry_entries = $Gaps.entries
                gap_axes = $Gaps.axes
                critical_gaps = @($Gaps.critical_gaps)
                output_root = $OutRoot
            } | ConvertTo-Json -Depth 8
        }
    }
} finally {
    Pop-Location
}
