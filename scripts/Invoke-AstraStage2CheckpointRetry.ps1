[CmdletBinding(PositionalBinding = $false)]
param(
    [ValidateSet('Retry', 'CheckDigest')][string]$Command = 'Retry',
    [string]$Path,
    [string]$ExpectedSha256,
    [string]$RepoRoot = 'D:\Projects\Measurement\Tier-Bench\main',
    [string]$Worktree,
    [string]$CustodyRoot = 'S:\Scratch\Incoming\Tier-Bench\astra-stage2-control-identities-real',
    [string]$TemporaryRoot = 'S:\Scratch\Temp\Tier-Bench',
    [string]$Python = 'python',
    [string]$CheckpointBranch,
    [string]$ExpectedHead,
    [string]$ExpectedTree,
    [string]$ExpectedLauncherSha256,
    [string]$ExpectedTemplateSha256,
    [string]$BinderHead,
    [string]$BinderTree
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LotusSourceCommit = 'eb77e2f7909c5006f58ff0ad7cd6629b942caa9e'
$LoopCoderSourceCommit = 'ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c'
$CheckpointRevisions = @(
    'b392d2cb7aaa73475b93028221523c47f49f66a2',
    'b87cf3aa2186937b0d0362a684d7d30f234543e3',
    '63de1ec1902ed143fe62250b6ddb14cb65f06e1a'
)

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Digest target is absent: $LiteralPath"
    }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Assert-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    if ($Expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw 'Expected SHA-256 must contain exactly 64 hexadecimal characters'
    }
    $observed = Get-Sha256 -LiteralPath $LiteralPath
    if (($observed) -ne $Expected.ToLowerInvariant()) {
        throw "Digest mismatch: expected $($Expected.ToLowerInvariant()), observed $observed"
    }
    return $observed
}

if ($Command -eq 'CheckDigest') {
    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        throw 'CheckDigest requires -Path and -ExpectedSha256'
    }
    $digest = Assert-Sha256 -LiteralPath $Path -Expected $ExpectedSha256
    Write-Output "DIGEST_MATCH $digest"
    exit 0
}

function Assert-RequiredValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Value,
        [string]$Pattern = '.+'
    )
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -notmatch $Pattern) {
        throw "Retry requires a valid -$($Name)"
    }
}

Assert-RequiredValue -Name 'CheckpointBranch' -Value $CheckpointBranch
Assert-RequiredValue -Name 'ExpectedHead' -Value $ExpectedHead -Pattern '^[0-9a-f]{40}$'
Assert-RequiredValue -Name 'ExpectedTree' -Value $ExpectedTree -Pattern '^[0-9a-f]{40}$'
Assert-RequiredValue -Name 'ExpectedLauncherSha256' -Value $ExpectedLauncherSha256 -Pattern '^[0-9a-f]{64}$'
Assert-RequiredValue -Name 'ExpectedTemplateSha256' -Value $ExpectedTemplateSha256 -Pattern '^[0-9a-f]{64}$'
Assert-RequiredValue -Name 'BinderHead' -Value $BinderHead -Pattern '^[0-9a-f]{40}$'
Assert-RequiredValue -Name 'BinderTree' -Value $BinderTree -Pattern '^[0-9a-f]{40}$'
Assert-RequiredValue -Name 'Worktree' -Value $Worktree

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed ($LASTEXITCODE): $($Arguments -join ' ')"
    }
}

function Assert-CleanSource {
    param([string]$Root, [string]$Commit, [string]$Label)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Missing $($Label): $Root"
    }
    $head = (& git -C $Root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $Commit) {
        throw "$($Label) head mismatch: $head"
    }
    if (& git -C $Root status --porcelain) {
        throw "$($Label) is dirty: $Root"
    }
}

$checkpointRef = 'refs/astra-stage2/checkpoint-retry'
$refspec = '+refs/heads/{0}:{1}' -f $CheckpointBranch, $checkpointRef
Invoke-Git -C $RepoRoot fetch --no-tags origin $refspec
$fetchedHead = (& git -C $RepoRoot rev-parse $checkpointRef).Trim()
if ($fetchedHead -ne $ExpectedHead) {
    throw "Checkpoint drift: expected $ExpectedHead, observed $fetchedHead"
}
$treeExpression = '{0}^{{tree}}' -f $ExpectedHead
$fetchedTree = (& git -C $RepoRoot rev-parse $treeExpression).Trim()
if ($fetchedTree -ne $ExpectedTree) {
    throw "Checkpoint tree mismatch: expected $ExpectedTree, observed $fetchedTree"
}

