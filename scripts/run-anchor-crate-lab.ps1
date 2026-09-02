[CmdletBinding()]
param(
    [ValidateSet('quick', 'cuda-fixture', 'riscv-fixture', 'resume-demo', 'conformance')]
    [string]$Command = 'quick',
    [string]$OutRoot = "$env:USERPROFILE\TierRuns\AnchorCrate",
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Floor = Join-Path $Repo 'labs\community-home-lab\anchor-crate\floor.json'
$Cartridge = Join-Path $Repo 'labs\community-home-lab\anchor-crate\physical_availability_cartridge.json'
$Backends = Join-Path $Repo 'labs\community-home-lab\anchor-crate\backend_registry.json'
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

function Invoke-Anchor([string[]]$Arguments) {
    & $Python -m tier_runner.anchor_crate @Arguments
    if ($LASTEXITCODE -ne 0) { throw "tieranchor failed with exit code $LASTEXITCODE" }
}

Invoke-Anchor -Arguments @('validate', '--floor', $Floor, '--cartridge', $Cartridge, '--backends', $Backends)
& $Python (Join-Path $Repo 'scripts\verify_anchor_crate_bundle.py') --repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Anchor Crate bundle verification failed' }

if ($Command -eq 'quick') { exit 0 }

if ($Command -eq 'conformance') {
    foreach ($Backend in @(
        'backend.host-controller-fixture',
        'backend.cuda3090-fixture',
        'backend.riscv-llm-fixture'
    )) {
        $Name = $Backend.Replace('backend.', '')
        Invoke-Anchor -Arguments @(
            'conformance', '--backends', $Backends, '--backend', $Backend,
            '--controller-cwd', $Repo, '--out', (Join-Path $OutRoot "conformance.$Name.json")
        )
    }
    exit 0
}

if ($Command -eq 'resume-demo') {
    $RunRoot = Join-Path $OutRoot 'resume-demo'
    if (Test-Path $RunRoot) { Remove-Item -Recurse -Force $RunRoot }
    Invoke-Anchor -Arguments @(
        'run', '--floor', $Floor, '--cartridge', $Cartridge, '--backends', $Backends,
        '--run-root', $RunRoot, '--controller-cwd', $Repo,
        '--stop-after-node', 'derive_availability', '--out', (Join-Path $RunRoot 'paused.json')
    )
    $Anchor = Get-ChildItem (Join-Path $RunRoot 'anchors') -Filter '0002-*.json' | Select-Object -First 1
    if ($null -eq $Anchor) { throw 'No sequence-2 anchor was produced' }
    Invoke-Anchor -Arguments @(
        'run', '--floor', $Floor, '--cartridge', $Cartridge, '--backends', $Backends,
        '--run-root', $RunRoot, '--controller-cwd', $Repo,
        '--resume-anchor', $Anchor.FullName, '--out', (Join-Path $RunRoot 'resumed.json')
    )
    exit 0
}

$BackendArgs = @()
$RunName = 'cuda-fixture'
if ($Command -eq 'riscv-fixture') {
    $BackendArgs = @('--bind', 'generate_decision_packet=backend.riscv-llm-fixture')
    $RunName = 'riscv-fixture'
}
$RunRoot = Join-Path $OutRoot $RunName
if (Test-Path $RunRoot) { Remove-Item -Recurse -Force $RunRoot }
$RunArgs = @(
    'run', '--floor', $Floor, '--cartridge', $Cartridge, '--backends', $Backends,
    '--run-root', $RunRoot, '--controller-cwd', $Repo
) + $BackendArgs + @('--out', (Join-Path $RunRoot 'result.json'))
Invoke-Anchor -Arguments $RunArgs
