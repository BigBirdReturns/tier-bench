[CmdletBinding()]
param(
    [ValidateSet('Preflight', 'Prepare', 'Bind', 'Verify')]
    [string]$Mode = 'Prepare',

    [string]$RepoRoot,
    [string]$CustodyRoot = 'S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities-real',
    [string]$Python = 'python',
    [switch]$SkipDownloads
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BinderHead = 'dbb44b7efca1b04f2ed2d8c127af653b278909e4'
$BinderTree = '2671247337030d9c8e281393103104f7436d2800'
$LawHead = 'c36c35bf9b70d879e1e1c9ee2f0296879442df3e'
$LawBlob = '77abe4e177fc61e4f52f56ea64494b113f9662fc'
$ScaffoldHead = '9babad4631ef517485c56ea4906aab123e30fad7'
$Stage1Join = '60bca963d63edca267106bc5c7725c2cc1df8dd7'

$LotusSourceCommit = 'eb77e2f7909c5006f58ff0ad7cd6629b942caa9e'
$LoopCoderSourceCommit = 'ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c'
$LotusRevision = 'b392d2cb7aaa73475b93028221523c47f49f66a2'
$LoopCoderRevision = 'b87cf3aa2186937b0d0362a684d7d30f234543e3'
$CotRevision = '63de1ec1902ed143fe62250b6ddb14cb65f06e1a'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $File @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed ($exitCode): $File $($Arguments -join ' ')"
    }
}

function Invoke-GitText {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = & git -C $Root @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Git command failed ($exitCode) at ${Root}: git $($Arguments -join ' ')"
    }
    return (($output -join "`n").Trim())
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        return (Resolve-Path -LiteralPath $Path).ProviderPath
    }
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-GitWorkTree {
    param([Parameter(Mandatory = $true)][string]$Candidate)

    if (-not (Test-Path -LiteralPath $Candidate -PathType Container)) {
        return $false
    }
    $null = & git -C $Candidate rev-parse --is-inside-work-tree 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Resolve-RepositoryRoot {
    param([string]$RequestedRoot)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedRoot)) {
        $candidates += $RequestedRoot
    }
    $candidates += (Join-Path $PSScriptRoot '..')
    $candidates += 'D:\Projects\Measurement\Tier-Bench\main'
    $candidates += 'D:\Projects\Measurement\Tier-Bench'

    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        try {
            $normalized = Get-NormalizedPath -Path $candidate
        }
        catch {
            continue
        }
        $key = $normalized.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            continue
        }
        $seen[$key] = $true
        if (Test-GitWorkTree -Candidate $normalized) {
            return $normalized
        }
    }

    throw (
        'Unable to discover the Tier-Bench Git repository. Supply -RepoRoot. ' +
        'The canonical estate checkout is D:\Projects\Measurement\Tier-Bench\main.'
    )
}

function Get-GitHead {
    param([Parameter(Mandatory = $true)][string]$Root)
    return Invoke-GitText -Root $Root -Arguments @('rev-parse', 'HEAD')
}

function Get-GitTree {
    param([Parameter(Mandatory = $true)][string]$Root)
    return Invoke-GitText -Root $Root -Arguments @('rev-parse', 'HEAD^{tree}')
}

function Assert-CleanWorkTree {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $dirty = & git -C $Root status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect ${Label}: $Root"
    }
    if ($dirty) {
        throw "${Label} is dirty: $Root"
    }
}

function Ensure-ExactSource {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath (Join-Path $Destination '.git'))) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Invoke-Checked -File 'git' -Arguments @('-C', $Destination, 'init')
        Invoke-Checked -File 'git' -Arguments @(
            '-C', $Destination, 'remote', 'add', 'origin',
            ("https://github.com/{0}.git" -f $Repository)
        )
        Invoke-Checked -File 'git' -Arguments @(
            '-C', $Destination, 'fetch', '--no-tags', '--depth=1', 'origin', $Commit
        )
        Invoke-Checked -File 'git' -Arguments @(
            '-C', $Destination, 'checkout', '--detach', 'FETCH_HEAD'
        )
    }

    Assert-ExactSource -Repository $Repository -Commit $Commit -Destination $Destination
}

