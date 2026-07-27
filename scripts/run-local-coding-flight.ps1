[CmdletBinding()]
param(
    [ValidateSet("smoke", "core", "adversarial")]
    [string]$Profile = "smoke",

    [string]$GpuUuid,
    [string]$UtilityGpuUuid,
    [int]$Port = 11439,
    [int]$ContextLength = 32768,
    [double]$MinGpuResidency = 0.95,
    [double]$MinWorkerDeltaMiB = 4096,
    [double]$MaxUtilityDeltaMiB = 1536,
    [int]$CallTimeoutSeconds = 900,
    [string]$OutputRoot = "D:\TierRuns\LocalCoding",
    [string]$Python = "python",
    [string]$Ollama = "ollama",
    [string]$Claude = "claude",
    [string]$NvidiaSmi = "nvidia-smi",
    [switch]$PullMissing,
    [switch]$KeepServer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ContextLength -le 0) { throw "ContextLength must be positive." }
if ($CallTimeoutSeconds -le 0) { throw "CallTimeoutSeconds must be positive." }
if ($MinGpuResidency -lt 0 -or $MinGpuResidency -gt 1) {
    throw "MinGpuResidency must be between zero and one."
}
if ($MinWorkerDeltaMiB -lt 0 -or $MaxUtilityDeltaMiB -lt 0) {
    throw "GPU memory thresholds must be non-negative."
}

$RequiredModels = @(
    "gpt-oss:20b",
    "qwen3-coder:30b",
    "devstral-small-2:24b"
)

function Resolve-Executable([string]$Name) {
    $command = Get-Command $Name -ErrorAction Stop
    if (-not $command.Source) {
        throw "Cannot resolve executable path for $Name"
    }
    return $command.Source
}

function Get-GpuInventory([string]$Executable) {
    $lines = & $Executable `
        --query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu `
        --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0) {
        throw "nvidia-smi inventory failed with exit code $LASTEXITCODE"
    }
    $rows = @()
    foreach ($line in $lines) {
        $parts = $line -split ",", 6
        if ($parts.Count -ne 6) { continue }
        $rows += [ordered]@{
            index = [int]$parts[0].Trim()
            uuid = $parts[1].Trim()
            name = $parts[2].Trim()
            memory_total_mib = [double]$parts[3].Trim()
            memory_used_mib = [double]$parts[4].Trim()
            utilization_percent = [double]$parts[5].Trim()
        }
    }
    if ($rows.Count -eq 0) {
        throw "nvidia-smi returned no GPU rows"
    }
    return $rows
}

function Invoke-OllamaJson([string]$BaseUrl, [string]$Path, [string]$Method = "GET", $Body = $null) {
    $parameters = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = ($Body | ConvertTo-Json -Depth 20 -Compress)
    }
    return Invoke-RestMethod @parameters
}

function Set-LaunchEnvironment([System.Collections.IDictionary]$Values) {
    $previous = @{}
    foreach ($key in $Values.Keys) {
        $item = Get-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        $previous[$key] = if ($null -eq $item) { $null } else { $item.Value }
        Set-Item -Path "Env:$key" -Value ([string]$Values[$key])
    }
    return $previous
}

function Restore-LaunchEnvironment([System.Collections.IDictionary]$Previous) {
    foreach ($key in $Previous.Keys) {
        if ($null -eq $Previous[$key]) {
            Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$key" -Value ([string]$Previous[$key])
        }
    }
}


function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

$PythonPath = Resolve-Executable $Python
$OllamaPath = Resolve-Executable $Ollama
$ClaudePath = Resolve-Executable $Claude
$NvidiaSmiPath = Resolve-Executable $NvidiaSmi
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BaseUrl = "http://127.0.0.1:$Port"
$HostValue = "127.0.0.1:$Port"
$Inventory = @(Get-GpuInventory $NvidiaSmiPath)

if (-not $GpuUuid) {
    $workers = @($Inventory | Where-Object { $_.name -match "RTX\s+3090" })
    if ($workers.Count -ne 1) {
        throw "Specify -GpuUuid. Automatic selection requires exactly one RTX 3090, found $($workers.Count)."
    }
    $GpuUuid = $workers[0].uuid
}
$Worker = @($Inventory | Where-Object { $_.uuid -eq $GpuUuid })
if ($Worker.Count -ne 1) {
    throw "Worker GPU UUID $GpuUuid was not found in nvidia-smi inventory."
}
if ($Worker[0].name -notmatch "RTX\s+3090") {
    throw "Worker GPU $GpuUuid is $($Worker[0].name), not the expected RTX 3090."
}