if (-not (Test-Path -LiteralPath $Worktree)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Worktree) | Out-Null
    Invoke-Git -C $RepoRoot worktree add --detach $Worktree $ExpectedHead
}
else {
    if (& git -C $Worktree status --porcelain) {
        throw "Retained worktree is dirty: $Worktree"
    }
    Invoke-Git -C $Worktree checkout --detach $ExpectedHead
}
if ((& git -C $Worktree rev-parse HEAD).Trim() -ne $ExpectedHead) {
    throw 'Worktree head mismatch'
}
if ((& git -C $Worktree rev-parse 'HEAD^{tree}').Trim() -ne $ExpectedTree) {
    throw 'Worktree tree mismatch'
}
$binderTreeExpression = '{0}^{{tree}}' -f $BinderHead
if ((& git -C $Worktree rev-parse $binderTreeExpression).Trim() -ne $BinderTree) {
    throw 'Binder tree mismatch'
}
& git -C $Worktree merge-base --is-ancestor $BinderHead $ExpectedHead
if ($LASTEXITCODE -ne 0) {
    throw 'Release is not descended from the pinned binder'
}

$launcherRelative = 'scripts/Invoke-AstraStage2ControlIdentityBinding.ps1'
$launcher = Join-Path $Worktree $launcherRelative
$attribute = (& git -C $Worktree check-attr eol -- $launcherRelative).Trim()
if ($LASTEXITCODE -ne 0 -or $attribute -notmatch ': eol: lf$') {
    throw "Launcher LF materialization rule is absent: $attribute"
}
$null = Assert-Sha256 -LiteralPath $launcher -Expected $ExpectedLauncherSha256

$sourceRoot = Join-Path $CustodyRoot 'sources'
$modelRoot = Join-Path $CustodyRoot 'models'
Assert-CleanSource -Root (Join-Path $sourceRoot ('lotus-' + $LotusSourceCommit)) -Commit $LotusSourceCommit -Label 'LOTUS source'
Assert-CleanSource -Root (Join-Path $sourceRoot ('loopcoder-' + $LoopCoderSourceCommit)) -Commit $LoopCoderSourceCommit -Label 'LoopCoder source'
foreach ($revision in $CheckpointRevisions) {
    $checkpointPath = Join-Path $modelRoot $revision
    if (-not (Test-Path -LiteralPath $checkpointPath -PathType Container)) {
        throw "Missing checkpoint: $checkpointPath"
    }
    if (@(Get-ChildItem -LiteralPath $checkpointPath -Recurse -File).Count -eq 0) {
        throw "Empty checkpoint: $checkpointPath"
    }
}
if (@(Get-ChildItem -LiteralPath $CustodyRoot -Recurse -File -Filter '*.incomplete' -ErrorAction SilentlyContinue).Count -ne 0) {
    throw 'Incomplete download files remain'
}

$historyLabel = 'before-' + $ExpectedHead.Substring(0, 7) + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$history = Join-Path $CustodyRoot ('history\' + $historyLabel)
New-Item -ItemType Directory -Force -Path $history | Out-Null
$artifactNames = @(
    'PREFLIGHT-RECEIPT.json',
    'PREPARE-RECEIPT.json',
    'astra-stage2-control-identities.private.json',
    'astra-stage2-control-identities.inventoried.private.json'
)
foreach ($name in $artifactNames) {
    $source = Join-Path $CustodyRoot $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $history $name)
    }
}