function Assert-ExactSource {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath (Join-Path $Destination '.git'))) {
        throw "Exact source checkout is absent for ${Repository}: $Destination"
    }
    $head = Get-GitHead -Root $Destination
    if ($head -ne $Commit) {
        throw "Source checkout drift for ${Repository}: expected $Commit, observed $head"
    }
    Assert-CleanWorkTree -Root $Destination -Label "Source checkout for $Repository"
}

function Ensure-BinderWorktree {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Root
    )

    if (-not (Test-GitWorkTree -Candidate $RepositoryRoot)) {
        throw "Tier-Bench repository not found at $RepositoryRoot"
    }

    Invoke-Checked -File 'git' -Arguments @(
        '-C', $RepositoryRoot, 'fetch', '--no-tags', 'origin', $BinderHead
    )

    if (-not (Test-Path -LiteralPath $Root)) {
        Invoke-Checked -File 'git' -Arguments @(
            '-C', $RepositoryRoot, 'worktree', 'add', '--detach', $Root, $BinderHead
        )
    }

    if (-not (Test-GitWorkTree -Candidate $Root)) {
        throw "Binder worktree is absent or invalid: $Root"
    }

    $head = Get-GitHead -Root $Root
    if ($head -ne $BinderHead) {
        throw "Binder worktree must be exact head $BinderHead; observed $head"
    }

    $tree = Get-GitTree -Root $Root
    if ($tree -ne $BinderTree) {
        throw "Binder tree mismatch: expected $BinderTree, observed $tree"
    }

    $observedLawBlob = Invoke-GitText -Root $Root -Arguments @(
        'rev-parse', 'HEAD:docs/agents/claims/FRR-ASTRA-STAGE2-1.md'
    )
    if ($observedLawBlob -ne $LawBlob) {
        throw 'Released Sol law blob is not present at the pinned binder head'
    }

    Assert-CleanWorkTree -Root $Root -Label 'Binder worktree'
}

function Ensure-HuggingFaceTools {
    param([Parameter(Mandatory = $true)][string]$VenvRoot)

    $windowsPython = Join-Path $VenvRoot 'Scripts\python.exe'
    $posixPython = Join-Path $VenvRoot 'bin/python'

    if (-not (Test-Path -LiteralPath $windowsPython) -and
        -not (Test-Path -LiteralPath $posixPython)) {
        Invoke-Checked -File $Python -Arguments @('-m', 'venv', $VenvRoot)
    }

    if (Test-Path -LiteralPath $windowsPython) {
        $venvPython = $windowsPython
    }
    elseif (Test-Path -LiteralPath $posixPython) {
        $venvPython = $posixPython
    }
    else {
        throw "Virtual-environment Python was not created under $VenvRoot"
    }

    Invoke-Checked -File $venvPython -Arguments @(
        '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet',
        'huggingface_hub==0.34.4'
    )
    return $venvPython
}

function Download-ExactSnapshots {
    param(
        [Parameter(Mandatory = $true)][string]$ToolPython,
        [Parameter(Mandatory = $true)][string]$ModelRoot
    )

    $downloadScript = Join-Path $CustodyRoot 'download_exact_control_snapshots.py'
    $scriptText = @'
from pathlib import Path
from huggingface_hub import snapshot_download
import sys

root = Path(sys.argv[1])
items = [
    ('yingfanbot/gsm-lotus-llama3b', 'b392d2cb7aaa73475b93028221523c47f49f66a2'),
    ('Multilingual-Multimodal-NLP/LoopCoder-V2', 'b87cf3aa2186937b0d0362a684d7d30f234543e3'),
    ('yingfanbot/gsm-cot-llama3b', '63de1ec1902ed143fe62250b6ddb14cb65f06e1a'),
]
for repo_id, revision in items:
    target = root / revision
    target.mkdir(parents=True, exist_ok=True)
    kwargs = dict(repo_id=repo_id, revision=revision, local_dir=str(target))
    try:
        snapshot_download(local_dir_use_symlinks=False, **kwargs)
    except TypeError:
        snapshot_download(**kwargs)
    print(f'{repo_id}@{revision} -> {target}')
'@

    [System.IO.File]::WriteAllText(
        $downloadScript,
        $scriptText,
        [System.Text.UTF8Encoding]::new($false)
    )
    Invoke-Checked -File $ToolPython -Arguments @($downloadScript, $ModelRoot)
}