if (-not $UtilityGpuUuid) {
    $utilities = @($Inventory | Where-Object { $_.name -match "RTX\s+4060" })
    if ($utilities.Count -eq 1) {
        $UtilityGpuUuid = $utilities[0].uuid
    }
}
if ($UtilityGpuUuid) {
    $Utility = @($Inventory | Where-Object { $_.uuid -eq $UtilityGpuUuid })
    if ($Utility.Count -ne 1) {
        throw "Utility GPU UUID $UtilityGpuUuid was not found in nvidia-smi inventory."
    }
    if ($UtilityGpuUuid -eq $GpuUuid) {
        throw "Worker and utility GPU UUIDs must be different."
    }
}

try {
    Invoke-OllamaJson $BaseUrl "/api/version" | Out-Null
    throw "A server is already listening at $BaseUrl. Refusing to reuse an unattested process."
}
catch {
    if ($_.Exception.Message -like "A server is already listening*") { throw }
}

$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BootstrapDir = Join-Path $OutputRoot "bootstrap-$Stamp"
New-Item -ItemType Directory -Path $BootstrapDir -Force | Out-Null
$StdoutLog = Join-Path $BootstrapDir "ollama-server.stdout.log"
$StderrLog = Join-Path $BootstrapDir "ollama-server.stderr.log"
$AttestationPath = Join-Path $BootstrapDir "ollama-server-attestation.json"
$LauncherOutput = Join-Path $BootstrapDir "tiercode-output.json"
$CloseoutPath = Join-Path $BootstrapDir "launcher-closeout.json"

$LaunchEnvironment = [ordered]@{
    CUDA_VISIBLE_DEVICES = $GpuUuid
    OLLAMA_HOST = $HostValue
    OLLAMA_CONTEXT_LENGTH = [string]$ContextLength
    OLLAMA_FLASH_ATTENTION = "1"
    OLLAMA_KV_CACHE_TYPE = "q8_0"
    OLLAMA_NUM_PARALLEL = "1"
    OLLAMA_MAX_LOADED_MODELS = "1"
    OLLAMA_KEEP_ALIVE = "30m"
}

