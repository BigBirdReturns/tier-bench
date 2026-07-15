param(
    [string]$Scratch = (Join-Path $env:TEMP ("cart0-profile-1-portable-" + [guid]::NewGuid().ToString("N"))),
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$expectedCommit = "a30ca1a3509b11cae601e2fd5968440c9133a9ab"
$historicalB0Commit = "133fdf14177e3fded0250a7953f8ac1ed941df4c"
$bundle = Join-Path $PSScriptRoot "repository.bundle"
$treeZip = Join-Path $PSScriptRoot "tested-tree.zip"
$sums = Join-Path $PSScriptRoot "SHA256SUMS"

if (Test-Path -LiteralPath $Scratch) {
    throw "Scratch path already exists; verifier only extracts into a new directory: $Scratch"
}
New-Item -ItemType Directory -Path $Scratch | Out-Null

foreach ($line in Get-Content -LiteralPath $sums) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split "  ", 2
    if ($parts.Count -ne 2) { throw "Malformed SHA256SUMS line: $line" }
    $path = Join-Path $PSScriptRoot $parts[1]
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $parts[0]) { throw "SHA-256 mismatch for $($parts[1])" }
}

$repo = Join-Path $Scratch "r"
& git clone --no-checkout --no-local $bundle $repo
if ($LASTEXITCODE -ne 0) { throw "git clone from bundle failed" }
& git -C $repo bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw "git bundle verify failed" }
& git -C $repo config core.longpaths true
& git -C $repo checkout --detach $expectedCommit
if ($LASTEXITCODE -ne 0) { throw "tested commit checkout failed" }
if ((& git -C $repo rev-parse HEAD).Trim() -ne $expectedCommit) { throw "tested commit mismatch" }

$tree = Join-Path $Scratch "t"
Expand-Archive -LiteralPath $treeZip -DestinationPath $tree
$tracked = @(& git -C $repo ls-tree -r --name-only $expectedCommit)
$treeFiles = @(Get-ChildItem -LiteralPath $tree -Recurse -File)
if ($tracked.Count -ne $treeFiles.Count) { throw "tested-tree file count mismatch" }
foreach ($relative in $tracked) {
    $left = Join-Path $repo $relative
    $right = Join-Path $tree $relative
    if (-not (Test-Path -LiteralPath $right -PathType Leaf)) { throw "tested-tree missing $relative" }
    $a = (Get-FileHash -LiteralPath $left -Algorithm SHA256).Hash
    $b = (Get-FileHash -LiteralPath $right -Algorithm SHA256).Hash
    if ($a -ne $b) { throw "tested-tree mismatch: $relative" }
}

Push-Location $repo
try {
    & $Python -m py_compile scripts/cart0_anchor.py experiments/cart0_anchor_prototype/run_profile_conformance.py tests/test_cart0_anchor.py tests/test_cart0_catalog_attack_receipt.py
    if ($LASTEXITCODE -ne 0) { throw "py_compile failed" }
    & $Python tests/test_cart0_anchor.py
    if ($LASTEXITCODE -ne 0) { throw "test_cart0_anchor.py failed" }
    & $Python tests/test_cart0_catalog_attack_receipt.py
    if ($LASTEXITCODE -ne 0) { throw "test_cart0_catalog_attack_receipt.py failed" }
    & $Python experiments/cart0_anchor_prototype/run_profile_conformance.py --out (Join-Path $Scratch "c")
    if ($LASTEXITCODE -ne 0) { throw "fresh profile conformance failed" }
    & $Python scripts/cart0_anchor.py verify --repo . --bundle experiments/cart0_anchor_prototype/run_profile_b0_remediation_20260714/bundle
    if ($LASTEXITCODE -ne 0) { throw "remediated B0 verification failed" }
} finally {
    Pop-Location
}

$historical = Join-Path $Scratch "h"
& git clone --no-checkout --no-local $bundle $historical
if ($LASTEXITCODE -ne 0) { throw "historical clone failed" }
& git -C $historical config core.longpaths true
& git -C $historical checkout --detach $historicalB0Commit
if ($LASTEXITCODE -ne 0) { throw "historical B0 checkout failed" }
Push-Location $historical
try {
    & $Python scripts/cart0_anchor.py verify --repo . --bundle experiments/cart0_anchor_prototype/run_profile_b0_20260714/bundle
    if ($LASTEXITCODE -ne 0) { throw "preserved historical B0 verification failed" }
} finally {
    Pop-Location
}

Write-Output "PORTABLE_CART0_PROFILE_1_VERIFIED"
Write-Output "TESTED_COMMIT $expectedCommit"
Write-Output "PRESERVED_B0_COMMIT $historicalB0Commit"
Write-Output "SCRATCH $Scratch"
