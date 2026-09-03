[CmdletBinding()]
param(
    [ValidateSet('Preflight', 'Prepare', 'Bind', 'Verify')]
    [string]$Mode = 'Prepare',

    [string]$RepoRoot = '',
    [string]$CustodyRoot = 'S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities-real',
    [string]$Python = 'python',
    [switch]$SkipDownloads
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BinderHead = 'af03cef494a509ab7ba5df29fa4b4ccba423f1f8'
$BinderTree = '519ea2f8f448a464e817a024ad8ed1ac64493931'
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
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

function Invoke-BinderCommand {
    param(
        [Parameter(Mandatory = $true)][string]$BinderRoot,
        [Parameter(Mandatory = $true)][string]$Wrapper,
        [Parameter(Mandatory = $true)][hashtable]$Parameters
    )

    $hadPythonPath = Test-Path Env:PYTHONPATH
    $previousPythonPath = $env:PYTHONPATH
    $pathSeparator = [System.IO.Path]::PathSeparator
    $locationPushed = $false

    try {
        if ($previousPythonPath) {
            $env:PYTHONPATH = $BinderRoot + $pathSeparator + $previousPythonPath
        }
        else {
            $env:PYTHONPATH = $BinderRoot
        }

        Push-Location -LiteralPath $BinderRoot
        $locationPushed = $true
        & $Wrapper @Parameters
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $command = $Parameters['Command']
            throw "Binder command failed ($exitCode): $command"
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

function Resolve-TierBenchRepositoryRoot {
    param([string]$RequestedRoot)

    $candidates = @()
    if ($RequestedRoot) {
        $candidates += $RequestedRoot
    }

    # The launcher is committed under <repo>\scripts, so its own worktree is
    # the most reliable default and works for detached Git worktrees.
    $candidates += (Split-Path -Parent $PSScriptRoot)

    # Estate fallbacks. The first is the current canonical checkout.
    $candidates += 'D:\Projects\Measurement\Tier-Bench\main'
    $candidates += 'D:\Projects\Measurement\Tier-Bench'

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        $top = & git -C $candidate rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $top) {
            return $top.Trim()
        }
    }

    throw 'Unable to discover a Tier-Bench Git checkout. Pass -RepoRoot explicitly.'
}

function Get-GitHead {
    param([Parameter(Mandatory = $true)][string]$Root)
    return (& git -C $Root rev-parse HEAD).Trim()
}

function Ensure-ExactSource {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath (Join-Path $Destination '.git'))) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Invoke-Checked git -C $Destination init
        Invoke-Checked git -C $Destination remote add origin ("https://github.com/{0}.git" -f $Repository)
        Invoke-Checked git -C $Destination fetch --no-tags --depth=1 origin $Commit
        Invoke-Checked git -C $Destination checkout --detach FETCH_HEAD
    }

    $head = Get-GitHead -Root $Destination
    if ($head -ne $Commit) {
        throw "Source checkout drift for ${Repository}: expected $Commit, observed $head"
    }

    $dirty = (& git -C $Destination status --porcelain)
    if ($dirty) {
        throw "Source checkout is dirty: $Destination"
    }
}

function Ensure-BinderWorktree {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $top = & git -C $RepositoryRoot rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $top) {
        throw "Tier-Bench repository not found at $RepositoryRoot"
    }

    Invoke-Checked git -C $RepositoryRoot fetch --no-tags origin $BinderHead

    if (-not (Test-Path -LiteralPath $Root)) {
        Invoke-Checked git -C $RepositoryRoot worktree add --detach $Root $BinderHead
    }

    $head = Get-GitHead -Root $Root
    if ($head -ne $BinderHead) {
        throw "Binder worktree must be exact head $BinderHead; observed $head"
    }

    $tree = (& git -C $Root rev-parse 'HEAD^{tree}').Trim()
    if ($tree -ne $BinderTree) {
        throw "Binder tree mismatch: expected $BinderTree, observed $tree"
    }

    if ((& git -C $Root rev-parse "HEAD:docs/agents/claims/FRR-ASTRA-STAGE2-1.md").Trim() -ne $LawBlob) {
        throw 'Released Sol law blob is not present at the pinned binder head'
    }

    if ((& git -C $Root status --porcelain)) {
        throw "Binder worktree is dirty: $Root"
    }
}

function Ensure-HuggingFaceTools {
    param([Parameter(Mandatory = $true)][string]$VenvRoot)

    $venvPython = Join-Path $VenvRoot 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked $Python -m venv $VenvRoot
    }
    Invoke-Checked $venvPython -m pip install --disable-pip-version-check --quiet 'huggingface_hub==0.34.4'
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
    Invoke-Checked $ToolPython $downloadScript $ModelRoot
}

