[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TierBenchRoot,
    [Parameter(Mandatory = $true)][string]$GradientRoot,
    [Parameter(Mandatory = $true)][string]$EstateReceipt,
    [Parameter(Mandatory = $true)][string]$EstateObservation,
    [Parameter(Mandatory = $true)][string]$ControlHostObservation,
    [string]$OutRoot = (Join-Path $env:LOCALAPPDATA "AXM\anchor-crate-4060-smoke"),
    [string]$Model = "qwen3.5:9b-q4_K_M",
    [string]$Endpoint = "http://127.0.0.1:11442",
    [string]$BackendId = "backend.cuda4060-qwen35-physical",
    [string]$GpuUuid = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-FileStrict {
    param([string]$Path, [string]$Label)
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$Label is not a file: $Path" }
    return $resolved.Path
}

function Resolve-DirectoryStrict {
    param([string]$Path, [string]$Label)
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) { throw "$Label is not a directory: $Path" }
    return $resolved.Path
}

function Read-JsonStrict {
    param([string]$Path)
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Utf8NoBomJson {
    param([string]$Path, $Value)
    $json = $Value | ConvertTo-Json -Depth 32
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $json + "`n", $utf8)
}

function Invoke-JsonCommand {
    param([string]$Python, [string[]]$Arguments, [string]$Label)
    $text = (& $Python @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit $LASTEXITCODE`n$text" }
    try { return $text | ConvertFrom-Json } catch { throw "$Label returned invalid JSON`n$text" }
}

function Wait-Ollama {
    param([string]$BaseUrl, [int]$TimeoutSeconds = 45)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            return Invoke-RestMethod -Method Get -Uri ($BaseUrl.TrimEnd('/') + "/api/version") -TimeoutSec 3
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "dedicated Ollama server did not become ready at $BaseUrl"
}

function Get-ReceiptArtifact {
    param($Receipt, [string]$ReceiptPath, [string]$Suffix)
    $root = Split-Path -Parent $ReceiptPath
    $matches = @($Receipt.artifacts | Where-Object { $_.path -eq $Suffix -or $_.path.EndsWith("/$Suffix") })
    if ($matches.Count -ne 1) { throw "expected one receipt artifact ending in $Suffix, found $($matches.Count)" }
    $path = Join-Path $root $matches[0].path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "receipt artifact missing: $path" }
    $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($digest -ne ([string]$matches[0].sha256).ToLowerInvariant()) { throw "receipt artifact digest mismatch: $path" }
    return (Resolve-Path -LiteralPath $path).Path
}

function Parse-NvidiaRow {
    param([string]$Line)
    $parts = @($Line -split ',' | ForEach-Object { $_.Trim() })
    if ($parts.Count -lt 9) { throw "nvidia-smi returned an incomplete GPU row: $Line" }
    return [ordered]@{
        uuid = $parts[0]
        name = $parts[1]
        memory_total_mib = [int64]$parts[2]
        memory_used_mib = [int64]$parts[3]
        driver_version = $parts[4]
        pci_bus_id = $parts[5]
        pstate = $parts[6]
        power_limit_watts = [double]$parts[7]
        power_draw_watts = if ($parts[8] -match '^[0-9.]+$') { [double]$parts[8] } else { $null }
    }
}

$TierBenchRoot = Resolve-DirectoryStrict $TierBenchRoot "Tier Bench root"
$GradientRoot = Resolve-DirectoryStrict $GradientRoot "Home Lab Gradient root"
$EstateReceipt = Resolve-FileStrict $EstateReceipt "estate receipt"
$EstateObservation = Resolve-FileStrict $EstateObservation "estate observation"
$ControlHostObservation = Resolve-FileStrict $ControlHostObservation "control-host observation"
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
if (Test-Path -LiteralPath $OutRoot) { throw "output root already exists: $OutRoot" }
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null