function Assert-CheckpointCustody {
    param([Parameter(Mandatory = $true)][string]$Root)

    foreach ($revision in @($LotusRevision, $LoopCoderRevision, $CotRevision)) {
        $snapshot = Join-Path $Root $revision
        if (-not (Test-Path -LiteralPath $snapshot -PathType Container)) {
            throw "Checkpoint snapshot is absent: $revision"
        }
    }

    $incomplete = Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Name -like '*.incomplete' }
    if ($incomplete) {
        throw "Incomplete checkpoint download files remain under $Root"
    }
}

function Select-LargestNvidiaDevice {
    $nvidia = (Get-Command nvidia-smi -ErrorAction Stop).Source
    $rows = & $nvidia --query-gpu=index,name,memory.total --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0 -or -not $rows) {
        throw 'Unable to query NVIDIA devices'
    }

    $parsed = foreach ($line in $rows) {
        $parts = $line -split ',' | ForEach-Object { $_.Trim() }
        if ($parts.Count -ne 3) {
            throw "Unexpected nvidia-smi row: $line"
        }
        [pscustomobject]@{
            Index = [int]$parts[0]
            Name = $parts[1]
            MemoryMiB = [int]$parts[2]
        }
    }

    $selected = $parsed |
        Sort-Object @{Expression = 'MemoryMiB'; Descending = $true},
                    @{Expression = 'Index'; Descending = $false} |
        Select-Object -First 1

    return [pscustomobject]@{
        NvidiaSmi = $nvidia
        Device = $selected
    }
}

function Write-PreparedConfig {
    param(
        [Parameter(Mandatory = $true)][string]$BinderRoot,
        [Parameter(Mandatory = $true)][string]$LotusSource,
        [Parameter(Mandatory = $true)][string]$LoopCoderSource,
        [Parameter(Mandatory = $true)][string]$Models,
        [Parameter(Mandatory = $true)][string]$HardwareRoot,
        [Parameter(Mandatory = $true)][int]$DeviceIndex,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )

    $templatePath = Join-Path $BinderRoot 'experiments\astra_kxr\stage2\control_identity\binding-template.json'
    $config = Get-Content -Raw -LiteralPath $templatePath | ConvertFrom-Json
    $config.binding_id = 'astra-stage2-controls-' + (Get-Date -Format 'yyyyMMdd-HHmmss')

    foreach ($control in $config.controls) {
        switch ($control.role) {
            'lotus_3b_recurrent' {
                $control.source_root = $LotusSource
                $control.model_root = Join-Path $Models $LotusRevision
            }
            'loopcoder_v2_7b_parallel' {
                $control.source_root = $LoopCoderSource
                $control.model_root = Join-Path $Models $LoopCoderRevision
            }
            'conventional_transformer_negative' {
                $control.source_root = $LotusSource
                $control.model_root = Join-Path $Models $CotRevision
            }
            default {
                throw "Unexpected control role: $($control.role)"
            }
        }

        $control.hardware.evidence_root = $HardwareRoot
        $control.hardware.platform_path = 'platform.json'
        $control.hardware.device_query_path = 'nvidia-query.csv'
        $control.hardware.topology_evidence_path = 'nvidia-topology.json'
        $control.hardware.selected_device_indices = @($DeviceIndex)
    }

    $json = $config | ConvertTo-Json -Depth 64
    [System.IO.File]::WriteAllText(
        $OutputPath,
        $json + "`n",
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporary = $Path + '.tmp'
    $json = $Value | ConvertTo-Json -Depth 64
    [System.IO.File]::WriteAllText(
        $temporary,
        $json + "`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -Force -LiteralPath $temporary -Destination $Path
}

function Get-CanonicalPayloadSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $program = @'
import hashlib
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
value.pop("payload_sha256", None)
payload = json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
print(hashlib.sha256(payload).hexdigest())
'@
    $digest = (& $Python -c $program $Path)
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical payload hashing failed for $Path"
    }
    return ([string]$digest).Trim().ToLowerInvariant()
}