$PreviousEnvironment = Set-LaunchEnvironment $LaunchEnvironment
$Server = $null
try {
    $Server = Start-Process `
        -FilePath $OllamaPath `
        -ArgumentList @("serve") `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog
}
finally {
    Restore-LaunchEnvironment $PreviousEnvironment
}

$PythonExit = 2
$ReportPath = $null
$ReportSha256 = $null
try {
    $Deadline = (Get-Date).AddSeconds(90)
    $Version = $null
    while ((Get-Date) -lt $Deadline) {
        if ($Server.HasExited) {
            throw "The dedicated Ollama server exited with code $($Server.ExitCode). See $StderrLog"
        }
        try {
            $Version = Invoke-OllamaJson $BaseUrl "/api/version"
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if ($null -eq $Version) {
        throw "The dedicated Ollama server did not become healthy at $BaseUrl"
    }

    $Tags = Invoke-OllamaJson $BaseUrl "/api/tags"
    $Installed = @{}
    foreach ($model in @($Tags.models)) {
        if ($model.name) { $Installed[[string]$model.name] = $true }
        if ($model.model) { $Installed[[string]$model.model] = $true }
    }
    $Missing = @($RequiredModels | Where-Object { -not $Installed.ContainsKey($_) })
    if ($Missing.Count -gt 0 -and -not $PullMissing) {
        $pulls = ($Missing | ForEach-Object { "ollama pull $_" }) -join "; "
        throw "Missing required models: $($Missing -join ', '). Re-run with -PullMissing or execute: $pulls"
    }
    if ($Missing.Count -gt 0) {
        $oldHost = Get-Item Env:OLLAMA_HOST -ErrorAction SilentlyContinue
        try {
            $env:OLLAMA_HOST = $HostValue
            foreach ($model in $Missing) {
                & $OllamaPath pull $model
                if ($LASTEXITCODE -ne 0) {
                    throw "ollama pull $model failed with exit code $LASTEXITCODE"
                }
            }
        }
        finally {
            if ($null -eq $oldHost) { Remove-Item Env:OLLAMA_HOST -ErrorAction SilentlyContinue }
            else { $env:OLLAMA_HOST = $oldHost.Value }
        }
    }

    $ExecutableHash = (Get-FileHash -Algorithm SHA256 -Path $OllamaPath).Hash.ToLowerInvariant()
    $Attestation = [ordered]@{
        schema = "tier-bench/ollama-server-attestation@1"
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        ollama_host = $BaseUrl
        ollama_version = [string]$Version.version
        server_pid = [int]$Server.Id
        executable_path = $OllamaPath
        executable_sha256 = $ExecutableHash
        gpu_uuid = $GpuUuid
        gpu_name = [string]$Worker[0].name
        gpu_memory_total_mib = [double]$Worker[0].memory_total_mib
        utility_gpu_uuid = $UtilityGpuUuid
        context_length = [int]$ContextLength
        launch_environment = $LaunchEnvironment
        gpu_inventory = $Inventory
        server_stdout = $StdoutLog
        server_stderr = $StderrLog
    }
    Write-Utf8NoBom $AttestationPath ($Attestation | ConvertTo-Json -Depth 20)

    $Server.Refresh()
    if ($Server.HasExited) {
        throw "The dedicated Ollama server exited before the flight with code $($Server.ExitCode)."
    }

    $Arguments = @(
        "-m", "tier_runner.local_coding_flight", "run",
        "--ollama-host", $BaseUrl,
        "--server-attestation", $AttestationPath,
        "--claude-bin", $ClaudePath,
        "--context-length", [string]$ContextLength,
        "--min-gpu-residency", [string]$MinGpuResidency,
        "--profile", $Profile,
        "--output-root", $OutputRoot,
        "--worker-gpu-uuid", $GpuUuid,
        "--nvidia-smi", $NvidiaSmiPath,
        "--min-worker-delta-mib", [string]$MinWorkerDeltaMiB,
        "--max-utility-delta-mib", [string]$MaxUtilityDeltaMiB,
        "--call-timeout-seconds", [string]$CallTimeoutSeconds
    )
    if ($UtilityGpuUuid) {
        $Arguments += @("--utility-gpu-uuid", $UtilityGpuUuid)
    }

    Push-Location $RepoRoot
    try {
        $RawOutput = & $PythonPath @Arguments 2>&1 | Out-String
        $PythonExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    Write-Utf8NoBom $LauncherOutput $RawOutput
    Write-Output $RawOutput

    try {
        $Parsed = $RawOutput | ConvertFrom-Json
        if ($Parsed.report_path) {
            $ReportPath = [string]$Parsed.report_path
            if (Test-Path $ReportPath) {
                $ReportSha256 = (Get-FileHash -Algorithm SHA256 -Path $ReportPath).Hash.ToLowerInvariant()
            }
        }
    }
    catch {
        # The raw output is preserved even when the Python command fails before emitting JSON.
    }

    $Server.Refresh()
    $FinalInventory = @(Get-GpuInventory $NvidiaSmiPath)
    $ServerExitCode = $null
    if ($Server.HasExited) {
        $ServerExitCode = [int]$Server.ExitCode
    }
    $AttestationSha256 = (
        Get-FileHash -Algorithm SHA256 -Path $AttestationPath
    ).Hash.ToLowerInvariant()
    $Closeout = [ordered]@{
        schema = "tier-bench/local-coding-launcher-closeout@1"
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        python_exit_code = [int]$PythonExit
        server_attestation_path = $AttestationPath
        server_attestation_sha256 = $AttestationSha256
        flight_report_path = $ReportPath
        flight_report_sha256 = $ReportSha256
        final_gpu_inventory = $FinalInventory
        server_pid = [int]$Server.Id
        server_has_exited = [bool]$Server.HasExited
        server_exit_code = $ServerExitCode
        server_kept = [bool]$KeepServer
        call_timeout_seconds = [int]$CallTimeoutSeconds
    }
    Write-Utf8NoBom $CloseoutPath ($Closeout | ConvertTo-Json -Depth 20)
}
finally {
    if ($null -ne $Server -and -not $KeepServer -and -not $Server.HasExited) {
        Stop-ProcessTree $Server.Id
    }
}

Write-Host "Server attestation: $AttestationPath"
Write-Host "Launcher closeout:   $CloseoutPath"
if ($ReportPath) { Write-Host "Flight report:       $ReportPath" }
exit $PythonExit