$estateReceiptObject = Read-JsonStrict $EstateReceipt
if ($estateReceiptObject.status -ne "PASS" -or $estateReceiptObject.experiment_id -ne "capture-estate-snapshot") {
    throw "the three-host estate receipt is not a PASS capture-estate-snapshot receipt"
}
$coveredEstateObservation = Get-ReceiptArtifact $estateReceiptObject $EstateReceipt "estate-observation.json"
$coveredControlObservation = Get-ReceiptArtifact $estateReceiptObject $EstateReceipt "inputs/control-host.json"
if ($coveredEstateObservation -ne $EstateObservation -or $coveredControlObservation -ne $ControlHostObservation) {
    throw "the supplied estate inputs are not the exact artifacts covered by the census receipt"
}
$estateSourceRoot = Split-Path -Parent $EstateReceipt
$estateEvidenceRoot = Join-Path $OutRoot "estate-census"
Copy-Item -LiteralPath $estateSourceRoot -Destination $estateEvidenceRoot -Recurse
$EstateReceipt = Join-Path $estateEvidenceRoot (Split-Path -Leaf $EstateReceipt)
$EstateObservation = Join-Path $estateEvidenceRoot "estate-observation.json"
$ControlHostObservation = Join-Path $estateEvidenceRoot "inputs\control-host.json"
$estateReceiptObject = Read-JsonStrict $EstateReceipt
$estateObject = Read-JsonStrict $EstateObservation
if ($estateObject.host_count_observed -ne 3 -or $estateObject.accelerator_domains_resolved -ne $estateObject.accelerator_domains_expected) {
    throw "the estate observation does not close the three-host accelerator census"
}
$control = Read-JsonStrict $ControlHostObservation
if ($control.host_id -ne "control-host") { throw "control-host observation has the wrong host_id" }

$runtimes = @{}
foreach ($row in @($control.runtime)) { $runtimes[[string]$row.name] = $row }
foreach ($name in @("python", "ollama", "nvidia-smi")) {
    if (-not $runtimes.ContainsKey($name) -or -not $runtimes[$name].present -or $runtimes[$name].disabled) {
        throw "required runtime is not enabled in the census: $name"
    }
}
$python = Resolve-FileStrict ([string]$runtimes["python"].path) "Python runtime"
$ollama = Resolve-FileStrict ([string]$runtimes["ollama"].path) "Ollama runtime"
$nvidiaSmi = Resolve-FileStrict ([string]$runtimes["nvidia-smi"].path) "nvidia-smi runtime"

$gpuCandidates = @($control.graphics.nvidia | Where-Object {
    ([string]$_.name).ToUpperInvariant().Contains("RTX 4060") -and ((-not $GpuUuid) -or $_.uuid -eq $GpuUuid)
})
if ($gpuCandidates.Count -ne 1) { throw "expected one exact RTX 4060 in the control-host census, found $($gpuCandidates.Count)" }
$gpu = $gpuCandidates[0]
$GpuUuid = [string]$gpu.uuid

try {
    Invoke-RestMethod -Method Get -Uri ($Endpoint.TrimEnd('/') + "/api/version") -TimeoutSec 2 | Out-Null
    throw "the dedicated Ollama endpoint is already occupied: $Endpoint"
} catch {
    if ($_.Exception.Message -like "the dedicated Ollama endpoint is already occupied*") { throw }
}

$endpointUri = [Uri]$Endpoint
if ($endpointUri.Scheme -ne "http" -or $endpointUri.Host -notin @("127.0.0.1", "localhost", "::1")) {
    throw "physical smoke requires a loopback HTTP endpoint"
}
$ollamaHost = if ($endpointUri.IsDefaultPort) { $endpointUri.Host } else { "$($endpointUri.Host):$($endpointUri.Port)" }

