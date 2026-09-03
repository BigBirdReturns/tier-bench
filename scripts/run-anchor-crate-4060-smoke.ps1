[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TierBenchRoot,
    [Parameter(Mandatory = $true)][string]$GradientRoot,
    [Parameter(Mandatory = $true)][string]$EstateReceipt,
    [Parameter(Mandatory = $true)][string]$EstateObservation,
    [Parameter(Mandatory = $true)][string]$ControlHostObservation,
    [Parameter(Mandatory = $true)][string]$ThermalProfilePublicReceipt,
    [Parameter(Mandatory = $true)][string]$ThermalProfilePrivateReceipt,
    [Parameter(Mandatory = $true)][string]$ThermalControlManifest,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedThermalControlManifestSha256,
    [string]$OutRoot = "",
    [string]$Model = "qwen3.5:9b-q4_K_M",
    [string]$Endpoint = "http://127.0.0.1:11442",
    [string]$BackendId = "backend.cuda4060-qwen35-physical",
    [string]$GpuUuid = "",
    [int]$TargetPowerLimitW = 90,
    [string]$KeepAlive = "10m",
    [ValidateSet("", "power-apply-fails", "power-restore-fails", "holder-preflight-fails", "post-load-primary-cleanup-fails")]
    [string]$FailureHarnessScenario = ""
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
        [string]$ExpectedSha256,
        [string]$ExpectedProfileId,
        [string]$Label
    )
    $ReceiptPath = Resolve-FileStrict $ReceiptPath $Label
    $sha = (Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -cne $ExpectedSha256) { throw "$Label controlling identity mismatch" }
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
    return @{ path = $ReceiptPath; receipt = $obj; observed_sha256 = $sha; controlling_sha256 = $ExpectedSha256 }
}

function Read-ThermalControl {
    param([string]$ManifestPath, [string]$ExpectedSha256)
    $ManifestPath = Resolve-FileStrict $ManifestPath "thermal control manifest"
    $observed = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($observed -cne $ExpectedSha256) { throw "thermal control manifest controlling identity mismatch" }
    $control = Read-JsonStrict $ManifestPath
    if ($control.schema -ne "tier-bench/anchor-thermal-control@1" -or $control.profile_id -ne "W01-RTX4060-MENACE-A17-THERMAL-V1") {
        throw "thermal control manifest schema or profile identity mismatch"
    }
    return @{ path = $ManifestPath; observed_sha256 = $observed; controlling_sha256 = $ExpectedSha256; control = $control }
}

function Ensure-ThermalCoverage {
    param($Control)
    $rows = @()
    foreach ($artifact in @($Control.artifacts)) {
        if (-not $artifact.path -or [string]$artifact.sha256 -notmatch '^[0-9a-f]{64}$') { throw "thermal control artifact identity is incomplete" }
        $path = Resolve-FileStrict ([string]$artifact.path) "thermal covered artifact"
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne [string]$artifact.sha256) { throw "thermal control artifact digest mismatch: $path" }
        $rows += [ordered]@{
            path = $path
            sha256 = $actual
        }
    }
    if ($rows.Count -lt 8) { throw "thermal control manifest covers fewer than eight required artifacts" }
    return $rows
}