function Select-LargestNvidiaDevice {
    $nvidia = (Get-Command nvidia-smi -ErrorAction Stop).Source
    $rows = & $nvidia --query-gpu=index,name,memory.total --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0 -or -not $rows) {
        throw 'Unable to query NVIDIA devices'
    }

    $parsed = foreach ($line in $rows) {
        $parts = $line -split ',' | ForEach-Object { $_.Trim() }
        [pscustomobject]@{
            Index = [int]$parts[0]
            Name = $parts[1]
            MemoryMiB = [int]$parts[2]
        }
    }

    $selected = $parsed |
        Sort-Object @{Expression='MemoryMiB';Descending=$true}, @{Expression='Index';Descending=$false} |
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
        $control.hardware.topology_path = 'nvidia-topology.txt'
        $control.hardware.selected_device_indices = @($DeviceIndex)
    }

    $json = $config | ConvertTo-Json -Depth 64
    [System.IO.File]::WriteAllText(
        $OutputPath,
        $json + "`n",
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Assert-BindReady {
    param([Parameter(Mandatory = $true)][string]$ConfigPath)

    $raw = Get-Content -Raw -LiteralPath $ConfigPath
    if ($raw -match 'REPLACE') {
        throw 'Runtime identity is still unbound. Replace every REPLACE value before Bind.'
    }

    $config = $raw | ConvertFrom-Json
    foreach ($control in $config.controls) {
        $low = ($control.effort_mapping.low.arguments | ConvertTo-Json -Compress)
        $high = ($control.effort_mapping.high.arguments | ConvertTo-Json -Compress)
        if ($low -eq '["--effort","low"]' -and $high -eq '["--effort","high"]') {
            throw "Effort mapping for $($control.role) is still the non-authoritative template. Bind is refused."
        }
    }
}

$RepoRoot = Resolve-TierBenchRepositoryRoot -RequestedRoot $RepoRoot
New-Item -ItemType Directory -Force -Path $CustodyRoot | Out-Null

$BinderRoot = Join-Path $CustodyRoot ('tier-bench-binder-' + $BinderHead.Substring(0, 8))
$SourceRoot = Join-Path $CustodyRoot 'sources'
$ModelRoot = Join-Path $CustodyRoot 'models'
$HardwareRoot = Join-Path $CustodyRoot 'hardware'
$PrivateConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.private.json'
$InventoriedConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.inventoried.private.json'
$BoundRoot = Join-Path $CustodyRoot 'bound'
$PrepareReceipt = Join-Path $CustodyRoot 'PREPARE-RECEIPT.json'
$PreflightReceipt = Join-Path $CustodyRoot 'PREFLIGHT-RECEIPT.json'
$PreflightBinderProbe = Join-Path $CustodyRoot 'PREFLIGHT-BINDER-TEMPLATE.json'

Ensure-BinderWorktree -RepositoryRoot $RepoRoot -Root $BinderRoot
$wrapper = Join-Path $BinderRoot 'scripts\astra_stage2_bind_controls.ps1'
if (-not (Test-Path -LiteralPath $wrapper)) {
    throw "Binder wrapper is missing at $wrapper"
}

if ($Mode -eq 'Preflight') {
    $callerWorkingDirectory = (Get-Location).Path
    if (Test-Path -LiteralPath $PreflightBinderProbe) {
        Remove-Item -Force -LiteralPath $PreflightBinderProbe
    }

    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'template'
            Out = $PreflightBinderProbe
        }

    if (-not (Test-Path -LiteralPath $PreflightBinderProbe)) {
        throw 'Binder import probe did not create its template output.'
    }

    $probe = Get-Content -Raw -LiteralPath $PreflightBinderProbe | ConvertFrom-Json
    if ($probe.law.blob_sha1 -ne $LawBlob) {
        throw 'Binder import probe resolved a package with the wrong law blob.'
    }
    if ($probe.scaffold.head_sha1 -ne $ScaffoldHead) {
        throw 'Binder import probe resolved a package with the wrong scaffold head.'
    }
    if ($probe.stage1_join_head -ne $Stage1Join) {
        throw 'Binder import probe resolved a package with the wrong Stage 1 join.'
    }
    if (@($probe.controls).Count -ne 3) {
        throw 'Binder import probe did not expose exactly three controls.'
    }

    $probeSha256 = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $PreflightBinderProbe
    ).Hash.ToLowerInvariant()

    $receipt = [ordered]@{
        schema = 'tier-bench/astra-stage2-control-identity-preflight@2'
        state = 'PREFLIGHT_PASS'
        release_repository_root = $RepoRoot
        caller_working_directory = $callerWorkingDirectory
        binder_root = $BinderRoot
        binder_head = $BinderHead
        binder_tree = $BinderTree
        law_head = $LawHead
        law_blob = $LawBlob
        scaffold_head = $ScaffoldHead
        stage1_join_head = $Stage1Join
        binder_command_import_probe = 'PASS'
        binder_command = 'template'
        binder_command_working_directory = $BinderRoot
        binder_pythonpath_root = $BinderRoot
        binder_template_probe = $PreflightBinderProbe
        binder_template_probe_sha256 = $probeSha256
        downloads_performed = $false
        model_calls = 0
        provider_calls = 0
        actual_executable_control_identities = 'UNBOUND'
        empirical_calibration = 'NOT_RUN'
        numeric_stage2_freeze = 'NOT_ISSUED'
    }
    $receipt | ConvertTo-Json -Depth 16 | Set-Content -Encoding utf8 $PreflightReceipt
    Write-Host 'PREFLIGHT_PASS'
    Write-Host "Repository root: $RepoRoot"
    Write-Host "Binder worktree: $BinderRoot"
    Write-Host "Binder import probe: $PreflightBinderProbe"
    exit 0
}

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

    if (-not (Test-Path -LiteralPath $lotusSource) -or -not (Test-Path -LiteralPath $loopCoderSource)) {
        throw 'Exact source checkouts are absent. Prepare cannot continue.'
    }

    foreach ($revision in @($LotusRevision, $LoopCoderRevision, $CotRevision)) {
        if (-not (Test-Path -LiteralPath (Join-Path $ModelRoot $revision))) {
            throw "Checkpoint snapshot is absent: $revision"
        }
    }

    $gpu = Select-LargestNvidiaDevice
    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'probe-hardware'
            Out = $HardwareRoot
            NvidiaSmi = $gpu.NvidiaSmi
            DeviceIndices = [string]$gpu.Device.Index
        }

    Write-PreparedConfig `
        -BinderRoot $BinderRoot `
        -LotusSource $lotusSource `
        -LoopCoderSource $loopCoderSource `
        -Models $ModelRoot `
        -HardwareRoot $HardwareRoot `
        -DeviceIndex $gpu.Device.Index `
        -OutputPath $PrivateConfig

    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'inventory'
            Config = $PrivateConfig
            Out = $InventoriedConfig
        }

    $receipt = [ordered]@{
        schema = 'tier-bench/astra-stage2-control-identity-prepare@1'
        state = 'ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND'
        release_repository_root = $RepoRoot
        binder_head = $BinderHead
        binder_tree = $BinderTree
        law_head = $LawHead
        law_blob = $LawBlob
        scaffold_head = $ScaffoldHead
        stage1_join_head = $Stage1Join
        source_roots = [ordered]@{
            lotus = $lotusSource
            loopcoder = $loopCoderSource
        }
        checkpoint_roots = [ordered]@{
            lotus = (Join-Path $ModelRoot $LotusRevision)
            loopcoder = (Join-Path $ModelRoot $LoopCoderRevision)
            conventional = (Join-Path $ModelRoot $CotRevision)
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
    $receipt | ConvertTo-Json -Depth 16 | Set-Content -Encoding utf8 $PrepareReceipt
    Write-Host 'Prepared exact source/checkpoint/hardware custody. Runtime and effort mapping remain UNBOUND.'
    Write-Host "Edit: $InventoriedConfig"
    Write-Host 'Then rerun with -Mode Bind.'
    exit 0
}

if (-not (Test-Path -LiteralPath $InventoriedConfig)) {
    throw "Inventoried private config is absent: $InventoriedConfig. Run -Mode Prepare first."
}

if ($Mode -eq 'Bind') {
    Assert-BindReady -ConfigPath $InventoriedConfig
    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'validate-config'
            Config = $InventoriedConfig
        }
    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'bind'
            Config = $InventoriedConfig
            RepoRoot = $BinderRoot
            Out = $BoundRoot
        }
    Invoke-BinderCommand `
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
    if (-not (Test-Path -LiteralPath $BoundRoot)) {
        throw "Bound output is absent: $BoundRoot"
    }
    Invoke-BinderCommand `
        -BinderRoot $BinderRoot `
        -Wrapper $wrapper `
        -Parameters @{
            Command = 'verify'
            Config = $InventoriedConfig
            RepoRoot = $BinderRoot
            Out = $BoundRoot
        }
    Write-Host 'Executable identities reproduce from current local bytes.'
    exit 0
}
