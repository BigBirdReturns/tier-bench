[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('template', 'inventory', 'probe-hardware', 'bind', 'verify', 'validate-config')]
    [string]$Command,

    [string]$Config,
    [string]$Out,
    [string]$RepoRoot = '.',
    [string]$NvidiaSmi,
    [string]$DeviceIndices = ''
)

$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction Stop
$script = Join-Path $PSScriptRoot 'astra_stage2_bind_controls.py'

$arguments = @($script, $Command)
switch ($Command) {
    'template' {
        if (-not $Out) { throw '-Out is required' }
        $arguments += @('--out', $Out)
    }
    'inventory' {
        if (-not $Config -or -not $Out) { throw '-Config and -Out are required' }
        $arguments += @('--config', $Config, '--out', $Out)
    }
    'probe-hardware' {
        if (-not $Out) { throw '-Out is required' }
        $arguments += @('--out', $Out)
        if ($NvidiaSmi) { $arguments += @('--nvidia-smi', $NvidiaSmi) }
        if ($DeviceIndices) { $arguments += @('--device-indices', $DeviceIndices) }
    }
    'bind' {
        if (-not $Config -or -not $Out) { throw '-Config and -Out are required' }
        $arguments += @('--config', $Config, '--repo-root', $RepoRoot, '--out', $Out)
    }
    'verify' {
        if (-not $Config -or -not $Out) { throw '-Config and -Out are required' }
        $arguments += @('--config', $Config, '--repo-root', $RepoRoot, '--out', $Out)
    }
    'validate-config' {
        if (-not $Config) { throw '-Config is required' }
        $arguments += @('--config', $Config)
    }
}

& $python.Source @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Astra Stage 2 control identity command failed with exit code $LASTEXITCODE"
}