New-Item -ItemType Directory -Force -Path $TemporaryRoot | Out-Null
$temporaryRootPath = (Resolve-Path -LiteralPath $TemporaryRoot).ProviderPath
$caller = Join-Path $temporaryRootPath ('astra-checkpoint-preflight-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $caller | Out-Null
$callerPath = (Resolve-Path -LiteralPath $caller).ProviderPath
$requiredPrefix = $temporaryRootPath.TrimEnd('\') + '\'
if (-not $callerPath.StartsWith($requiredPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary caller escaped its declared root: $callerPath"
}

$preflightArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher,
    '-Mode', 'Preflight', '-RepoRoot', $RepoRoot,
    '-CustodyRoot', $CustodyRoot, '-Python', $Python
)
Push-Location $callerPath
try {
    & powershell.exe @preflightArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight failed: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $callerPath -PathType Container) {
        Remove-Item -LiteralPath $callerPath -Recurse -Force
    }
}

$preflightPath = Join-Path $CustodyRoot 'PREFLIGHT-RECEIPT.json'
$preflight = Get-Content -Raw -LiteralPath $preflightPath | ConvertFrom-Json
if ($preflight.schema -ne 'tier-bench/astra-stage2-control-identity-preflight@2') {
    throw 'Preflight schema mismatch'
}
if ($preflight.state -ne 'PREFLIGHT_PASS') {
    throw 'Preflight did not pass'
}
if ($preflight.release_head -ne $ExpectedHead -or $preflight.release_tree -ne $ExpectedTree) {
    throw 'Preflight release coordinate mismatch'
}
if ($preflight.binder_head -ne $BinderHead -or $preflight.binder_tree -ne $BinderTree) {
    throw 'Preflight binder coordinate mismatch'
}
if ($preflight.binder_import_smoke -ne 'PASS' -or
    $preflight.binder_execution_cwd -ne 'PINNED_BINDER_ROOT' -or
    $preflight.binder_pythonpath -ne 'PINNED_BINDER_ROOT' -or
    $preflight.binder_caller_cwd -ne 'DELIBERATELY_NON_BINDER') {
    throw 'Binder import boundary not proven'
}
if ($preflight.binder_template_sha256 -ne $ExpectedTemplateSha256) {
    throw 'Template hash mismatch'
}
if ($preflight.downloads_performed -ne $false -or
    $preflight.model_calls -ne 0 -or
    $preflight.provider_calls -ne 0 -or
    $preflight.actual_executable_control_identities -ne 'UNBOUND') {
    throw 'Preflight widened authority'
}
$preflightSha256 = Get-Sha256 -LiteralPath $preflightPath

$prepareArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher,
    '-Mode', 'Prepare', '-RepoRoot', $RepoRoot,
    '-CustodyRoot', $CustodyRoot, '-Python', $Python, '-SkipDownloads'
)
& powershell.exe @prepareArgs
if ($LASTEXITCODE -ne 0) {
    throw "Prepare -SkipDownloads failed: $LASTEXITCODE"
}

$preparePath = Join-Path $CustodyRoot 'PREPARE-RECEIPT.json'
$privateConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.private.json'
$inventoriedConfig = Join-Path $CustodyRoot 'astra-stage2-control-identities.inventoried.private.json'
foreach ($requiredPath in @($preflightPath, $preparePath, $privateConfig, $inventoriedConfig)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Missing Prepare output: $requiredPath"
    }
}

$prepare = Get-Content -Raw -LiteralPath $preparePath | ConvertFrom-Json
if ($prepare.schema -ne 'tier-bench/astra-stage2-control-identity-prepare@2') {
    throw 'Prepare schema mismatch'
}
if ($prepare.state -ne 'ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND') {
    throw "Prepare state mismatch: $($prepare.state)"
}
if ($prepare.release_head -ne $ExpectedHead -or $prepare.release_tree -ne $ExpectedTree) {
    throw 'Prepare release coordinate mismatch'
}
if ($prepare.preflight_receipt_sha256 -ne $preflightSha256) {
    throw 'Prepare did not bind the current Preflight receipt'
}
if ($prepare.download_mode -ne 'REUSE_EXISTING_EXACT_ASSETS') {
    throw 'Prepare did not reuse preserved assets'
}
if ($prepare.runtime_identity -ne 'UNBOUND' -or
    $prepare.effort_mapping -ne 'UNBOUND' -or
    $prepare.model_calls -ne 0 -or
    $prepare.provider_calls -ne 0 -or
    $prepare.empirical_calibration -ne 'NOT_RUN' -or
    $prepare.numeric_stage2_freeze -ne 'NOT_ISSUED') {
    throw 'Prepare widened authority'
}

Write-Host ''
Write-Host 'PREPARE_COMPLETE_UNBOUND'
Write-Host "Release head:      $ExpectedHead"
Write-Host "Release tree:      $ExpectedTree"
Write-Host "Preflight SHA-256: $preflightSha256"
Write-Host "Prepare SHA-256:   $(Get-Sha256 -LiteralPath $preparePath)"
Write-Host "History archive:   $history"
Write-Host ''
Write-Host 'STOP. Do not run Bind.'

