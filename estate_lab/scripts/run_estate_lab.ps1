[CmdletBinding()]
param(
    [string]$Workspace = "D:\Projects",
    [string]$Output = "D:\Projects\AXM\estate-lab-runs",
    [ValidateSet("none", "smoke", "full", "all")]
    [string]$ProbeProfile = "smoke",
    [ValidateSet("synthetic", "live")]
    [string]$Mode = "live"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $RepoRoot
try {
    python -m estate_lab validate
    if ($LASTEXITCODE -ne 0) { throw "Estate Lab validation failed." }

    python -m unittest discover -s estate_lab/tests -v
    if ($LASTEXITCODE -ne 0) { throw "Estate Lab tests failed." }

    python -m estate_lab discover `
        --workspace $Workspace `
        --mode $Mode `
        --probe-profile $ProbeProfile
    if ($LASTEXITCODE -ne 0) { throw "Estate discovery failed." }

    python -m estate_lab run-all `
        --workspace $Workspace `
        --mode $Mode `
        --probe-profile $ProbeProfile `
        --output $Output
    if ($LASTEXITCODE -ne 0) { throw "One or more Estate Lab scenarios failed." }
}
finally {
    Pop-Location
}