function Assert-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is absent: $Path"
    }
    $observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($observed -ne $Expected.ToLowerInvariant()) {
        throw "$Label digest mismatch: expected $Expected, observed $observed"
    }
}

function Assert-BindReady {
    param([Parameter(Mandatory = $true)][string]$ConfigPath)

    $raw = Get-Content -Raw -LiteralPath $ConfigPath
    if ($raw -match 'REPLACE') {
        throw 'Runtime identity is still unbound. Replace every REPLACE value before Bind.'
    }

    $config = $raw | ConvertFrom-Json
    foreach ($control in $config.controls) {
        $low = $control.effort_mapping.low.arguments | ConvertTo-Json -Compress
        $high = $control.effort_mapping.high.arguments | ConvertTo-Json -Compress
        if ($low -eq '["--effort","low"]' -and
            $high -eq '["--effort","high"]') {
            throw (
                "Effort mapping for $($control.role) is still the " +
                'non-authoritative template. Bind is refused.'
            )
        }
    }
}

function Invoke-PinnedBinder {
    param(
        [Parameter(Mandatory = $true)][string]$BinderRoot,
        [Parameter(Mandatory = $true)][string]$Wrapper,
        [Parameter(Mandatory = $true)][hashtable]$Parameters
    )

    if (-not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
        throw "Pinned binder wrapper is absent: $Wrapper"
    }

    $expectedRoot = Get-NormalizedPath -Path $BinderRoot
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $previousPythonPath = $env:PYTHONPATH
    $locationPushed = $false

    try {
        $env:PYTHONPATH = $expectedRoot
        Push-Location -LiteralPath $expectedRoot
        $locationPushed = $true

        $observedRoot = Get-NormalizedPath -Path ((Get-Location).Path)
        if (-not $observedRoot.Equals(
            $expectedRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Pinned binder working-directory mismatch: $observedRoot"
        }

        & $Wrapper @Parameters
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $command = [string]$Parameters['Command']
            throw (
                "Pinned binder command failed ($exitCode) from ${expectedRoot}: " +
                $command
            )
        }
    }
    finally {
        if ($locationPushed) {
            Pop-Location
        }
        if ($hadPythonPath) {
            $env:PYTHONPATH = $previousPythonPath
        }
        else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
}

function Get-LauncherCoordinates {
    param([Parameter(Mandatory = $true)][string]$Root)

    if (-not (Test-GitWorkTree -Candidate $Root)) {
        throw "Launcher is not executing from a Git worktree: $Root"
    }

    $head = Get-GitHead -Root $Root
    $tree = Get-GitTree -Root $Root
    $null = & git -C $Root merge-base --is-ancestor $BinderHead $head
    if ($LASTEXITCODE -ne 0) {
        throw "Launcher head $head is not descended from pinned binder head $BinderHead"
    }
    Assert-CleanWorkTree -Root $Root -Label 'Release launcher worktree'

    return [pscustomobject]@{
        Root = $Root
        Head = $head
        Tree = $tree
    }
}

function Assert-CurrentPreflight {
    param(
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)]$LauncherCoordinates
    )

    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
        throw "Current Preflight receipt is absent: $ReceiptPath"
    }

    $receipt = Get-Content -Raw -LiteralPath $ReceiptPath | ConvertFrom-Json
    if ($receipt.state -ne 'PREFLIGHT_PASS') {
        throw "Preflight did not pass: $($receipt.state)"
    }
    if ($receipt.release_head -ne $LauncherCoordinates.Head -or
        $receipt.release_tree -ne $LauncherCoordinates.Tree) {
        throw 'Preflight receipt does not bind the current release head and tree'
    }
    if ($receipt.binder_import_smoke -ne 'PASS' -or
        $receipt.binder_execution_cwd -ne 'PINNED_BINDER_ROOT' -or
        $receipt.binder_pythonpath -ne 'PINNED_BINDER_ROOT') {
        throw 'Preflight did not prove the pinned binder import root'
    }
    if ($receipt.downloads_performed -ne $false -or
        $receipt.model_calls -ne 0 -or
        $receipt.provider_calls -ne 0 -or
        $receipt.actual_executable_control_identities -ne 'UNBOUND') {
        throw 'Preflight widened authority or performed asset acquisition'
    }
}

