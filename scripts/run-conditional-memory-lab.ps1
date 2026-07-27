[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$Lab,
    [ValidateSet("smoke", "canary", "full")]
    [string]$Profile = "smoke",
    [string]$StateDir = "D:\TierRuns\ConditionalMemory",
    [string]$FlightRoot,
    [string]$Python = "python",
    [string]$Gpu3090AUuid,
    [string]$Gpu3090BUuid,
    [string]$Gpu4060Uuid,
    [switch]$ForceCpu
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-CommandLineArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append('"')
    $Backslashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') {
            $Backslashes += 1
            continue
        }
        if ($Character -eq '"') {
            [void]$Builder.Append(('\' * ($Backslashes * 2 + 1)))
            [void]$Builder.Append('"')
            $Backslashes = 0
            continue
        }
        if ($Backslashes) {
            [void]$Builder.Append(('\' * $Backslashes))
            $Backslashes = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($Backslashes) {
        [void]$Builder.Append(('\' * ($Backslashes * 2)))
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Start-TierProcess {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Stdout,
        [Parameter(Mandatory = $true)][string]$Stderr
    )
    $ArgumentLine = ($Arguments | ForEach-Object { ConvertTo-CommandLineArgument $_ }) -join " "
    return Start-Process `
        -FilePath $Python `
        -ArgumentList $ArgumentLine `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -NoNewWindow `
        -PassThru
}

function Invoke-TierProcess {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Stdout,
        [Parameter(Mandatory = $true)][string]$Stderr
    )
    $Process = Start-TierProcess -Arguments $Arguments -Stdout $Stdout -Stderr $Stderr
    $Process.WaitForExit()
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) {
        $ErrorText = if (Test-Path $Stderr) { Get-Content $Stderr -Raw } else { "" }
        throw "Tier process failed with exit code $($Process.ExitCode): $ErrorText"
    }
    return $Process
}

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not $Lab) {
    $Lab = Join-Path $RepoRoot "experiments\conditional_memory\lab.example.json"
}
$Lab = (Resolve-Path $Lab).Path

if ($Gpu3090AUuid) { $env:TIER_GPU_3090_A_UUID = $Gpu3090AUuid }
if ($Gpu3090BUuid) { $env:TIER_GPU_3090_B_UUID = $Gpu3090BUuid }
if ($Gpu4060Uuid) { $env:TIER_GPU_4060_UUID = $Gpu4060Uuid }

if (-not $ForceCpu) {
    foreach ($Name in @(
        "TIER_GPU_3090_A_UUID",
        "TIER_GPU_3090_B_UUID",
        "TIER_GPU_4060_UUID"
    )) {
        $Value = [Environment]::GetEnvironmentVariable($Name)
        if (-not $Value) {
            throw "$Name is required. Bind the exact nvidia-smi GPU UUID before the flight."
        }
    }
}

if (-not $FlightRoot) {
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $FlightRoot = Join-Path $StateDir "flights\$Stamp-$Profile"
}
$FlightRoot = [System.IO.Path]::GetFullPath($FlightRoot)
$InvocationId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$TrialState = Join-Path $FlightRoot "state"
$PlanPath = Join-Path $FlightRoot "plan.json"
$ReportPath = Join-Path $FlightRoot "report-$InvocationId.json"
$StatusPath = Join-Path $FlightRoot "status-$InvocationId.json"
$StopFile = Join-Path $FlightRoot "monitor-$InvocationId.stop"
$MonitorPath = Join-Path $FlightRoot "hardware-monitor-$InvocationId.jsonl"
New-Item -ItemType Directory -Path $FlightRoot -Force | Out-Null
New-Item -ItemType Directory -Path $TrialState -Force | Out-Null
if (Test-Path $StopFile) { Remove-Item $StopFile -Force }

$Module = "tier_runner.conditional_memory_cli"
if (Test-Path $PlanPath) {
    Invoke-TierProcess `
        -Arguments @("-m", $Module, "verify-plan", "--lab", $Lab, "--plan", $PlanPath) `
        -Stdout (Join-Path $FlightRoot "$InvocationId-verify-plan.stdout.log") `
        -Stderr (Join-Path $FlightRoot "$InvocationId-verify-plan.stderr.log") | Out-Null
} else {
    Invoke-TierProcess `
        -Arguments @(
            "-m", $Module, "plan", "--lab", $Lab, "--profile", $Profile,
            "--out", $PlanPath
        ) `
        -Stdout (Join-Path $FlightRoot "$InvocationId-plan.stdout.log") `
        -Stderr (Join-Path $FlightRoot "$InvocationId-plan.stderr.log") | Out-Null
}

$Plan = Get-Content $PlanPath -Raw | ConvertFrom-Json
if ($Plan.profile -ne $Profile) {
    throw "Frozen plan profile '$($Plan.profile)' does not match requested profile '$Profile'."
}
$SeatIds = @($Plan.resolved.topology.seats | ForEach-Object { $_.id })
if ($SeatIds.Count -lt 1) {
    throw "The frozen plan contains no execution seats."
}

$MonitorProcess = $null
$Workers = @()
try {
    if (-not $ForceCpu) {
        Invoke-TierProcess `
            -Arguments @("-m", $Module, "probe", "--out", (Join-Path $FlightRoot "$InvocationId-hardware-probe.json")) `
            -Stdout (Join-Path $FlightRoot "$InvocationId-probe.stdout.log") `
            -Stderr (Join-Path $FlightRoot "$InvocationId-probe.stderr.log") | Out-Null
        $MonitorProcess = Start-TierProcess `
            -Arguments @(
                "-m", $Module, "monitor", "--out", $MonitorPath,
                "--stop-file", $StopFile, "--interval-seconds", "1.0"
            ) `
            -Stdout (Join-Path $FlightRoot "$InvocationId-monitor.stdout.log") `
            -Stderr (Join-Path $FlightRoot "$InvocationId-monitor.stderr.log")
    }

    foreach ($SeatId in $SeatIds) {
        $Arguments = @(
            "-m", $Module, "run-seat", "--lab", $Lab, "--plan", $PlanPath,
            "--seat", $SeatId, "--state-dir", $TrialState, "--stop-on-failure"
        )
        if ($ForceCpu) { $Arguments += "--force-cpu" }
        $SafeSeat = $SeatId -replace '[^A-Za-z0-9_.-]', '-'
        $Workers += [PSCustomObject]@{
            Seat = $SeatId
            Process = Start-TierProcess `
                -Arguments $Arguments `
                -Stdout (Join-Path $FlightRoot "$InvocationId-seat-$SafeSeat.stdout.log") `
                -Stderr (Join-Path $FlightRoot "$InvocationId-seat-$SafeSeat.stderr.log")
        }
    }

    foreach ($Worker in $Workers) {
        $Worker.Process.WaitForExit()
        $Worker.Process.Refresh()
    }
} finally {
    New-Item -ItemType File -Path $StopFile -Force | Out-Null
    if ($MonitorProcess) {
        $MonitorProcess.WaitForExit()
        $MonitorProcess.Refresh()
    }
}

$WorkerFailures = @($Workers | Where-Object { $_.Process.ExitCode -ne 0 })
if ($WorkerFailures.Count) {
    $Names = ($WorkerFailures | ForEach-Object { "$($_.Seat)=$($_.Process.ExitCode)" }) -join ", "
    throw "One or more conditional-memory workers failed: $Names"
}
if ($MonitorProcess -and $MonitorProcess.ExitCode -ne 0) {
    throw "Hardware monitor failed with exit code $($MonitorProcess.ExitCode)."
}

Invoke-TierProcess `
    -Arguments @(
        "-m", $Module, "status", "--lab", $Lab, "--plan", $PlanPath,
        "--state-dir", $TrialState
    ) `
    -Stdout $StatusPath `
    -Stderr (Join-Path $FlightRoot "$InvocationId-status.stderr.log") | Out-Null

Invoke-TierProcess `
    -Arguments @(
        "-m", $Module, "report", "--lab", $Lab, "--plan", $PlanPath,
        "--state-dir", $TrialState, "--out", $ReportPath
    ) `
    -Stdout (Join-Path $FlightRoot "$InvocationId-report.stdout.log") `
    -Stderr (Join-Path $FlightRoot "$InvocationId-report.stderr.log") | Out-Null

$Report = Get-Content $ReportPath -Raw | ConvertFrom-Json
[PSCustomObject]@{
    ok = [bool]$Report.status.ok
    profile = $Profile
    plan_sha256 = $Plan.plan_sha256
    flight_root = $FlightRoot
    report = $ReportPath
    promotable_arms = @($Report.promotable_arms)
    promotion_authorized = [bool]$Report.promotion_authorized
} | ConvertTo-Json -Depth 6
