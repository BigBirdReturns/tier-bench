[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TierBenchRoot,
    [Parameter(Mandatory = $true)][string]$GradientRoot,
    [Parameter(Mandatory = $true)][string]$EstateReceipt,
    [Parameter(Mandatory = $true)][string]$EstateObservation,
    [Parameter(Mandatory = $true)][string]$ControlHostObservation,
    [string]$ThermalProfilePublicReceipt = "S:\Scratch\EOC007-A17-CLOSEOUT-01\crate\W01-RTX4060-THERMAL-QUALIFICATION-PUBLIC.json",
    [string]$ThermalProfilePrivateReceipt = "S:\Scratch\EOC007-A17-CLOSEOUT-01\crate\W01-RTX4060-THERMAL-QUALIFICATION-PRIVATE.json",
    [string]$ThermalCoverageRoot = "S:\Scratch\EOC007-OPERATOR-UNBLOCK-01\thermal",
    [string]$ThermalProfileCandidate = "S:\Scratch\EOC007-OPERATOR-UNBLOCK-01\receipts\W01-RTX4060-THERMAL-PROFILE-CANDIDATE.json",
    [string]$OutRoot = (Join-Path $env:LOCALAPPDATA "AXM\anchor-crate-4060-smoke"),
    [string]$Model = "qwen3.5:9b-q4_K_M",
    [string]$Endpoint = "http://127.0.0.1:11442",
    [string]$BackendId = "backend.cuda4060-qwen35-physical",
    [string]$GpuUuid = "",
    [int]$TargetPowerLimitW = 90,
    [string]$KeepAlive = "10m"
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

function Parse-KeepAlive {
    param([string]$Value)
    $match = [regex]::Match($Value, "^(?<value>\d+)(?<unit>[smh])$")
    if (-not $match.Success) {
        throw "OLLAMA_KEEP_ALIVE must be a bounded duration in s/m/h: $Value"
    }
    $seconds = [double]$match.Groups["value"].Value
    switch ($match.Groups["unit"].Value) {
        "s" { break }
        "m" { $seconds *= 60 }
        "h" { $seconds *= 3600 }
    }
    if ($seconds -lt 30 -or $seconds -gt 1800) {
        throw "OLLAMA_KEEP_ALIVE outside accepted bounds (30s - 1800s): $Value"
    }
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

function Is-EndpointInUse {
    param([string]$BaseUrl)
    try {
        $null = Invoke-RestMethod -Method Get -Uri ($BaseUrl.TrimEnd('/') + "/api/version") -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
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
    $parts = @($Line -split "," | ForEach-Object { $_.Trim() })
    if ($parts.Count -lt 14) { throw "nvidia-smi returned an incomplete GPU row: $Line" }
    return [ordered]@{
        uuid = $parts[0]
        name = $parts[1]
        vbios_version = $parts[2]
        memory_total_mib = [double]$parts[3]
        memory_used_mib = [double]$parts[4]
        driver_version = $parts[5]
        pci_bus_id = $parts[6]
        pstate = $parts[7]
        power_limit_watts = [double]$parts[8]
        power_draw_watts = if ($parts[9] -match '^[0-9.]+$') { [double]$parts[9] } else { $null }
        utilization_gpu = if ($parts[10] -match '^[0-9.]+$') { [double]$parts[10] } else { $null }
        power_min_limit_watts = if ($parts[11] -match '^[0-9.]+$') { [double]$parts[11] } else { $null }
        power_max_limit_watts = if ($parts[12] -match '^[0-9.]+$') { [double]$parts[12] } else { $null }
        power_default_limit_watts = if ($parts[13] -match '^[0-9.]+$') { [double]$parts[13] } else { $null }
    }
}

function Parse-ComputeRow {
    param([string]$Line)
    $parts = @($Line -split "," | ForEach-Object { $_.Trim() })
    if ($parts.Count -lt 4) { return $null }
    return [ordered]@{
        gpu_uuid = $parts[0]
        pid = [int64]$parts[1]
        process_name = $parts[2]
        used_memory_mib = [double]$parts[3]
    }
}

function Capture-EnvironmentState {
    param([string[]]$Names)
    $state = @{}
    foreach ($name in $Names) {
        $entry = Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        if ($entry) {
            $state[$name] = @{ present = $true; value = [string]$entry.Value }
        } else {
            $state[$name] = @{ present = $false; value = $null }
        }
    }
    return $state
}

function Restore-EnvironmentState {
    param([hashtable]$State)
    foreach ($name in $State.Keys) {
        $entry = $State[$name]
        if ($entry.present) {
            Set-Item -Path "Env:$name" -Value [string]$entry.value
        } else {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

function Test-EnvironmentState {
    param([hashtable]$State)
    foreach ($name in $State.Keys) {
        $current = Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        if ($State[$name].present) {
            if (-not $current -or [string]$current.Value -cne [string]$State[$name].value) { return $false }
        } elseif ($current) {
            return $false
        }
    }
    return $true
}

function Assert-LoopbackEndpoint {
    param([string]$EndpointValue)
    try {
        $endpointUri = [Uri]$EndpointValue
    } catch {
        throw "physical smoke requires a valid loopback endpoint: $EndpointValue"
    }
    if ($endpointUri.Scheme -ne "http" -or $endpointUri.Host -notin @("127.0.0.1", "localhost", "::1")) {
        throw "physical smoke requires a loopback HTTP endpoint"
    }
    if ($endpointUri.Path -and $endpointUri.Path -notin @("", "/")) {
        throw "Ollama endpoint must be loopback-only root path"
    }
}

function Ensure-ThermalReceipt {
    param(
        [string]$ReceiptPath,
        [string]$ExpectedProfileId,
        [string]$Label
    )
    $ReceiptPath = Resolve-FileStrict $ReceiptPath $Label
    $obj = Read-JsonStrict $ReceiptPath
    if (($obj.profile_id -ne $ExpectedProfileId)) {
        throw "$Label does not target profile $ExpectedProfileId (got $($obj.profile_id))"
    }
    if ($obj.terminal -ne "PASS" -or (($obj.PSObject.Properties.Name -contains "pass") -and $obj.pass -ne $true)) {
        throw "$Label is not PASS"
    }
    if ($obj.PSObject.Properties.Name -contains "rerun_required" -and $obj.rerun_required -ne $false) {
        throw "$Label requests rerun_required=true"
    }
    if ($obj.PSObject.Properties.Name -contains "provider_calls" -and [int]$obj.provider_calls -ne 0) {
        throw "$Label recorded provider calls"
    }
    if ($obj.PSObject.Properties.Name -contains "authorizes_a17_smoke" -and -not [bool]$obj.authorizes_a17_smoke) {
        throw "$Label does not authorize the A-17 run"
    }
    $sha = (Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    return @{ path = (Resolve-Path -LiteralPath $ReceiptPath).Path; receipt = $obj; sha256 = $sha }
}

function Ensure-ThermalCoverage {
    param([string]$CoverageRoot, [string]$CandidatePath)
    $CoverageRoot = Resolve-DirectoryStrict $CoverageRoot "thermal coverage root"
    $CandidatePath = Resolve-FileStrict $CandidatePath "thermal profile candidate"
    $coordinates = @(
        (Join-Path $CoverageRoot "qwen-thermal-receipt.json"),
        (Join-Path $CoverageRoot "qwen-telemetry.csv"),
        (Join-Path $CoverageRoot "qwen-casefan-trace.jsonl"),
        (Join-Path $CoverageRoot "case-fan-hold.ps1"),
        (Join-Path $CoverageRoot "qwen-thermal-qualify.ps1"),
        (Join-Path $CoverageRoot "qwen-pl-set.log"),
        (Join-Path $CoverageRoot "qwen-pl-restore.log"),
        $CandidatePath
    )
    $rows = @()
    foreach ($coordinate in $coordinates) {
        $path = Resolve-FileStrict $coordinate "thermal covered artifact"
        $rows += [ordered]@{
            path = $path
            sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $receipt = Read-JsonStrict $coordinates[0]
    $candidate = Read-JsonStrict $CandidatePath
    $identityArtifacts = @()
    if ($receipt.PSObject.Properties.Name -contains "artifacts") { $identityArtifacts += @($receipt.artifacts) }
    if ($candidate.PSObject.Properties.Name -contains "artifacts") { $identityArtifacts += @($candidate.artifacts) }
    if (-not $identityArtifacts.Count) { throw "thermal evidence does not provide covered-artifact digests" }
    foreach ($artifact in $identityArtifacts) {
            if (-not $artifact.path -or -not $artifact.sha256) { throw "thermal receipt artifact identity is incomplete" }
            $artifactRoot = if ($artifact.PSObject.Properties.Name -contains "root" -and $artifact.root) { [string]$artifact.root } else { $CoverageRoot }
            $coveredPath = Join-Path $artifactRoot ([string]$artifact.path)
            $coveredPath = Resolve-FileStrict $coveredPath "thermal receipt artifact"
            $actual = (Get-FileHash -LiteralPath $coveredPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne ([string]$artifact.sha256).ToLowerInvariant()) {
                throw "thermal receipt covered-artifact digest mismatch: $coveredPath"
            }
            if (-not ($rows | Where-Object { $_.path -eq $coveredPath })) {
                $rows += [ordered]@{ path = $coveredPath; sha256 = $actual }
            }
    }
    return $rows
}

function Ensure-ThermalHolder {
    param([array]$CoverageArtifacts)
    $policy = @($CoverageArtifacts | Where-Object { $_.path -like "*case-fan-hold.ps1" })
    $trace = @($CoverageArtifacts | Where-Object { $_.path -like "*qwen-casefan-trace.jsonl" })
    if ($policy.Count -ne 1 -or $trace.Count -ne 1) { throw "thermal holder policy or trace identity is ambiguous" }
    $age = ([DateTimeOffset]::UtcNow - [DateTimeOffset](Get-Item -LiteralPath $trace[0].path).LastWriteTimeUtc).TotalSeconds
    if ($age -lt 0 -or $age -gt 12) { throw "thermal holder sensors are stale" }
    $tail = Get-Content -LiteralPath $trace[0].path -Tail 1 -Encoding UTF8
    if (-not $tail) { throw "thermal holder trace has no current sensor row" }
    $traceObject = $tail | ConvertFrom-Json
    $traceText = $traceObject | ConvertTo-Json -Depth 32 -Compress
    $channels = @("Pump Fan control/1", "System Fan #1 control/2", "System Fan #3 control/4")
    foreach ($channel in $channels) {
        $name = ($channel -split " control/")[0]
        if ($traceText -notmatch [regex]::Escape($name)) { throw "thermal holder trace omits $channel" }
    }
    $tachValues = [regex]::Matches($traceText, '(?i)(?:tach(?:ometer)?|rpm)[^0-9]{0,20}(?<rpm>[0-9]+(?:\.[0-9]+)?)')
    if (@($tachValues | Where-Object { [double]$_.Groups['rpm'].Value -gt 0 }).Count -lt 3) {
        throw "thermal holder trace does not confirm three nonzero tachometers"
    }
    $escapedPolicy = [regex]::Escape([string]$policy[0].path)
    $holders = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $escapedPolicy })
    if ($holders.Count -ne 1) { throw "expected one already-running accepted thermal holder, found $($holders.Count)" }
    $candidateText = Get-Content -LiteralPath $ThermalProfileCandidate -Raw -Encoding UTF8
    if ($candidateText -notmatch "PawnIO" -or $candidateText -notmatch "LibreHardwareMonitor") {
        throw "thermal candidate does not bind PawnIO and LibreHardwareMonitor"
    }
    $positiveTach = @($tachValues | Where-Object { [double]$_.Groups['rpm'].Value -gt 0 } | ForEach-Object { [double]$_.Groups['rpm'].Value })
    $fanRows = @()
    for ($index = 0; $index -lt $channels.Count; $index++) {
        $fanRows += [ordered]@{ channel = $channels[$index]; tachometer_rpm = $positiveTach[$index] }
    }
    return [ordered]@{
        active = $true
        pid = [int64]$holders[0].ProcessId
        executable_path = [string]$holders[0].ExecutablePath
        policy_path = [string]$policy[0].path
        policy_sha256 = [string]$policy[0].sha256
        pawnio_identity_verified = $true
        lhm_identity_verified = $true
        sensor_age_seconds = [math]::Round($age, 3)
        fan_channels = $fanRows
    }
}

function Ensure-ThermalCandidateIdentity {
    param([string]$CandidatePath, [System.Collections.IDictionary]$Gpu, [string]$ModelName)
    $text = Get-Content -LiteralPath $CandidatePath -Raw -Encoding UTF8
    foreach ($identity in @(
        "GPU-e0b1541d-fc7d-38f5-d4c0-c15a3bd241a0",
        [string]$Gpu.vbios_version,
        [string]$Gpu.driver_version,
        $ModelName,
        "PawnIO",
        "LibreHardwareMonitor"
    )) {
        if (-not $identity -or $text -notmatch [regex]::Escape($identity)) {
            throw "thermal profile candidate does not bind required identity: $identity"
        }
    }
    if ($text -notmatch '(?i)(power.{0,30}90|90.{0,12}W)' -or $text -notmatch '(?i)(worker.{0,12}2|2.{0,12}worker)' -or $text -notmatch '(?i)(900|15.?min)') {
        throw "thermal profile candidate workload or power identity differs"
    }
}

function Query-GpuRows {
    param([string]$NvidiaSmi, [string]$TargetUuid, [string]$Query)
    $raw = @(& $NvidiaSmi -i $TargetUuid "--query-gpu=$Query" "--format=csv,noheader,nounits" 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi GPU query failed" }
    $rows = @()
    foreach ($line in $raw) {
        $line = [string]$line
        if (-not $line.Trim()) { continue }
        $rows += Parse-NvidiaRow $line
    }
    return $rows
}

function Query-AllGpuRows {
    param([string]$NvidiaSmi, [string]$Query)
    $raw = @(& $NvidiaSmi "--query-gpu=$Query" "--format=csv,noheader,nounits" 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi full GPU inventory query failed" }
    $rows = @()
    foreach ($line in $raw) {
        if ([string]$line -and ([string]$line).Trim()) { $rows += Parse-NvidiaRow ([string]$line) }
    }
    if (-not $rows.Count) { throw "nvidia-smi returned no NVIDIA GPUs" }
    return $rows
}

function Query-ComputeRows {
    param([string]$NvidiaSmi)
    $raw = @(& $NvidiaSmi "--query-compute-apps=gpu_uuid,pid,process_name,used_memory" "--format=csv,noheader,nounits" 2>$null)
    if ($LASTEXITCODE -ne 0) { return @() }
    $rows = @()
    foreach ($line in $raw) {
        $line = [string]$line
        if (-not $line.Trim()) { continue }
        $row = Parse-ComputeRow $line
        if ($row) { $rows += $row }
    }
    return $rows
}

function Ensure-OllamaProcessPlacement {
    param([string]$TargetUuid, [array]$ComputeRows, [array]$BeforeInventory, [array]$LiveInventory, [double]$ModelVramMiB)
    $ollamaRows = @($ComputeRows | Where-Object { $_.process_name -match "ollama" })
    if (-not $ollamaRows.Count) {
        throw "no Ollama compute process is visible to nvidia-smi"
    }
    $offTarget = @($ollamaRows | Where-Object { $_.gpu_uuid -ne $TargetUuid })
    if ($offTarget.Count) {
        throw "Ollama compute process is visible on non-target GPU(s): $($offTarget | ForEach-Object { $_.gpu_uuid } -join ',')"
    }
    $onTarget = @($ollamaRows | Where-Object { $_.gpu_uuid -eq $TargetUuid })
    if (-not ($onTarget | ForEach-Object { $_.used_memory_mib } | Measure-Object -Sum).Sum) {
        throw "Ollama process is not resident (used memory is zero) on the target"
    }
    foreach ($row in @($LiveInventory | Where-Object { $_.uuid -ne $TargetUuid })) {
        $before = @($BeforeInventory | Where-Object { $_.uuid -eq $row.uuid })
        if ($before.Count -ne 1) { throw "non-target GPU inventory changed during the dedicated transaction" }
        if (([double]$row.memory_used_mib - [double]$before[0].memory_used_mib) -ge [math]::Max(1024, $ModelVramMiB * 0.75)) {
            throw "model-sized VRAM growth is visible on non-target GPU $($row.uuid)"
        }
    }
}

function Ensure-PowerLimits {
    param([hashtable]$Row, [double]$TargetW)
    if ($TargetW -ne 90) { throw "the qualified thermal profile admits only an exact 90 W target" }
    if ($null -eq $Row.power_min_limit_watts -or $null -eq $Row.power_max_limit_watts -or $null -eq $Row.power_default_limit_watts) {
        throw "card power-limit legality fields are incomplete"
    }
    if ([math]::Abs([double]$Row.power_default_limit_watts - 115) -gt 0.5) { throw "bound card default power limit is not 115 W" }
    if ([math]::Abs([double]$Row.power_limit_watts - 115) -gt 0.5) { throw "pre-run power limit is not the restorable 115 W default" }
    if ($TargetW -lt $Row.power_min_limit_watts -or $TargetW -gt $Row.power_max_limit_watts) {
        throw "target power cap $TargetW W is outside [$($Row.power_min_limit_watts), $($Row.power_max_limit_watts)]"
    }
}

function Set-PowerLimit {
    param([string]$NvidiaSmi, [string]$TargetUuid, [int]$TargetW)
    & $NvidiaSmi -i $TargetUuid --power-limit=$TargetW 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "power-limit apply failed for $TargetUuid to $TargetW W" }
}

function Stop-OllamaServer {
    param([System.Diagnostics.Process]$Process)
    if ($Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
}

function Assert-EndpointStopped {
    param([string]$BaseUrl)
    try {
        $null = Invoke-RestMethod -Method Get -Uri ($BaseUrl.TrimEnd('/') + "/api/version") -TimeoutSec 2
        return $false
    } catch {
        return $true
    }
}

function Add-Failure {
    param([System.Collections.Generic.List[string]]$Sink, [string]$Message)
    $Sink.Add($Message)
}

$TierBenchRoot = Resolve-DirectoryStrict $TierBenchRoot "Tier Bench root"
$GradientRoot = Resolve-DirectoryStrict $GradientRoot "Home Lab Gradient root"
$EstateReceipt = Resolve-FileStrict $EstateReceipt "estate receipt"
$EstateObservation = Resolve-FileStrict $EstateObservation "estate observation"
$ControlHostObservation = Resolve-FileStrict $ControlHostObservation "control-host observation"
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
if (Test-Path -LiteralPath $OutRoot) { throw "output root already exists: $OutRoot" }
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null

Parse-KeepAlive $KeepAlive
$profileId = "W01-RTX4060-MENACE-A17-THERMAL-V1"
$thermalPublic = Ensure-ThermalReceipt $ThermalProfilePublicReceipt $profileId "public thermal profile receipt"
$thermalPrivate = Ensure-ThermalReceipt $ThermalProfilePrivateReceipt $profileId "private thermal profile receipt"
$thermalCoverage = Ensure-ThermalCoverage $ThermalCoverageRoot $ThermalProfileCandidate
$thermalHolder = Ensure-ThermalHolder $thermalCoverage

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
if ($gpuCandidates.Count -ne 1) {
    throw "expected one exact RTX 4060 in the control-host census, found $($gpuCandidates.Count)"
}
$gpu = $gpuCandidates[0]
$GpuUuid = [string]$gpu.uuid
if ($GpuUuid -ne "GPU-e0b1541d-fc7d-38f5-d4c0-c15a3bd241a0") { throw "selected GPU is not the exact thermally qualified RTX 4060" }

Assert-LoopbackEndpoint $Endpoint
if (Is-EndpointInUse $Endpoint) { throw "the dedicated Ollama endpoint is already occupied: $Endpoint" }
$endpointUri = [Uri]$Endpoint
$ollamaHost = if ($endpointUri.IsDefaultPort) { $endpointUri.Host } else { "$($endpointUri.Host):$($endpointUri.Port)" }

$schedSpread = $env:OLLAMA_SCHED_SPREAD
if ($schedSpread) {
    throw "OLLAMA_SCHED_SPREAD is inherited; hostile control rejects scheduler spread"
}

$envKeys = @("OLLAMA_HOST", "CUDA_VISIBLE_DEVICES", "OLLAMA_KEEP_ALIVE", "OLLAMA_VULKAN", "OLLAMA_SCHED_SPREAD")
$originalEnv = Capture-EnvironmentState $envKeys
$cleanupFailures = New-Object System.Collections.Generic.List[string]
$server = $null
$powerLimitRestore = $null
$powerBefore = $null
$powerAfter = $null

try {
    $gpuQuery = "uuid,name,vbios_version,memory.total,memory.used,driver_version,pci.bus_id,pstate,power.limit,power.draw,utilization.gpu,power.min_limit,power.max_limit,power.default_limit"
    $inventoryBefore = Query-AllGpuRows -NvidiaSmi $nvidiaSmi -Query $gpuQuery
    $censusUuids = @($control.graphics.nvidia | ForEach-Object { [string]$_.uuid } | Sort-Object)
    $liveUuids = @($inventoryBefore | ForEach-Object { [string]$_.uuid } | Sort-Object)
    if (($censusUuids -join ',') -ne ($liveUuids -join ',')) { throw "live NVIDIA inventory differs from the complete census" }
    $baseGpu = Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery
    if ($baseGpu.Count -ne 1) { throw "could not locate target GPU in nvidia-smi query" }
    $baseGpu = $baseGpu[0]
    Ensure-ThermalCandidateIdentity -CandidatePath $ThermalProfileCandidate -Gpu $baseGpu -ModelName $Model
    $powerBefore = [double]$baseGpu.power_limit_watts
    Ensure-PowerLimits -Row $baseGpu -TargetW $TargetPowerLimitW
    $powerLimitRestore = 115

    Set-PowerLimit -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -TargetW $TargetPowerLimitW
    $powerAfter = (Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery)[0].power_limit_watts
    if ([math]::Abs([double]$powerAfter - 90) -gt 0.5) { throw "power-limit application did not establish exact 90 W" }

    $env:OLLAMA_HOST = $ollamaHost
    $env:CUDA_VISIBLE_DEVICES = $GpuUuid
    $env:OLLAMA_VULKAN = "0"
    $env:OLLAMA_KEEP_ALIVE = $KeepAlive
    Remove-Item Env:OLLAMA_SCHED_SPREAD -ErrorAction SilentlyContinue
    $server = Start-Process -FilePath $ollama -ArgumentList @("serve") -PassThru -WindowStyle Hidden
    if ($server -eq $null -or $server.HasExited) { throw "failed to start dedicated Ollama server" }

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

    $gpuLive = (Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery)[0]
    $inventoryLive = Query-AllGpuRows -NvidiaSmi $nvidiaSmi -Query $gpuQuery
    $computeRows = Query-ComputeRows -NvidiaSmi $nvidiaSmi
    Ensure-OllamaProcessPlacement -TargetUuid $GpuUuid -ComputeRows $computeRows -BeforeInventory $inventoryBefore -LiveInventory $inventoryLive -ModelVramMiB ([double]$loadedModel[0].size_vram / 1MB)

    $checks = @(
        [ordered]@{ id = "three-host-census-pass"; pass = $true; detail = [string]$estateReceiptObject.receipt_sha256 },
        [ordered]@{ id = "dedicated-loopback-server"; pass = ($server -and -not $server.HasExited); detail = "pid=$($server.Id) endpoint=$Endpoint" },
        [ordered]@{ id = "exact-target-uuid"; pass = ($GpuUuid -eq [string]$gpuLive.uuid); detail = $GpuUuid },
        [ordered]@{ id = "cuda-visible-devices-bound"; pass = ($env:CUDA_VISIBLE_DEVICES -eq $GpuUuid); detail = $env:CUDA_VISIBLE_DEVICES },
        [ordered]@{ id = "ollama-vulkan-fixed"; pass = ($env:OLLAMA_VULKAN -eq "0"); detail = $env:OLLAMA_VULKAN },
        [ordered]@{ id = "keep-alive-bounded"; pass = $true; detail = $KeepAlive },
        [ordered]@{ id = "exact-model-digest"; pass = ($catalogModel.Count -eq 1 -and $loadedModel.Count -eq 1); detail = $modelDigest },
        [ordered]@{ id = "function-replay-pass"; pass = ($qualified.status -eq "PASS"); detail = [string]$functionReceiptObject.receipt_sha256 },
        [ordered]@{ id = "scheduler-spread-refused"; pass = (-not $schedSpread); detail = "OLLAMA_SCHED_SPREAD not present" },
        [ordered]@{ id = "thermal-profile-bound"; pass = ($thermalPublic.sha256 -and $thermalPrivate.sha256); detail = $profileId },
        [ordered]@{ id = "thermal-covered-artifacts-verified"; pass = ($thermalCoverage.Count -ge 8); detail = "$($thermalCoverage.Count) artifacts" },
        [ordered]@{ id = "thermal-holder-live"; pass = [bool]$thermalHolder.active; detail = "pid=$($thermalHolder.pid)" },
        [ordered]@{ id = "all-nvidia-gpus-enumerated"; pass = ($inventoryBefore.Count -eq $inventoryLive.Count); detail = ($liveUuids -join ',') },
        [ordered]@{ id = "power-limit-set"; pass = ([int]$gpuLive.power_limit_watts -eq $TargetPowerLimitW); detail = "$($gpuLive.power_limit_watts)" },
        [ordered]@{ id = "nvidia-memory-residency"; pass = ([int64]$gpuLive.memory_used_mib -ge 1024); detail = [string]$gpuLive.memory_used_mib },
        [ordered]@{ id = "ollama-vram-residency"; pass = ([int64]$loadedModel[0].size_vram -ge 2147483648); detail = [string]$loadedModel[0].size_vram }
    )
    $probeStatus = if (@($checks | Where-Object { -not $_.pass }).Count -eq 0) { "PASS" } else { "FAIL" }
    $probe = [ordered]@{
        schema = "tier-bench/anchor-4060-physical-probe@1"
        generated_at = $stamp
        status = $probeStatus
        endpoint = $Endpoint
        thermal_profile = [ordered]@{
            profile_id = $profileId
            fan_governance = "PawnIO_LibreHardwareMonitor_holder"
            fan_channels = $thermalHolder.fan_channels
            holder = $thermalHolder
            coverage_artifacts = $thermalCoverage
            public_receipt = $thermalPublic.path
            private_receipt = $thermalPrivate.path
            public_receipt_sha256 = $thermalPublic.sha256
            private_receipt_sha256 = $thermalPrivate.sha256
        }
        power_limit_target_watts = $TargetPowerLimitW
        power_before_watts = $powerBefore
        power_control = [ordered]@{
            minimum_watts = $baseGpu.power_min_limit_watts
            maximum_watts = $baseGpu.power_max_limit_watts
            default_watts = $baseGpu.power_default_limit_watts
            pre_run_watts = $powerBefore
            applied_watts = $powerAfter
            application_result = "PASS"
            restoration_target_watts = $powerLimitRestore
        }
        gpu_inventory_before = $inventoryBefore
        gpu_inventory_live = $inventoryLive
        keep_alive = $KeepAlive
        python_version = (& $python --version 2>&1 | Out-String).Trim()
        dedicated_server = [ordered]@{
            pid = $server.Id
            executable = $ollama
            cuda_visible_devices = $GpuUuid
            ollama_host = $ollamaHost
            ollama_vulkan = "0"
        }
        nvidia_smi_command = @($nvidiaSmi)
        gpu = [ordered]@{
            uuid = $gpuLive.uuid
            name = $gpuLive.name
            vbios_version = $gpuLive.vbios_version
            memory_total_mib = $gpuLive.memory_total_mib
            memory_used_mib = $gpuLive.memory_used_mib
            driver_version = $gpuLive.driver_version
            pci_bus_id = $gpuLive.pci_bus_id
            pstate = $gpuLive.pstate
            power_limit_watts = $gpuLive.power_limit_watts
            power_draw_watts = $gpuLive.power_draw_watts
            utilization_gpu = $gpuLive.utilization_gpu
            compute_processes = $computeRows
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
        "--thermal-profile-public-receipt", $thermalPublic.path,
        "--thermal-profile-private-receipt", $thermalPrivate.path,
        "--thermal-target-power-limit-watts", "$TargetPowerLimitW",
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
    & $python -m tier_runner.anchor_crate run --floor $floor --cartridge $cartridge --backends $registry --bind "generate_decision_packet=$BackendId" --controller-cwd $TierBenchRoot --run-root $runRoot --out $resultPath
    if ($LASTEXITCODE -ne 0) { throw "physical cartridge smoke failed" }

    $result = Read-JsonStrict $resultPath
    if ($result.status -ne "accepted" -or $result.final_product.decision_packet.claim -ne "not_physically_available") {
        throw "controller did not accept the expected physical-availability product"
    }
    $acceptedResult = $result
    $physicalBackendReceiptSha = (Read-JsonStrict ([string]$build.receipt)).receipt_sha256
} finally {
    $processStopped = $true
    if ($server -and -not $server.HasExited) {
        try {
            Stop-OllamaServer -Process $server
            $server.WaitForExit(10000) | Out-Null
            if (-not $server.HasExited) { $processStopped = $false; Add-Failure -Sink $cleanupFailures -Message "Ollama process tree remained live" }
        } catch {
            $processStopped = $false
            Add-Failure -Sink $cleanupFailures -Message "could not stop Ollama process tree"
        }
    }
    $endpointStopped = Assert-EndpointStopped -BaseUrl $Endpoint
    if (-not $endpointStopped) { Add-Failure -Sink $cleanupFailures -Message "endpoint remained reachable after stop" }
    $environmentRestored = $false
    try {
        Restore-EnvironmentState -State $originalEnv
        $environmentRestored = Test-EnvironmentState -State $originalEnv
        if (-not $environmentRestored) { Add-Failure -Sink $cleanupFailures -Message "environment state differs after restore" }
    } catch {
        Add-Failure -Sink $cleanupFailures -Message "environment restore failed"
    }
    $powerRestored = ($powerLimitRestore -eq $null)
    $powerRestoredTo = $null
    if ($powerLimitRestore -ne $null -and (Test-Path -LiteralPath $nvidiaSmi)) {
        try {
            Set-PowerLimit -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -TargetW $powerLimitRestore
            $powerRestoredTo = (Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery)[0].power_limit_watts
            $powerRestored = [math]::Abs([double]$powerRestoredTo - $powerLimitRestore) -le 0.5
            if (-not $powerRestored) {
                Add-Failure -Sink $cleanupFailures -Message "power-limit restoration target mismatch"
            }
        } catch {
            Add-Failure -Sink $cleanupFailures -Message "power-limit restoration command failed"
        }
    }
    $holderReturned = $false
    try {
        $holderAfter = Ensure-ThermalHolder $thermalCoverage
        $holderReturned = $holderAfter.active -and $holderAfter.pid -eq $thermalHolder.pid
        if (-not $holderReturned) { Add-Failure -Sink $cleanupFailures -Message "accepted thermal holder did not remain in ordinary control" }
    } catch {
        Add-Failure -Sink $cleanupFailures -Message "accepted thermal holder is not healthy after cleanup"
    }
    $cleanupResult = [ordered]@{
        schema = "tier-bench/anchor-4060-cleanup-result@1"
        status = if ($cleanupFailures.Count -eq 0) { "PASS" } else { "REFUSED" }
        generated_at = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        endpoint_stopped = $endpointStopped
        process_tree_stopped = $processStopped
        environment_restored = $environmentRestored
        power_restored = $powerRestored
        power_restored_to_watts = $powerRestoredTo
        holder_returned = $holderReturned
        failures = @($cleanupFailures)
    }
    Write-Utf8NoBomJson (Join-Path $OutRoot "cleanup-result.json") $cleanupResult
    if ($cleanupFailures.Count -gt 0) {
        throw ("cleanup incomplete: " + ($cleanupFailures -join "; "))
    }
}

$smokeReceipt = [ordered]@{
    schema = "tier-bench/anchor-4060-smoke-receipt@1"
    status = "PASS"
    generated_at = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    backend_id = $BackendId
    portable_task_id = $acceptedResult.portable_task_id
    plan_id = $acceptedResult.plan_id
    final_anchor_sha256 = $acceptedResult.anchor.anchor_sha256
    claim = $acceptedResult.final_product.decision_packet.claim
    requires_human_review = $acceptedResult.final_product.decision_packet.requires_human_review
    source_receipts = [ordered]@{
        estate = $estateReceiptObject.receipt_sha256
        function = $functionReceiptObject.receipt_sha256
        physical_backend = $physicalBackendReceiptSha
        thermal_profile_public = $thermalPublic.sha256
        thermal_profile_private = $thermalPrivate.sha256
        thermal_profile_id = $profileId
    }
    thermal_profile = [ordered]@{
        holder = $thermalHolder
        fan_channels = $thermalHolder.fan_channels
        coverage_artifacts = $thermalCoverage
        bound = $true
    }
    power_limit = [ordered]@{
        requested_watts = $TargetPowerLimitW
        pre_run_watts = $powerBefore
        post_apply_watts = $powerAfter
        post_cleanup_target_watts = $powerLimitRestore
        post_cleanup_observed_watts = $cleanupResult.power_restored_to_watts
    }
    endpoint = [ordered]@{ base = $Endpoint; stopped = $cleanupResult.endpoint_stopped }
    cleanup = $cleanupResult
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