$oldHost = $env:OLLAMA_HOST
$oldCuda = $env:CUDA_VISIBLE_DEVICES
$oldKeepAlive = $env:OLLAMA_KEEP_ALIVE
$server = $null
try {
    $env:OLLAMA_HOST = $ollamaHost
    $env:CUDA_VISIBLE_DEVICES = $GpuUuid
    $env:OLLAMA_KEEP_ALIVE = "10m"
    $server = Start-Process -FilePath $ollama -ArgumentList @("serve") -PassThru -WindowStyle Hidden
} finally {
    $env:OLLAMA_HOST = $oldHost
    $env:CUDA_VISIBLE_DEVICES = $oldCuda
    $env:OLLAMA_KEEP_ALIVE = $oldKeepAlive
}

try {
    $version = Wait-Ollama -BaseUrl $Endpoint
    $stamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    $gradientState = Join-Path $OutRoot "gradient-state"
    $functionDir = Join-Path $gradientState "functions\qwen-4060-readiness"
    Invoke-JsonCommand $python @(
        (Join-Path $GradientRoot "scripts\lab.py"),
        "--state-dir", $gradientState,
        "init"
    ) "gradient state initialization" | Out-Null
    $scaffold = Invoke-JsonCommand $python @(
        (Join-Path $GradientRoot "scripts\lab.py"),
        "--state-dir", $gradientState,
        "scaffold-function",
        "--id", "qwen-4060-readiness",
        "--model", $Model,
        "--host", $Endpoint,
        "--output", $functionDir
    ) "Qwen function scaffold"
    $qualified = Invoke-JsonCommand $python @(
        (Join-Path $GradientRoot "scripts\lab.py"),
        "--state-dir", $gradientState,
        "qualify-function",
        "--contract", ([string]$scaffold.contract),
        "--fixture", ([string]$scaffold.fixture),
        "--now", $stamp
    ) "Qwen function qualification"
    if (-not $qualified.ok -or $qualified.status -ne "PASS") { throw "Qwen function qualification did not pass" }
    $functionReceipt = Resolve-FileStrict ([string]$qualified.receipt) "function qualification receipt"
    $functionReceiptObject = Read-JsonStrict $functionReceipt
    $attemptOne = Read-JsonStrict (Get-ReceiptArtifact $functionReceiptObject $functionReceipt "attempt-1/output.json")
    $attemptTwo = Read-JsonStrict (Get-ReceiptArtifact $functionReceiptObject $functionReceipt "attempt-2/output.json")
    if ($attemptOne.model_digest -ne $attemptTwo.model_digest -or -not $attemptOne.model_digest) {
        throw "function qualification did not retain one exact model digest"
    }
    $modelDigest = [string]$attemptOne.model_digest

    $tags = Invoke-RestMethod -Method Get -Uri ($Endpoint.TrimEnd('/') + "/api/tags") -TimeoutSec 10
    $loaded = Invoke-RestMethod -Method Get -Uri ($Endpoint.TrimEnd('/') + "/api/ps") -TimeoutSec 10
    $showBody = @{ model = $Model } | ConvertTo-Json -Compress
    $show = Invoke-RestMethod -Method Post -Uri ($Endpoint.TrimEnd('/') + "/api/show") -ContentType "application/json" -Body $showBody -TimeoutSec 20
    $catalogModel = @($tags.models | Where-Object { ($_.name -eq $Model -or $_.model -eq $Model) -and $_.digest -eq $modelDigest })
    $loadedModel = @($loaded.models | Where-Object { ($_.name -eq $Model -or $_.model -eq $Model) -and $_.digest -eq $modelDigest })
    if ($catalogModel.Count -ne 1) { throw "exact model digest not found in the dedicated Ollama catalog" }
    if ($loadedModel.Count -ne 1) { throw "exact model digest not resident in the dedicated Ollama server" }

    $query = "uuid,name,memory.total,memory.used,driver_version,pci.bus_id,pstate,power.limit,power.draw"
    $gpuLine = (& $nvidiaSmi -i $GpuUuid "--query-gpu=$query" "--format=csv,noheader,nounits" 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi GPU query failed" }
    $gpuLive = Parse-NvidiaRow $gpuLine
    $processRows = @()
    try {
        $rawProcesses = @(& $nvidiaSmi "--query-compute-apps=gpu_uuid,pid,process_name,used_memory" "--format=csv,noheader,nounits" 2>$null)
        foreach ($line in $rawProcesses) {
            if (-not $line) { continue }
            $parts = @($line -split ',' | ForEach-Object { $_.Trim() })
            if ($parts.Count -ge 4) {
                $processRows += [ordered]@{ gpu_uuid = $parts[0]; pid = $parts[1]; process_name = $parts[2]; used_memory_mib = $parts[3] }
            }
        }
    } catch { $processRows = @() }

    $checks = @(
        [ordered]@{ id = "three-host-census-pass"; pass = $true; detail = [string]$estateReceiptObject.receipt_sha256 },
        [ordered]@{ id = "dedicated-loopback-server"; pass = ($server -and -not $server.HasExited); detail = "pid=$($server.Id) endpoint=$Endpoint" },
        [ordered]@{ id = "cuda-visible-device-bound"; pass = ($GpuUuid -eq [string]$gpuLive.uuid); detail = $GpuUuid },
        [ordered]@{ id = "exact-model-digest"; pass = ($catalogModel.Count -eq 1 -and $loadedModel.Count -eq 1); detail = $modelDigest },
        [ordered]@{ id = "ollama-vram-residency"; pass = ([int64]$loadedModel[0].size_vram -ge 2147483648); detail = [string]$loadedModel[0].size_vram },
        [ordered]@{ id = "nvidia-memory-residency"; pass = ([int64]$gpuLive.memory_used_mib -ge 1024); detail = [string]$gpuLive.memory_used_mib },
        [ordered]@{ id = "function-replay-pass"; pass = ($qualified.status -eq "PASS"); detail = [string]$functionReceiptObject.receipt_sha256 }
    )
    $probeStatus = if (@($checks | Where-Object { -not $_.pass }).Count -eq 0) { "PASS" } else { "FAIL" }
    $probe = [ordered]@{
        schema = "tier-bench/anchor-4060-physical-probe@1"
        generated_at = $stamp
        status = $probeStatus
        endpoint = $Endpoint
        python_version = (& $python --version 2>&1 | Out-String).Trim()
        dedicated_server = [ordered]@{
            pid = $server.Id
            executable = $ollama
            cuda_visible_devices = $GpuUuid
            ollama_host = $ollamaHost
        }
        nvidia_smi_command = @($nvidiaSmi)
        gpu = [ordered]@{
            uuid = $gpuLive.uuid
            name = $gpuLive.name
            memory_total_mib = $gpuLive.memory_total_mib
            memory_used_mib = $gpuLive.memory_used_mib
            driver_version = $gpuLive.driver_version
            pci_bus_id = $gpuLive.pci_bus_id
            pstate = $gpuLive.pstate
            power_limit_watts = $gpuLive.power_limit_watts
            power_draw_watts = $gpuLive.power_draw_watts
            compute_processes = $processRows
        }
        ollama = [ordered]@{
            version = [string]$version.version
            model = $Model
            model_digest = $modelDigest
            model_size_bytes = [int64]$catalogModel[0].size
            size_vram = [int64]$loadedModel[0].size_vram
            context_length = [int64]$loadedModel[0].context_length
            details = $show.details
            model_info = $show.model_info
        }
        checks = $checks
        production_claim = $false
        promotion_authorized = $false
    }
    $probePath = Join-Path $OutRoot "physical-probe.json"
    Write-Utf8NoBomJson $probePath $probe
    if ($probeStatus -ne "PASS") { throw "physical 4060 probe failed; inspect $probePath" }

    $backendOut = Join-Path $OutRoot "physical-backend"
    $build = Invoke-JsonCommand $python @(
        (Join-Path $TierBenchRoot "scripts\build_anchor_4060_manifest.py"),
        "--base-registry", (Join-Path $TierBenchRoot "labs\community-home-lab\anchor-crate\backend_registry.json"),
        "--estate-receipt", $EstateReceipt,
        "--estate-observation", $EstateObservation,
        "--control-host-observation", $ControlHostObservation,
        "--function-receipt", $functionReceipt,
        "--physical-probe", $probePath,
        "--executor", (Join-Path $TierBenchRoot "examples\anchor_crate\ollama_4060_executor.py"),
        "--python", $python,
        "--output-dir", $backendOut,
        "--backend-id", $BackendId,
        "--gpu-uuid", $GpuUuid
    ) "physical backend manifest build"

    $floor = Join-Path $TierBenchRoot "labs\community-home-lab\anchor-crate\floor.json"
    $cartridge = Join-Path $TierBenchRoot "labs\community-home-lab\anchor-crate\physical_availability_cartridge.json"
    $registry = [string]$build.registry
    $planPath = Join-Path $OutRoot "plan.physical-4060.json"
    $conformancePath = Join-Path $OutRoot "conformance.physical-4060.json"
    $resultPath = Join-Path $OutRoot "result.physical-4060.json"
    $runRoot = Join-Path $OutRoot "run.physical-4060"

    & $python -m tier_runner.anchor_crate validate --floor $floor --cartridge $cartridge --backends $registry
    if ($LASTEXITCODE -ne 0) { throw "physical backend registry validation failed" }
    & $python -m tier_runner.anchor_crate plan --floor $floor --cartridge $cartridge --backends $registry --bind "generate_decision_packet=$BackendId" --out $planPath
    if ($LASTEXITCODE -ne 0) { throw "physical plan compilation failed" }
    & $python -m tier_runner.anchor_crate conformance --backends $registry --backend $BackendId --controller-cwd $TierBenchRoot --out $conformancePath
    if ($LASTEXITCODE -ne 0) { throw "physical backend conformance failed" }
    & $python -m tier_runner.anchor_crate run --floor $floor --cartridge $cartridge --backends $registry --bind "generate_decision_packet=$BackendId" --run-root $runRoot --controller-cwd $TierBenchRoot --out $resultPath
    if ($LASTEXITCODE -ne 0) { throw "physical cartridge smoke failed" }

    $result = Read-JsonStrict $resultPath
    if ($result.status -ne "accepted" -or $result.final_product.decision_packet.claim -ne "not_physically_available") {
        throw "controller did not accept the expected physical-availability product"
    }
    $smokeReceipt = [ordered]@{
        schema = "tier-bench/anchor-4060-smoke-receipt@1"
        status = "PASS"
        generated_at = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        backend_id = $BackendId
        portable_task_id = $result.portable_task_id
        plan_id = $result.plan_id
        final_anchor_sha256 = $result.anchor.anchor_sha256
        claim = $result.final_product.decision_packet.claim
        requires_human_review = $result.final_product.decision_packet.requires_human_review
        source_receipts = [ordered]@{
            estate = $estateReceiptObject.receipt_sha256
            function = $functionReceiptObject.receipt_sha256
            physical_backend = (Read-JsonStrict ([string]$build.receipt)).receipt_sha256
        }
        physical_qualification = $true
        production_claim = $false
        promotion_authorized = $false
    }
    $smokeReceiptPath = Join-Path $OutRoot "smoke-receipt.json"
    Write-Utf8NoBomJson $smokeReceiptPath $smokeReceipt

    $sumRows = @()
    Get-ChildItem -LiteralPath $OutRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        if ($_.Name -ne "SHA256SUMS") {
            $relative = $_.FullName.Substring($OutRoot.Length).TrimStart('\').Replace('\','/')
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $sumRows += "$hash  $relative"
        }
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $OutRoot "SHA256SUMS"), ($sumRows -join "`n") + "`n", $utf8)
    Write-Output ($smokeReceipt | ConvertTo-Json -Depth 16)
} finally {
    if ($server -and -not $server.HasExited) {
        & taskkill.exe /PID $server.Id /T /F 2>$null | Out-Null
    }
}