function Ensure-ThermalHolder {
    param($Control)
    $accepted = $Control.holder
    if (-not $accepted) { throw "thermal control holder identities are missing" }
    $measured = [ordered]@{}
    foreach ($name in @("executable", "lhm", "pawnio", "policy")) {
        $identity = $accepted.$name
        if (-not $identity.path -or [string]$identity.sha256 -notmatch '^[0-9a-f]{64}$') { throw "thermal control $name identity is incomplete" }
        $path = Resolve-FileStrict ([string]$identity.path) "thermal holder $name"
        $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($digest -cne [string]$identity.sha256) { throw "thermal holder $name digest mismatch" }
        $measured[$name] = [ordered]@{ path = $path; sha256 = $digest }
    }
    $escapedPolicy = [regex]::Escape([string]$measured.policy.path)
    $holders = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $escapedPolicy })
    if ($holders.Count -ne 1) { throw "expected one already-running accepted thermal holder, found $($holders.Count)" }
    $holderExecutable = Resolve-FileStrict ([string]$holders[0].ExecutablePath) "running thermal holder executable"
    $holderDigest = (Get-FileHash -LiteralPath $holderExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($holderExecutable -cne $measured.executable.path -or $holderDigest -cne $measured.executable.sha256) {
        throw "running thermal holder executable identity differs from control manifest"
    }
    $tracePath = Resolve-FileStrict ([string]$Control.fan_trace_path) "thermal fan trace"
    $tail = Get-Content -LiteralPath $tracePath -Tail 1 -Encoding UTF8
    if (-not $tail) { throw "thermal holder trace has no current sensor row" }
    $traceObject = $tail | ConvertFrom-Json
    $acceptedFans = @($Control.fan_channels)
    $observedFans = @($traceObject.fan_channels)
    if ($acceptedFans.Count -ne 3 -or $observedFans.Count -ne 3) { throw "thermal fan trace must contain exactly three structured channels" }
    $fanRows = @()
    $maxAge = 0.0
    foreach ($fan in $acceptedFans) {
        $matches = @($observedFans | Where-Object {
            $_.channel -eq $fan.channel -and
            $_.control_identity -eq $fan.control_identity -and
            $_.tachometer_sensor_identity -eq $fan.tachometer_sensor_identity
        })
        if ($matches.Count -ne 1) { throw "thermal fan structured identity mismatch: $($fan.channel)" }
        $observed = $matches[0]
        if ([double]$observed.tachometer_rpm -le 0 -or -not $observed.timestamp) { throw "thermal fan tachometer record is incomplete: $($fan.channel)" }
        $age = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse([string]$observed.timestamp).ToUniversalTime()).TotalSeconds
        if ($age -lt 0 -or $age -gt 12) { throw "thermal fan sensor is stale: $($fan.channel)" }
        $maxAge = [math]::Max($maxAge, $age)
        $fanRows += [ordered]@{
            channel = [string]$observed.channel
            control_identity = [string]$observed.control_identity
            tachometer_sensor_identity = [string]$observed.tachometer_sensor_identity
            tachometer_rpm = [double]$observed.tachometer_rpm
            timestamp = [string]$observed.timestamp
        }
    }
    return [ordered]@{
        active = $true
        pid = [int64]$holders[0].ProcessId
        creation_time = ([DateTimeOffset]$holders[0].CreationDate).ToUniversalTime().ToString("o")
        executable = $measured.executable
        lhm = $measured.lhm
        pawnio = $measured.pawnio
        policy = $measured.policy
        sensor_age_seconds = [math]::Round($maxAge, 3)
        fan_channels = $fanRows
    }
}