$RepoRoot = Resolve-RepositoryRoot -RequestedRoot $RepoRoot
$LauncherRoot = Get-NormalizedPath -Path (Join-Path $PSScriptRoot '..')
$LauncherCoordinates = Get-LauncherCoordinates -Root $LauncherRoot

New-Item -ItemType Directory -Force -Path $CustodyRoot | Out-Null
$BinderRoot = Join-Path $CustodyRoot ('tier-bench-binder-' + $BinderHead.Substring(0, 8))
$SourceRoot = Join-Path $CustodyRoot 'sources'
$ModelRoot = Join-Path $CustodyRoot 'models'
$HardwareRoot = Join-Path $CustodyRoot 'hardware'
$PrivateConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.private.json'
$InventoriedConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.inventoried.private.json'
$BoundRoot = Join-Path $CustodyRoot 'bound'
$PreflightReceipt = Join-Path $CustodyRoot 'PREFLIGHT-RECEIPT.json'
$PrepareReceipt = Join-Path $CustodyRoot 'PREPARE-RECEIPT.json'

Ensure-BinderWorktree -RepositoryRoot $RepoRoot -Root $BinderRoot
$wrapper = Join-Path $BinderRoot 'scripts\astra_stage2_bind_controls.ps1'

if ($Mode -eq 'Preflight') {
    $smokeRoot = Join-Path $CustodyRoot 'preflight-binder-import-smoke'
    $callerRoot = Join-Path $smokeRoot 'non-binder-cwd'
    $smokeTemplate = Join-Path $smokeRoot 'binding-template.json'
    New-Item -ItemType Directory -Force -Path $callerRoot | Out-Null
    if (Test-Path -LiteralPath $smokeTemplate) {
        Remove-Item -Force -LiteralPath $smokeTemplate
    }

    $callerLocationPushed = $false
    try {
        Push-Location -LiteralPath $callerRoot
        $callerLocationPushed = $true
        $before = Get-NormalizedPath -Path ((Get-Location).Path)
        $binderNormalized = Get-NormalizedPath -Path $BinderRoot
        if ($before.Equals(
            $binderNormalized,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw 'Preflight caller directory unexpectedly equals the binder root'
        }

        Invoke-PinnedBinder `
            -BinderRoot $BinderRoot `
            -Wrapper $wrapper `
            -Parameters @{
                Command = 'template'
                Out = $smokeTemplate
            }

        $after = Get-NormalizedPath -Path ((Get-Location).Path)
        if (-not $after.Equals(
            $before,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw 'Pinned binder command did not restore the non-binder caller directory'
        }
    }
    finally {
        if ($callerLocationPushed) {
            Pop-Location
        }
    }

    if (-not (Test-Path -LiteralPath $smokeTemplate -PathType Leaf)) {
        throw 'Binder import smoke did not emit its template'
    }
    $smoke = Get-Content -Raw -LiteralPath $smokeTemplate | ConvertFrom-Json
    if ($smoke.controls.Count -ne 3) {
        throw 'Binder import smoke emitted an unexpected control denominator'
    }

    $smokeSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $smokeTemplate).Hash.ToLowerInvariant()

    $receipt = [ordered]@{
        schema = 'tier-bench/astra-stage2-control-identity-preflight@2'
        state = 'PREFLIGHT_PASS'
        repository_root = $RepoRoot
        release_root = $LauncherCoordinates.Root
        release_head = $LauncherCoordinates.Head
        release_tree = $LauncherCoordinates.Tree
        binder_head = $BinderHead
        binder_tree = $BinderTree
        binder_root = $BinderRoot
        binder_import_smoke = 'PASS'
        binder_execution_cwd = 'PINNED_BINDER_ROOT'
        binder_pythonpath = 'PINNED_BINDER_ROOT'
        binder_caller_cwd = 'DELIBERATELY_NON_BINDER'
        binder_template_sha256 = $smokeSha256
        downloads_performed = $false
        source_or_checkpoint_bytes_acquired = 0
        model_calls = 0
        provider_calls = 0
        actual_executable_control_identities = 'UNBOUND'
        empirical_calibration = 'NOT_RUN'
        numeric_stage2_freeze = 'NOT_ISSUED'
    }
    Write-JsonFile -Value $receipt -Path $PreflightReceipt

    Write-Host 'PREFLIGHT_PASS'
    Write-Host "Repository root: $RepoRoot"
    Write-Host "Binder worktree: $BinderRoot"
    Write-Host 'Binder import smoke: PASS from deliberately non-binder caller directory'
    exit 0
}

Assert-CurrentPreflight -ReceiptPath $PreflightReceipt -LauncherCoordinates $LauncherCoordinates

if ($Mode -eq 'Prepare') {
    New-Item -ItemType Directory -Force -Path $SourceRoot, $ModelRoot, $HardwareRoot | Out-Null
    $lotusSource = Join-Path $SourceRoot ('lotus-' + $LotusSourceCommit)
    $loopCoderSource = Join-Path $SourceRoot ('loopcoder-' + $LoopCoderSourceCommit)

    if (-not $SkipDownloads) {
        Ensure-ExactSource -Repository 'yingfan-bot/lotus' -Commit $LotusSourceCommit -Destination $lotusSource
        Ensure-ExactSource -Repository 'CSJianYang/LoopCoder' -Commit $LoopCoderSourceCommit -Destination $loopCoderSource
        $toolPython = Ensure-HuggingFaceTools -VenvRoot (Join-Path $CustodyRoot 'hf-tools-venv')
        Download-ExactSnapshots -ToolPython $toolPython -ModelRoot $ModelRoot
    }

    Assert-ExactSource -Repository 'yingfan-bot/lotus' -Commit $LotusSourceCommit -Destination $lotusSource
    Assert-ExactSource -Repository 'CSJianYang/LoopCoder' -Commit $LoopCoderSourceCommit -Destination $loopCoderSource
    Assert-CheckpointCustody -Root $ModelRoot

    $gpu = Select-LargestNvidiaDevice
    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'probe-hardware'
            Out = $HardwareRoot
            NvidiaSmi = $gpu.NvidiaSmi
            DeviceIndices = ([string]$gpu.Device.Index)
        }

    $hardwareProbeReceiptPath = Join-Path $HardwareRoot 'probe-receipt.json'
    if (-not (Test-Path -LiteralPath $hardwareProbeReceiptPath -PathType Leaf)) {
        throw 'Hardware probe receipt is absent'
    }
    $hardwareProbe = Get-Content -Raw -LiteralPath $hardwareProbeReceiptPath | ConvertFrom-Json
    $selectedDeviceIndices = @($hardwareProbe.selected_device_indices)
    if ($hardwareProbe.schema -ne 'tier-bench/astra-stage2-hardware-probe@2' -or
        $selectedDeviceIndices.Count -ne 1 -or
        [int]$selectedDeviceIndices[0] -ne [int]$gpu.Device.Index) {
        throw 'Hardware probe receipt does not bind the exact selected native device singleton'
    }

    $platformPath = Join-Path $HardwareRoot 'platform.json'
    $deviceQueryPath = Join-Path $HardwareRoot 'nvidia-query.csv'
    $topologyEvidencePath = Join-Path $HardwareRoot 'nvidia-topology.json'
    Assert-FileSha256 -Path $platformPath -Expected $hardwareProbe.platform_sha256 -Label 'Hardware platform evidence'
    Assert-FileSha256 -Path $deviceQueryPath -Expected $hardwareProbe.device_query_sha256 -Label 'Hardware device query'
    Assert-FileSha256 -Path $topologyEvidencePath -Expected $hardwareProbe.topology_evidence_sha256 -Label 'Hardware topology evidence'

    $probePayloadSha256 = Get-CanonicalPayloadSha256 -Path $hardwareProbeReceiptPath
    if ($hardwareProbe.payload_sha256 -ne $probePayloadSha256) {
        throw 'Hardware probe receipt payload digest mismatch'
    }

    $platformEvidence = Get-Content -Raw -LiteralPath $platformPath | ConvertFrom-Json
    $platformSelected = @($platformEvidence.selected_device_indices)
    if ($platformEvidence.schema -ne 'tier-bench/astra-stage2-hardware-platform@1' -or
        $platformSelected.Count -ne 1 -or
        [int]$platformSelected[0] -ne [int]$gpu.Device.Index) {
        throw 'Hardware platform evidence does not bind the exact selected device singleton'
    }
    $platformPayloadSha256 = Get-CanonicalPayloadSha256 -Path $platformPath
    if ($platformEvidence.payload_sha256 -ne $platformPayloadSha256) {
        throw 'Hardware platform evidence payload digest mismatch'
    }

    $topologyEvidence = Get-Content -Raw -LiteralPath $topologyEvidencePath | ConvertFrom-Json
    if ($topologyEvidence.schema -ne 'tier-bench/astra-stage2-topology-evidence@1' -or
        $topologyEvidence.platform -ne $platformEvidence.system -or
        $topologyEvidence.device_query_sha256 -ne $hardwareProbe.device_query_sha256 -or
        $topologyEvidence.implicit_pooling_claimed -ne $false) {
        throw 'Hardware topology evidence failed its common contract'
    }
    $topologyPayloadSha256 = Get-CanonicalPayloadSha256 -Path $topologyEvidencePath
    if ($topologyEvidence.payload_sha256 -ne $topologyPayloadSha256) {
        throw 'Hardware topology evidence payload digest mismatch'
    }

    switch ($topologyEvidence.platform) {
        'Windows' {
            if ($topologyEvidence.state -ne 'NOT_APPLICABLE_SINGLE_SELECTED_DEVICE' -or
                $topologyEvidence.method -ne 'PLATFORM_LIMITATION_SINGLE_DEVICE' -or
                [int]$topologyEvidence.selected_device_index -ne [int]$gpu.Device.Index -or
                $topologyEvidence.inter_device_topology_claimed -ne $false) {
                throw 'Windows topology evidence exceeds single-device platform authority'
            }
        }
        'Linux' {
            $topologySelected = @($topologyEvidence.selected_device_indices)
            if ($topologyEvidence.state -ne 'OBSERVED' -or
                $topologyEvidence.method -ne 'NVIDIA_SMI_TOPO_MATRIX' -or
                $topologySelected.Count -ne 1 -or
                [int]$topologySelected[0] -ne [int]$gpu.Device.Index) {
                throw 'Linux topology evidence is not the observed selected-device matrix'
            }
        }
        default {
            throw "Unsupported topology evidence platform: $($topologyEvidence.platform)"
        }
    }
    $hardwareProbeSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $hardwareProbeReceiptPath).Hash.ToLowerInvariant()

    Write-PreparedConfig -BinderRoot $BinderRoot -LotusSource $lotusSource -LoopCoderSource $loopCoderSource -Models $ModelRoot -HardwareRoot $HardwareRoot -DeviceIndex $gpu.Device.Index -OutputPath $PrivateConfig

    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'inventory'
            Config = $PrivateConfig
            Out = $InventoriedConfig
        }

    if (-not (Test-Path -LiteralPath $InventoriedConfig -PathType Leaf)) {
        throw 'Checkpoint inventory did not emit the inventoried private configuration'
    }

    $preflightSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PreflightReceipt).Hash.ToLowerInvariant()

    $receipt = [ordered]@{
        schema = 'tier-bench/astra-stage2-control-identity-prepare@2'
        state = 'ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND'
        release_head = $LauncherCoordinates.Head
        release_tree = $LauncherCoordinates.Tree
        preflight_receipt_sha256 = $preflightSha256
        hardware_probe_receipt_sha256 = $hardwareProbeSha256
        topology_evidence_sha256 = $hardwareProbe.topology_evidence_sha256
        topology_platform = $topologyEvidence.platform
        topology_state = $topologyEvidence.state
        topology_method = $topologyEvidence.method
        selected_device_indices = @([int]$gpu.Device.Index)
        binder_head = $BinderHead
        binder_tree = $BinderTree
        law_head = $LawHead
        law_blob = $LawBlob
        scaffold_head = $ScaffoldHead
        stage1_join_head = $Stage1Join
        binder_execution_cwd = 'PINNED_BINDER_ROOT'
        binder_pythonpath = 'PINNED_BINDER_ROOT'
        download_mode = $(if ($SkipDownloads) { 'REUSE_EXISTING_EXACT_ASSETS' } else { 'ACQUIRE_OR_VERIFY_EXACT_ASSETS' })
        source_roots = [ordered]@{
            lotus = $lotusSource
            loopcoder = $loopCoderSource
        }
        checkpoint_roots = [ordered]@{
            lotus = Join-Path $ModelRoot $LotusRevision
            loopcoder = Join-Path $ModelRoot $LoopCoderRevision
            conventional = Join-Path $ModelRoot $CotRevision
        }
        selected_gpu = [ordered]@{
            index = $gpu.Device.Index
            name = $gpu.Device.Name
            memory_mib = $gpu.Device.MemoryMiB
        }
        private_config = $PrivateConfig
        inventoried_private_config = $InventoriedConfig
        runtime_identity = 'UNBOUND'
        effort_mapping = 'UNBOUND'
        model_calls = 0
        provider_calls = 0
        empirical_calibration = 'NOT_RUN'
        numeric_stage2_freeze = 'NOT_ISSUED'
    }
    Write-JsonFile -Value $receipt -Path $PrepareReceipt

    Write-Host 'Prepared exact source/checkpoint/hardware custody.'
    Write-Host 'Runtime identity and effort mapping remain UNBOUND.'
    Write-Host "Edit only after deriving truthful runtime semantics: $InventoriedConfig"
    Write-Host 'Then rerun with -Mode Bind.'
    exit 0
}

if (-not (Test-Path -LiteralPath $InventoriedConfig -PathType Leaf)) {
    throw "Inventoried private config is absent: $InventoriedConfig. Run -Mode Prepare first."
}

if ($Mode -eq 'Bind') {
    Assert-BindReady -ConfigPath $InventoriedConfig
    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'validate-config'
            Config = $InventoriedConfig
        }
    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'bind'
            Config = $InventoriedConfig
            RepoRoot = $BinderRoot
            Out = $BoundRoot
        }
    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'verify'
            Config = $InventoriedConfig
            RepoRoot = $BinderRoot
            Out = $BoundRoot
        }
    Write-Host 'Executable identities bound and verified. No model was executed.'
    exit 0
}

if ($Mode -eq 'Verify') {
    Assert-BindReady -ConfigPath $InventoriedConfig
    if (-not (Test-Path -LiteralPath $BoundRoot -PathType Container)) {
        throw "Bound output is absent: $BoundRoot"
    }
    Invoke-PinnedBinder `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'verify'
            Config = $InventoriedConfig
            RepoRoot = $BinderRoot
            Out = $BoundRoot
        }
    Write-Host 'Executable identities verified. No model was executed.'
    exit 0
}

throw "Unsupported mode: $Mode"