function Ensure-ThermalControlIdentity {
    param($Control, [System.Collections.IDictionary]$Gpu, [string]$ModelName, [string]$PythonPath, [string]$OllamaPath, [string]$NvidiaSmiPath)
    foreach ($name in @("uuid", "name", "vbios_version", "driver_version", "pci_bus_id")) {
        if ([string]$Control.gpu.$name -cne [string]$Gpu.$name) { throw "thermal control GPU $name identity differs" }
    }
    if ($Control.model.name -cne $ModelName -or [double]$Control.power.target_watts -ne 90 -or [double]$Control.power.default_watts -ne 115) {
        throw "thermal control model or power identity differs"
    }
    if ([int]$Control.workload.workers -ne 2 -or [int]$Control.workload.sustained_seconds -ne 900) {
        throw "thermal control workload identity differs"
    }
    foreach ($runtime in @(
        @{ name = "python"; path = $PythonPath },
        @{ name = "ollama"; path = $OllamaPath },
        @{ name = "nvidia_smi"; path = $NvidiaSmiPath }
    )) {
        $accepted = $Control.runtime.($runtime.name)
        $resolved = Resolve-FileStrict $runtime.path "selected $($runtime.name) runtime"
        $digest = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($resolved -cne [string]$accepted.path -or $digest -cne [string]$accepted.sha256) {
            throw "thermal control $($runtime.name) runtime identity differs"
        }
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

function Get-DedicatedProcessTree {
    param([int64]$RootPid)
    $snapshot = @(Get-CimInstance Win32_Process)
    $selected = New-Object System.Collections.Generic.List[object]
    $pending = New-Object System.Collections.Generic.Queue[int64]
    $pending.Enqueue($RootPid)
    $seen = @{}
    while ($pending.Count -gt 0) {
        $pidValue = $pending.Dequeue()
        if ($seen.ContainsKey($pidValue)) { continue }
        $seen[$pidValue] = $true
        $row = @($snapshot | Where-Object { [int64]$_.ProcessId -eq $pidValue })
        if ($row.Count -ne 1) { throw "dedicated Ollama process $pidValue is absent or ambiguous" }
        $path = Resolve-FileStrict ([string]$row[0].ExecutablePath) "dedicated Ollama process executable"
        $selected.Add([ordered]@{
            pid = [int64]$row[0].ProcessId
            parent_pid = [int64]$row[0].ParentProcessId
            executable_path = $path
            executable_sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            creation_time = ([DateTimeOffset]$row[0].CreationDate).ToUniversalTime().ToString("o")
        })
        foreach ($child in @($snapshot | Where-Object { [int64]$_.ParentProcessId -eq $pidValue })) {
            $pending.Enqueue([int64]$child.ProcessId)
        }
    }
    return @($selected)
}

function Ensure-OllamaProcessPlacement {
    param([string]$TargetUuid, [array]$ComputeRows, [array]$ProcessTree, [array]$BeforeInventory, [array]$LiveInventory, [double]$ModelVramMiB)
    $ollamaRows = @($ComputeRows | Where-Object { $_.process_name -match "ollama" })
    if (-not $ollamaRows.Count) {
        throw "no Ollama compute process is visible to nvidia-smi"
    }
    $offTarget = @($ollamaRows | Where-Object { $_.gpu_uuid -ne $TargetUuid })
    if ($offTarget.Count) {
        throw "Ollama compute process is visible on non-target GPU(s): $($offTarget | ForEach-Object { $_.gpu_uuid } -join ',')"
    }
    $treePids = @($ProcessTree | ForEach-Object { [int64]$_.pid })
    $onTarget = @($ComputeRows | Where-Object { $_.gpu_uuid -eq $TargetUuid -and $treePids -contains [int64]$_.pid })
    if (-not $onTarget.Count) { throw "target GPU compute process is not a member of the launched Ollama tree" }
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

function Invoke-VerifiedPowerTransition {
    [CmdletBinding()]
    param(
        [double]$TargetW,
        [scriptblock]$Apply,
        [scriptblock]$Observe,
        [string]$Label
    )
    & $Apply $TargetW | Out-Null
    $observed = [double](& $Observe)
    if ([math]::Abs($observed - $TargetW) -gt 0.5) {
        throw "$Label target mismatch: expected $TargetW W, observed $observed W"
    }
    return $observed
}

function Invoke-AnchorCleanup {
    [CmdletBinding()]
    param(
        [scriptblock]$StopProcessTree,
        [scriptblock]$ProcessTreeStopped,
        [scriptblock]$EndpointStopped,
        [scriptblock]$RestoreEnvironment,
        [scriptblock]$EnvironmentRestored,
        [Nullable[double]]$PowerRestoreTarget,
        [scriptblock]$RestorePower,
        [scriptblock]$ObservePower,
        [scriptblock]$HolderHealthy
    )
    $failures = New-Object System.Collections.Generic.List[string]
    $processStopped = $false
    try {
        & $StopProcessTree | Out-Null
        $processStopped = [bool](& $ProcessTreeStopped)
        if (-not $processStopped) { [void]$failures.Add("Ollama process tree remained live") }
    } catch {
        [void]$failures.Add("could not stop Ollama process tree: $($_.Exception.Message)")
    }

    $endpointIsStopped = $false
    try {
        $endpointIsStopped = [bool](& $EndpointStopped)
        if (-not $endpointIsStopped) { [void]$failures.Add("endpoint remained reachable after stop") }
    } catch {
        [void]$failures.Add("endpoint stop verification failed: $($_.Exception.Message)")
    }

    $environmentIsRestored = $false
    try {
        & $RestoreEnvironment | Out-Null
        $environmentIsRestored = [bool](& $EnvironmentRestored)
        if (-not $environmentIsRestored) { [void]$failures.Add("environment state differs after restore") }
    } catch {
        [void]$failures.Add("environment restore failed: $($_.Exception.Message)")
    }

    $powerRestored = ($null -eq $PowerRestoreTarget)
    $powerRestoredTo = $null
    if ($null -ne $PowerRestoreTarget) {
        try {
            $powerRestoredTo = Invoke-VerifiedPowerTransition `
                -TargetW ([double]$PowerRestoreTarget) `
                -Apply $RestorePower `
                -Observe $ObservePower `
                -Label "power-limit restoration"
            $powerRestored = $true
        } catch {
            [void]$failures.Add("power-limit restoration command failed: $($_.Exception.Message)")
        }
    }

    $holderReturned = $false
    try {
        $holderReturned = [bool](& $HolderHealthy)
        if (-not $holderReturned) { [void]$failures.Add("accepted thermal holder did not remain in ordinary control") }
    } catch {
        [void]$failures.Add("accepted thermal holder is not healthy after cleanup: $($_.Exception.Message)")
    }

    return [ordered]@{
        process_tree_stopped = $processStopped
        endpoint_stopped = $endpointIsStopped
        environment_restored = $environmentIsRestored
        power_restored = $powerRestored
        power_restored_to_watts = $powerRestoredTo
        holder_returned = $holderReturned
        failures = @($failures)
    }
}

function Assert-AnchorTransactionOutcome {
    [CmdletBinding()]
    param([string]$PrimaryFailure, $CleanupResult)
    $cleanupFailures = @($CleanupResult.failures)
    if ($PrimaryFailure -or $cleanupFailures.Count -gt 0) {
        $primaryText = if ($PrimaryFailure) { $PrimaryFailure } else { "none" }
        $cleanupText = if ($cleanupFailures.Count) { $cleanupFailures -join "; " } else { "none" }
        throw "transaction refused; primary failure: $primaryText; cleanup failures: $cleanupText"
    }
}

function Invoke-AnchorFailureHarnessScenario {
    [CmdletBinding()]
    param(
        [ValidateSet("power-apply-fails", "power-restore-fails", "holder-preflight-fails", "post-load-primary-cleanup-fails")]
        [string]$Scenario
    )
    $priorEnvironment = [ordered]@{
        OLLAMA_HOST = [ordered]@{ present = $true; value = "prior-host:11434" }
        CUDA_VISIBLE_DEVICES = [ordered]@{ present = $false; value = $null }
        OLLAMA_KEEP_ALIVE = [ordered]@{ present = $true; value = "5m" }
        OLLAMA_VULKAN = [ordered]@{ present = $false; value = $null }
        OLLAMA_SCHED_SPREAD = [ordered]@{ present = $false; value = $null }
    }
    $state = [ordered]@{
        environment = ($priorEnvironment | ConvertTo-Json -Depth 8 | ConvertFrom-Json)
        endpoint_live = $false
        process_tree_live = $false
        power_watts = 115.0
        power_application_attempted = $false
        power_restoration_attempted = $false
        holder_checked_before_model_load = $false
        model_load_attempted = $false
        smoke_pass_emitted = $false
    }
    $primaryFailure = $null
    $powerRestoreTarget = $null
    try {
        $state.holder_checked_before_model_load = $true
        if ($Scenario -eq "holder-preflight-fails") {
            throw "injected thermal holder absent or sensor stale before model load"
        }

        $powerRestoreTarget = 115.0
        $null = Invoke-VerifiedPowerTransition -TargetW 90 -Label "power-limit application" -Apply {
            param($TargetW)
            $state.power_application_attempted = $true
            if ($Scenario -eq "power-apply-fails") { throw "injected 90 W application failure" }
            $state.power_watts = [double]$TargetW
        } -Observe { $state.power_watts }

        $state.environment.OLLAMA_HOST.present = $true
        $state.environment.OLLAMA_HOST.value = "127.0.0.1:11442"
        $state.environment.CUDA_VISIBLE_DEVICES.present = $true
        $state.environment.CUDA_VISIBLE_DEVICES.value = "GPU-fixture"
        $state.environment.OLLAMA_KEEP_ALIVE.present = $true
        $state.environment.OLLAMA_KEEP_ALIVE.value = "10m"
        $state.environment.OLLAMA_VULKAN.present = $true
        $state.environment.OLLAMA_VULKAN.value = "0"
        $state.process_tree_live = $true
        $state.endpoint_live = $true
        $state.model_load_attempted = $true
        if ($Scenario -eq "post-load-primary-cleanup-fails") {
            throw "injected post-load primary failure"
        }
    } catch {
        $primaryFailure = $_.Exception.Message
    } finally {
        $cleanup = Invoke-AnchorCleanup `
            -StopProcessTree {
                $state.process_tree_live = $false
                $state.endpoint_live = $false
            } `
            -ProcessTreeStopped { -not $state.process_tree_live } `
            -EndpointStopped { -not $state.endpoint_live } `
            -RestoreEnvironment {
                $state.environment = ($priorEnvironment | ConvertTo-Json -Depth 8 | ConvertFrom-Json)
            } `
            -EnvironmentRestored {
                (($state.environment | ConvertTo-Json -Depth 8 -Compress) -ceq ($priorEnvironment | ConvertTo-Json -Depth 8 -Compress))
            } `
            -PowerRestoreTarget $powerRestoreTarget `
            -RestorePower {
                param($TargetW)
                $state.power_restoration_attempted = $true
                if ($Scenario -eq "power-restore-fails") { throw "injected 115 W restoration failure" }
                $state.power_watts = [double]$TargetW
            } `
            -ObservePower { $state.power_watts } `
            -HolderHealthy {
                if ($Scenario -eq "post-load-primary-cleanup-fails") {
                    throw "injected holder cleanup verification failure"
                }
                return $true
            }
    }

    $combinedFailure = $null
    try {
        Assert-AnchorTransactionOutcome -PrimaryFailure $primaryFailure -CleanupResult $cleanup
        $state.smoke_pass_emitted = $true
    } catch {
        $combinedFailure = $_.Exception.Message
    }
    return [ordered]@{
        scenario = $Scenario
        smoke_pass_emitted = $state.smoke_pass_emitted
        environment_prior = $priorEnvironment
        environment_after_cleanup = $state.environment
        environment_restored = $cleanup.environment_restored
        endpoint_stopped = $cleanup.endpoint_stopped
        process_tree_stopped = $cleanup.process_tree_stopped
        power_application_attempted = $state.power_application_attempted
        power_restoration_attempted = $state.power_restoration_attempted
        power_restoration_verified = $cleanup.power_restored
        power_after_cleanup_watts = $state.power_watts
        holder_checked_before_model_load = $state.holder_checked_before_model_load
        model_load_attempted = $state.model_load_attempted
        primary_failure = $primaryFailure
        cleanup_failures = @($cleanup.failures)
        combined_failure = $combinedFailure
    }
}

if ($FailureHarnessScenario) {
    Invoke-AnchorFailureHarnessScenario -Scenario $FailureHarnessScenario | ConvertTo-Json -Depth 16
    return
}

if ([string]::IsNullOrWhiteSpace($OutRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "OutRoot is required when LOCALAPPDATA is unavailable"
    }
    $OutRoot = Join-Path $env:LOCALAPPDATA "AXM\anchor-crate-4060-smoke"
}
$OutRoot = [IO.Path]::GetFullPath($OutRoot)

$TierBenchRoot = Resolve-DirectoryStrict $TierBenchRoot "Tier Bench root"
$GradientRoot = Resolve-DirectoryStrict $GradientRoot "Home Lab Gradient root"
$EstateReceipt = Resolve-FileStrict $EstateReceipt "estate receipt"
$EstateObservation = Resolve-FileStrict $EstateObservation "estate observation"
$ControlHostObservation = Resolve-FileStrict $ControlHostObservation "control-host observation"
if (Test-Path -LiteralPath $OutRoot) { throw "output root already exists: $OutRoot" }
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null

Parse-KeepAlive $KeepAlive
$profileId = "W01-RTX4060-MENACE-A17-THERMAL-V1"
$thermalAuthority = Read-ThermalControl $ThermalControlManifest $ExpectedThermalControlManifestSha256
$thermalControl = $thermalAuthority.control
$thermalPublic = Ensure-ThermalReceipt $ThermalProfilePublicReceipt ([string]$thermalControl.receipts.public_sha256) $profileId "public thermal profile receipt"
$thermalPrivate = Ensure-ThermalReceipt $ThermalProfilePrivateReceipt ([string]$thermalControl.receipts.private_sha256) $profileId "private thermal profile receipt"
$thermalCoverage = Ensure-ThermalCoverage $thermalControl
$thermalHolder = Ensure-ThermalHolder $thermalControl

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
$primaryFailure = $null

try {
    $gpuQuery = "uuid,name,vbios_version,memory.total,memory.used,driver_version,pci.bus_id,pstate,power.limit,power.draw,utilization.gpu,power.min_limit,power.max_limit,power.default_limit"
    $inventoryBefore = Query-AllGpuRows -NvidiaSmi $nvidiaSmi -Query $gpuQuery
    $censusUuids = @($control.graphics.nvidia | ForEach-Object { [string]$_.uuid } | Sort-Object)
    $liveUuids = @($inventoryBefore | ForEach-Object { [string]$_.uuid } | Sort-Object)
    if (($censusUuids -join ',') -ne ($liveUuids -join ',')) { throw "live NVIDIA inventory differs from the complete census" }
    $baseGpu = Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery
    if ($baseGpu.Count -ne 1) { throw "could not locate target GPU in nvidia-smi query" }
    $baseGpu = $baseGpu[0]
    Ensure-ThermalControlIdentity -Control $thermalControl -Gpu $baseGpu -ModelName $Model -PythonPath $python -OllamaPath $ollama -NvidiaSmiPath $nvidiaSmi
    $powerBefore = [double]$baseGpu.power_limit_watts
    Ensure-PowerLimits -Row $baseGpu -TargetW $TargetPowerLimitW
    $powerLimitRestore = 115

    $powerAfter = Invoke-VerifiedPowerTransition -TargetW $TargetPowerLimitW -Label "power-limit application" -Apply {
        param($TargetW)
        Set-PowerLimit -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -TargetW $TargetW
    } -Observe {
        (Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery)[0].power_limit_watts
    }

    $env:OLLAMA_HOST = $ollamaHost
    $env:CUDA_VISIBLE_DEVICES = $GpuUuid
    $env:OLLAMA_VULKAN = "0"
    $env:OLLAMA_KEEP_ALIVE = $KeepAlive
    Remove-Item Env:OLLAMA_SCHED_SPREAD -ErrorAction SilentlyContinue
    $server = Start-Process -FilePath $ollama -ArgumentList @("serve") -PassThru -WindowStyle Hidden
    if ($server -eq $null -or $server.HasExited) { throw "failed to start dedicated Ollama server" }

    $version = Wait-Ollama -BaseUrl $Endpoint
    if ([string]$thermalControl.runtime.ollama_version -cne [string]$version.version) { throw "live Ollama version differs from thermal control manifest" }
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
    if ([string]$thermalControl.model.digest -cne $modelDigest) { throw "live model digest differs from thermal control manifest" }

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
    $processTree = Get-DedicatedProcessTree -RootPid $server.Id
    Ensure-OllamaProcessPlacement -TargetUuid $GpuUuid -ComputeRows $computeRows -ProcessTree $processTree -BeforeInventory $inventoryBefore -LiveInventory $inventoryLive -ModelVramMiB ([double]$loadedModel[0].size_vram / 1MB)

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
        [ordered]@{ id = "thermal-profile-bound"; pass = ($thermalPublic.observed_sha256 -eq $thermalPublic.controlling_sha256 -and $thermalPrivate.observed_sha256 -eq $thermalPrivate.controlling_sha256); detail = $profileId },
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
            public_receipt_sha256 = $thermalPublic.observed_sha256
            private_receipt_sha256 = $thermalPrivate.observed_sha256
            public_receipt_controlling_sha256 = $thermalPublic.controlling_sha256
            private_receipt_controlling_sha256 = $thermalPrivate.controlling_sha256
            control_manifest = $thermalAuthority.path
            control_manifest_observed_sha256 = $thermalAuthority.observed_sha256
            control_manifest_expected_sha256 = $thermalAuthority.controlling_sha256
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
            executable_sha256 = (Get-FileHash -LiteralPath $ollama -Algorithm SHA256).Hash.ToLowerInvariant()
            creation_time = @($processTree | Where-Object { $_.pid -eq $server.Id })[0].creation_time
            process_tree = $processTree
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
        "--thermal-control-manifest", $thermalAuthority.path,
        "--expected-thermal-control-manifest-sha256", $thermalAuthority.controlling_sha256,
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
} catch {
    $primaryFailure = $_
} finally {
    $cleanupResult = Invoke-AnchorCleanup `
        -StopProcessTree {
            if ($server -and -not $server.HasExited) {
            Stop-OllamaServer -Process $server
            $server.WaitForExit(10000) | Out-Null
            }
        } `
        -ProcessTreeStopped { (-not $server) -or $server.HasExited } `
        -EndpointStopped { Assert-EndpointStopped -BaseUrl $Endpoint } `
        -RestoreEnvironment { Restore-EnvironmentState -State $originalEnv } `
        -EnvironmentRestored { Test-EnvironmentState -State $originalEnv } `
        -PowerRestoreTarget $powerLimitRestore `
        -RestorePower {
            param($TargetW)
            if (-not (Test-Path -LiteralPath $nvidiaSmi)) { throw "nvidia-smi is unavailable" }
            Set-PowerLimit -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -TargetW $powerLimitRestore
        } `
        -ObservePower { (Query-GpuRows -NvidiaSmi $nvidiaSmi -TargetUuid $GpuUuid -Query $gpuQuery)[0].power_limit_watts } `
        -HolderHealthy {
            $holderAfter = Ensure-ThermalHolder $thermalControl
            return $holderAfter.active -and $holderAfter.pid -eq $thermalHolder.pid
        }
    $cleanupFailures = @($cleanupResult.failures)
    $cleanupReceipt = [ordered]@{
        schema = "tier-bench/anchor-4060-cleanup-result@1"
        status = if ($cleanupFailures.Count -eq 0 -and $null -eq $primaryFailure) { "PASS" } else { "REFUSED" }
        generated_at = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        primary_failure = if ($primaryFailure) {
            [ordered]@{ type = $primaryFailure.Exception.GetType().FullName; message = $primaryFailure.Exception.Message }
        } else { $null }
        endpoint_stopped = $cleanupResult.endpoint_stopped
        process_tree_stopped = $cleanupResult.process_tree_stopped
        environment_restored = $cleanupResult.environment_restored
        power_restored = $cleanupResult.power_restored
        power_restored_to_watts = $cleanupResult.power_restored_to_watts
        holder_returned = $cleanupResult.holder_returned
        failures = @($cleanupFailures)
    }
    Write-Utf8NoBomJson (Join-Path $OutRoot "cleanup-result.json") $cleanupReceipt
}

$primaryText = if ($primaryFailure) { $primaryFailure.Exception.Message } else { $null }
Assert-AnchorTransactionOutcome -PrimaryFailure $primaryText -CleanupResult $cleanupResult

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
        thermal_profile_public_observed = $thermalPublic.observed_sha256
        thermal_profile_public_controlling = $thermalPublic.controlling_sha256
        thermal_profile_private_observed = $thermalPrivate.observed_sha256
        thermal_profile_private_controlling = $thermalPrivate.controlling_sha256
        thermal_control_manifest_observed = $thermalAuthority.observed_sha256
        thermal_control_manifest_controlling = $thermalAuthority.controlling_sha256
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
