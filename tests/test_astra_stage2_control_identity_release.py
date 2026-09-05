from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import tempfile
import uuid
from pathlib import Path


class ControlIdentityReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]
        cls.launcher = (
            cls.repo
            / "scripts"
            / "Invoke-AstraStage2ControlIdentityBinding.ps1"
        )
        cls.retry = (
            cls.repo
            / "scripts"
            / "Invoke-AstraStage2CheckpointRetry.ps1"
        )
        cls.retry_text = cls.retry.read_text(encoding="utf-8")
        cls.text = cls.launcher.read_text(encoding="utf-8")

    def _run_transport_harness(
        self,
        shell: Path,
        harness: Path,
        source: Path,
        python_path: Path,
        input_path: Path,
        expectation: str,
        case_name: str,
    ) -> dict[str, object]:
        process = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
                "-Action",
                "Run",
                "-SourcePath",
                str(source),
                "-PythonPath",
                str(python_path),
                "-InputPath",
                str(input_path),
                "-Expectation",
                expectation,
                "-CaseName",
                case_name,
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        expected_exit_code = 0 if expectation == "Success" else 20
        self.assertEqual(
            process.returncode,
            expected_exit_code,
            msg=process.stdout + "\n" + process.stderr,
        )
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                f"transport harness did not emit one JSON object: {exc}\n"
                f"stdout={process.stdout!r}\nstderr={process.stderr!r}"
            )
        self.assertEqual(result["exit_code"], expected_exit_code)
        return result

    def _powershell_identity(
        self,
        shell: Path,
        harness: Path,
    ) -> dict[str, str]:
        process = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
                "-Action",
                "Version",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(
            process.returncode,
            0,
            msg=process.stdout + "\n" + process.stderr,
        )
        result = json.loads(process.stdout)
        self.assertIn(result["edition"], ("Desktop", "Core"))
        self.assertIn(
            result["ps_native_command_argument_passing"],
            ("Legacy", "Standard", "Windows", "LEGACY_UNAVAILABLE"),
        )
        return {
            "version": str(result["version"]),
            "edition": str(result["edition"]),
            "ps_native_command_argument_passing": str(
                result["ps_native_command_argument_passing"]
            ),
        }

    def test_21_launcher_parses_with_terminating_powershell_gate(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell, "PowerShell is required for release qualification")
        environment = dict(os.environ)
        environment["ASTRA_RELEASE_LAUNCHER"] = str(self.launcher)
        command = (
            '$ErrorActionPreference = "Stop"; '
            '$text = Get-Content -Raw -LiteralPath '
            '$env:ASTRA_RELEASE_LAUNCHER; '
            '[void][scriptblock]::Create($text); '
            'Write-Output "POWERSHELL_PARSE_PASS"'
        )
        process = subprocess.run(
            [str(shell), "-NoProfile", "-Command", command],
            cwd=self.repo,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            process.returncode,
            0,
            msg=process.stdout + "\n" + process.stderr,
        )
        self.assertIn("POWERSHELL_PARSE_PASS", process.stdout)

    def test_22_launcher_pins_exact_qualified_binder_and_law(self) -> None:
        for coordinate in (
            "dbb44b7efca1b04f2ed2d8c127af653b278909e4",
            "2671247337030d9c8e281393103104f7436d2800",
            "c36c35bf9b70d879e1e1c9ee2f0296879442df3e",
            "77abe4e177fc61e4f52f56ea64494b113f9662fc",
            "9babad4631ef517485c56ea4906aab123e30fad7",
            "60bca963d63edca267106bc5c7725c2cc1df8dd7",
        ):
            self.assertIn(coordinate, self.text)
        self.assertIn("merge-base --is-ancestor $BinderHead $head", self.text)
        self.assertIn("Assert-CleanWorkTree", self.text)

    def test_23_launcher_pins_all_source_and_checkpoint_coordinates(self) -> None:
        for coordinate in (
            "yingfan-bot/lotus",
            "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
            "CSJianYang/LoopCoder",
            "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
            "yingfanbot/gsm-lotus-llama3b",
            "b392d2cb7aaa73475b93028221523c47f49f66a2",
            "Multilingual-Multimodal-NLP/LoopCoder-V2",
            "b87cf3aa2186937b0d0362a684d7d30f234543e3",
            "yingfanbot/gsm-cot-llama3b",
            "63de1ec1902ed143fe62250b6ddb14cb65f06e1a",
        ):
            self.assertIn(coordinate, self.text)
        self.assertIn("Assert-CheckpointCustody", self.text)
        self.assertIn("*.incomplete", self.text)

    def test_24_launcher_discovers_repo_root_and_preserves_checkout(self) -> None:
        self.assertIn("function Resolve-RepositoryRoot", self.text)
        self.assertIn(
            r"D:\Projects\Measurement\Tier-Bench\main",
            self.text,
        )
        self.assertIn("Join-Path $PSScriptRoot '..'", self.text)
        self.assertIn("function Ensure-BinderWorktree", self.text)
        self.assertRegex(
            self.text,
            re.compile(
                r"'worktree',\s*'add',\s*'--detach',\s*\$Root,\s*\$BinderHead",
                re.MULTILINE,
            ),
        )
        self.assertNotIn("worktree add --force", self.text)

    def test_25_prepare_reuses_or_acquires_assets_without_model_execution(self) -> None:
        self.assertIn("[switch]$SkipDownloads", self.text)
        self.assertIn("Ensure-ExactSource", self.text)
        self.assertIn("Download-ExactSnapshots", self.text)
        self.assertIn("Select-LargestNvidiaDevice", self.text)
        self.assertIn("REUSE_EXISTING_EXACT_ASSETS", self.text)
        self.assertIn(
            "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
            self.text,
        )
        self.assertIn("model_calls = 0", self.text)
        self.assertIn("provider_calls = 0", self.text)
        self.assertIn("tier-bench/astra-stage2-hardware-probe@2", self.text)
        self.assertIn("hardware_probe_receipt_sha256", self.text)
        self.assertIn("topology_evidence_sha256", self.text)
        self.assertIn("topology_platform", self.text)
        self.assertIn("topology_state", self.text)
        self.assertIn("topology_method", self.text)
        self.assertIn("selected_device_indices", self.text)
        self.assertIn("platform_sha256", self.text)
        self.assertIn("device_query_sha256", self.text)
        self.assertIn("payload_sha256", self.text)
        self.assertIn("NOT_APPLICABLE_SINGLE_SELECTED_DEVICE", self.text)
        self.assertIn("PLATFORM_LIMITATION_SINGLE_DEVICE", self.text)
        self.assertIn("NVIDIA_SMI_TOPO_MATRIX", self.text)
        self.assertNotIn("nvidia_topo_matrix", self.text)
        self.assertNotIn("topology_class", self.text)
        self.assertNotIn("topology_path", self.text)
        self.assertNotIn("topology_status_path", self.text)
        self.assertNotRegex(
            self.text,
            re.compile(r"\b(generate|completion|chat\.completions)\s*\(", re.I),
        )

    def test_26_preflight_proves_named_wrapper_import_from_non_binder_cwd(
        self,
    ) -> None:
        self.assertIn("function Invoke-PinnedBinder", self.text)
        binder_block = self.text.split(
            "function Invoke-PinnedBinder {", 1
        )[1].split("function Get-LauncherCoordinates", 1)[0]
        self.assertIn(
            "[Parameter(Mandatory = $true)][hashtable]$Parameters",
            binder_block,
        )
        self.assertIn("& $Wrapper @Parameters", binder_block)
        self.assertNotIn("@Arguments", binder_block)
        self.assertNotIn("[string[]]$Arguments", binder_block)
        self.assertIn("$env:PYTHONPATH = $expectedRoot", binder_block)
        self.assertIn("Push-Location -LiteralPath $expectedRoot", binder_block)
        self.assertIn("Remove-Item Env:PYTHONPATH", binder_block)
        self.assertIn("preflight-binder-import-smoke", self.text)
        self.assertIn("non-binder-cwd", self.text)
        self.assertIn("Command = 'template'", self.text)
        self.assertIn("Out = $smokeTemplate", self.text)
        self.assertNotRegex(
            self.text,
            re.compile(r"Invoke-PinnedBinder[^\n]*-Arguments"),
        )
        for receipt_field in (
            "binder_import_smoke = 'PASS'",
            "binder_execution_cwd = 'PINNED_BINDER_ROOT'",
            "binder_pythonpath = 'PINNED_BINDER_ROOT'",
            "binder_caller_cwd = 'DELIBERATELY_NON_BINDER'",
            "downloads_performed = $false",
            "actual_executable_control_identities = 'UNBOUND'",
        ):
            self.assertIn(receipt_field, self.text)

    def test_27_bind_refuses_unbound_runtime_and_uses_named_wrapper_parameters(
        self,
    ) -> None:
        self.assertIn("function Assert-BindReady", self.text)
        self.assertIn("Runtime identity is still unbound", self.text)
        self.assertIn('["--effort","low"]', self.text)
        self.assertIn('["--effort","high"]', self.text)
        self.assertIn("Bind is refused", self.text)
        for command in (
            "Command = 'probe-hardware'",
            "Command = 'inventory'",
            "Command = 'validate-config'",
            "Command = 'bind'",
            "Command = 'verify'",
        ):
            self.assertIn(command, self.text)
        self.assertGreaterEqual(self.text.count("Invoke-PinnedBinder"), 7)
        self.assertGreaterEqual(self.text.count("-Parameters @{"), 7)
        self.assertNotRegex(
            self.text,
            re.compile(r"Invoke-PinnedBinder[^\n]*-Arguments"),
        )


    def test_28_retry_digest_match_and_mismatch_paths(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell, "PowerShell is required for release qualification")
        with tempfile.TemporaryDirectory(prefix="astra-digest-test-") as temporary:
            target = Path(temporary) / "payload.bin"
            target.write_bytes(b"exact execution bytes\n")
            expected = hashlib.sha256(target.read_bytes()).hexdigest()
            common = [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.retry),
                "-Command",
                "CheckDigest",
                "-Path",
                str(target),
                "-ExpectedSha256",
            ]
            matched = subprocess.run(
                [*common, expected],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                matched.returncode,
                0,
                msg=matched.stdout + "\n" + matched.stderr,
            )
            self.assertIn("DIGEST_MATCH", matched.stdout)

            mismatched = subprocess.run(
                [*common, "0" * 64],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertNotEqual(mismatched.returncode, 0)
            self.assertIn(
                "Digest mismatch",
                mismatched.stdout + "\n" + mismatched.stderr,
            )
        self.assertIn("if (($observed) -ne $Expected.ToLowerInvariant())", self.retry_text)
        self.assertNotIn(
            "if (Get-Sha256 $launcher -ne $ExpectedLauncherSha256)",
            self.retry_text,
        )

    def test_29_astra_powershell_bytes_ignore_autocrlf(self) -> None:
        payloads = (
            Path("scripts/Invoke-AstraStage2ControlIdentityBinding.ps1"),
            Path("scripts/Invoke-AstraStage2CheckpointRetry.ps1"),
            Path("scripts/astra_stage2_bind_controls.ps1"),
        )

        def run_git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
            process = subprocess.run(
                ["git", *arguments],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                process.returncode,
                0,
                msg=process.stdout + "\n" + process.stderr,
            )
            return process

        with tempfile.TemporaryDirectory(prefix="astra-autocrlf-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            shutil.copy2(self.repo / ".gitattributes", source / ".gitattributes")
            (source / "scripts").mkdir()
            for relative in payloads:
                shutil.copy2(self.repo / relative, source / relative)

            run_git("init", cwd=source)
            run_git("config", "user.name", "Astra Qualification", cwd=source)
            run_git(
                "config",
                "user.email",
                "astra-qualification.invalid",
                cwd=source,
            )
            run_git("config", "commit.gpgsign", "false", cwd=source)
            run_git("add", "--", ".gitattributes", "scripts", cwd=source)
            run_git("commit", "-m", "fixture", cwd=source)
            checkouts: dict[str, Path] = {}
            for setting in ("true", "false"):
                destination = root / f"autocrlf-{setting}"
                destination.mkdir()
                run_git("init", cwd=destination)
                run_git("config", "core.autocrlf", setting, cwd=destination)
                run_git("remote", "add", "origin", str(source), cwd=destination)
                run_git("fetch", "--no-tags", "origin", "HEAD", cwd=destination)
                run_git("checkout", "--detach", "FETCH_HEAD", cwd=destination)
                self.assertEqual(
                    run_git("status", "--porcelain", cwd=destination).stdout,
                    "",
                )
                checkouts[setting] = destination

            for relative in payloads:
                true_bytes = (checkouts["true"] / relative).read_bytes()
                false_bytes = (checkouts["false"] / relative).read_bytes()
                self.assertEqual(
                    hashlib.sha256(true_bytes).hexdigest(),
                    hashlib.sha256(false_bytes).hexdigest(),
                    msg=f"autocrlf changed {relative}",
                )
                self.assertNotIn(
                    b"\r\n",
                    true_bytes,
                    msg=f"LF rule did not control {relative}",
                )

    def test_30_canonical_payload_digest_survives_native_powershell_argument_transport(
        self,
    ) -> None:
        self.assertIn("[System.IO.FileMode]::CreateNew", self.text)
        self.assertIn("& $Python -B $createdScriptPath $Path", self.text)
        self.assertNotIn("& $Python -c $program $Path", self.text)
        harness_text = r'''param(
    [ValidateSet('Version', 'Run')][string]$Action = 'Run',
    [string]$SourcePath,
    [string]$PythonPath,
    [string]$InputPath,
    [ValidateSet('Success', 'Failure')][string]$Expectation = 'Success',
    [string]$CaseName = 'unnamed'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# The fixture JSON is transported as UTF-8 on both PowerShell editions.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

if ($Action -eq 'Version') {
    $edition = if ($PSVersionTable.ContainsKey('PSEdition')) {
        [string]$PSVersionTable['PSEdition']
    } else {
        'Desktop'
    }
    $nativeArgumentPassing = if ($null -ne (Get-Variable `
        -Name PSNativeCommandArgumentPassing -ErrorAction SilentlyContinue)) {
        [string]$PSNativeCommandArgumentPassing
    } else {
        'LEGACY_UNAVAILABLE'
    }
    [ordered]@{
        version = $PSVersionTable.PSVersion.ToString()
        edition = $edition
        ps_native_command_argument_passing = $nativeArgumentPassing
    } | ConvertTo-Json -Compress
    exit 0
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $SourcePath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "Launcher parse failed: $($parseErrors[0].Message)"
}
$matches = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-CanonicalPayloadSha256'
}, $true))
if ($matches.Count -ne 1) {
    throw "Expected one canonical payload function, found $($matches.Count)"
}
$functionText = $matches[0].Extent.Text
$utf8 = New-Object System.Text.UTF8Encoding($false)
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $functionSha256 = ([System.BitConverter]::ToString(
        $sha.ComputeHash($utf8.GetBytes($functionText))
    )).Replace('-', '').ToLowerInvariant()
}
finally {
    $sha.Dispose()
}

$Python = $PythonPath
if ($CaseName -eq 'preference_restore') {
    $ErrorActionPreference = 'SilentlyContinue'
}
$beforePreference = [string]$ErrorActionPreference
$tempRoot = [System.IO.Path]::GetTempPath()
$beforeNames = @{}
Get-ChildItem -LiteralPath $tempRoot -Filter 'astra-canonical-payload-*' |
    ForEach-Object { $beforeNames[$_.FullName] = $true }
$invokeText = $functionText + "`n" +
    'Get-CanonicalPayloadSha256 -Path $InputPath'
$scriptBlock = [scriptblock]::Create($invokeText)
$output = @()
$message = $null
$threw = $false
try {
    $output = @(& $scriptBlock)
}
catch {
    $threw = $true
    $message = $_.Exception.Message
}
$afterPreference = [string]$ErrorActionPreference
$newItems = @(Get-ChildItem -LiteralPath $tempRoot -Filter 'astra-canonical-payload-*' |
    Where-Object { -not $beforeNames.ContainsKey($_.FullName) })
$cleanupRefused = ($CaseName -eq 'cleanup_error' -and $threw -and
    $message -like '*temporary script cleanup failed*')
if ($CaseName -eq 'cleanup_error') {
    foreach ($item in $newItems) {
        if ($item.PSIsContainer) {
            Remove-Item -Recurse -Force -LiteralPath $item.FullName
        } else {
            Remove-Item -Force -LiteralPath $item.FullName
        }
    }
}

if ($beforePreference -ne $afterPreference) {
    throw "ErrorActionPreference changed from $beforePreference to $afterPreference"
}
if ($Expectation -eq 'Success' -and $threw) {
    throw "Expected success for ${CaseName}: $message"
}
if ($Expectation -eq 'Failure' -and -not $threw) {
    throw "Expected failure for $CaseName"
}
if ($Expectation -eq 'Failure' -and
    $message -notlike '*Canonical payload hashing failed*') {
    throw "Failure lacked launcher-owned message for ${CaseName}: $message"
}
if ($CaseName -ne 'cleanup_error' -and $newItems.Count -ne 0) {
    throw "Temporary script residue remained for $CaseName"
}
if ($CaseName -eq 'cleanup_error' -and -not $cleanupRefused) {
    throw 'Cleanup error did not fail closed'
}

$harnessExitCode = if ($threw) { 20 } else { 0 }
[ordered]@{
    case = $CaseName
    outcome = if ($threw) { 'REFUSED' } else { 'PASS' }
    exit_code = $harnessExitCode
    output = @($output | ForEach-Object { [string]$_ })
    message = $message
    function_sha256 = $functionSha256
    error_action_preference_restored = ($beforePreference -eq $afterPreference)
    temporary_script_cleanup = if ($CaseName -eq 'cleanup_error') {
        'ERROR_REFUSED'
    } else {
        'PASS'
    }
} | ConvertTo-Json -Depth 8 -Compress
exit $harnessExitCode
'''

        root = Path(tempfile.gettempdir()) / (
            "astra canonical transport test " + uuid.uuid4().hex
        )
        root.mkdir()
        try:
            harness = root / "invoke extracted function.ps1"
            harness.write_text(harness_text, encoding="utf-8", newline="\n")

            valid = root / "fixture path with spaces é" / "reordered payload.json"
            valid.parent.mkdir()
            valid_value = {
                "zeta": {"second": [3, {"snowman": "☃"}], "first": True},
                "payload_sha256": "f" * 64,
                "alpha": "café",
                "count": 7,
            }
            valid.write_text(
                json.dumps(valid_value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            independently_canonical = dict(valid_value)
            independently_canonical.pop("payload_sha256")
            expected_digest = hashlib.sha256(
                json.dumps(
                    independently_canonical,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()

            malformed = root / "malformed payload.json"
            malformed.write_text('{"broken": ]\n', encoding="utf-8", newline="\n")
            nonfinite = root / "nonfinite payload.json"
            nonfinite.write_text(
                '{"payload_sha256":"ignored","value":NaN}\n',
                encoding="utf-8",
                newline="\n",
            )
            missing_input = root / "missing payload.json"
            missing_interpreter = root / "missing python executable"

            fake_paths: dict[str, Path] = {}
            if os.name == "nt":
                fake_bodies = {
                    "empty": "@echo off\r\nexit /b 0\r\n",
                    "multiline": (
                        "@echo off\r\n"
                        f"echo {'0' * 64}\r\n"
                        f"echo {'1' * 64}\r\n"
                        "exit /b 0\r\n"
                    ),
                    "nonhex": f"@echo off\r\necho {'g' * 64}\r\nexit /b 0\r\n",
                    "uppercase": f"@echo off\r\necho {'A' * 64}\r\nexit /b 0\r\n",
                    "nonzero": (
                        "@echo off\r\n"
                        "echo fake native failure 1>&2\r\n"
                        "exit /b 7\r\n"
                    ),
                    "cleanup_error": (
                        "@echo off\r\n"
                        "del /f /q \"%~2\"\r\n"
                        "mkdir \"%~2\"\r\n"
                        f"echo {'0' * 64}\r\n"
                        "exit /b 0\r\n"
                    ),
                }
                for name, body in fake_bodies.items():
                    path = root / f"fake-{name}.cmd"
                    path.write_bytes(body.encode("ascii"))
                    fake_paths[name] = path
            else:
                fake_bodies = {
                    "empty": "#!/bin/sh\nexit 0\n",
                    "multiline": (
                        "#!/bin/sh\n"
                        f"printf '%s\\n%s\\n' '{'0' * 64}' '{'1' * 64}'\n"
                        "exit 0\n"
                    ),
                    "nonhex": f"#!/bin/sh\nprintf '%s\\n' '{'g' * 64}'\nexit 0\n",
                    "uppercase": f"#!/bin/sh\nprintf '%s\\n' '{'A' * 64}'\nexit 0\n",
                    "nonzero": (
                        "#!/bin/sh\n"
                        "printf '%s\\n' 'fake native failure' >&2\n"
                        "exit 7\n"
                    ),
                    "cleanup_error": (
                        "#!/bin/sh\n"
                        "rm -- \"$2\"\n"
                        "mkdir -- \"$2\"\n"
                        f"printf '%s\\n' '{'0' * 64}'\n"
                        "exit 0\n"
                    ),
                }
                for name, body in fake_bodies.items():
                    path = root / f"fake-{name}"
                    path.write_text(body, encoding="utf-8", newline="\n")
                    path.chmod(0o700)
                    fake_paths[name] = path

            if os.name == "nt":
                system_root = os.environ.get("SystemRoot")
                self.assertIsNotNone(system_root, "SystemRoot is required on Windows")
                windows_powershell = (
                    Path(str(system_root))
                    / "System32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "powershell.exe"
                )
                self.assertTrue(
                    windows_powershell.is_file(),
                    f"Windows PowerShell 5.1 is absent: {windows_powershell}",
                )
                interpreters = [("windows_powershell_5_1", windows_powershell)]
                portable_pwsh = shutil.which("pwsh")
                if portable_pwsh:
                    interpreters.append(("windows_pwsh", Path(portable_pwsh)))
            else:
                portable_pwsh = shutil.which("pwsh")
                self.assertIsNotNone(portable_pwsh, "pwsh is required on Linux")
                interpreters = [("linux_pwsh", Path(str(portable_pwsh)))]

            evidence_interpreters: list[dict[str, object]] = []
            production_sha256: str | None = None
            for mode, shell in interpreters:
                identity = self._powershell_identity(shell, harness)
                full_version = identity["version"]
                if mode == "windows_powershell_5_1":
                    version_parts = full_version.split(".")
                    self.assertEqual(version_parts[:2], ["5", "1"])
                    self.assertEqual(identity["edition"], "Desktop")
                    self.assertEqual(
                        identity["ps_native_command_argument_passing"],
                        "LEGACY_UNAVAILABLE",
                    )

                named_results: dict[str, dict[str, object]] = {}
                cases = (
                    ("valid", Path(sys.executable), valid, "Success"),
                    ("malformed", Path(sys.executable), malformed, "Failure"),
                    ("nonfinite", Path(sys.executable), nonfinite, "Failure"),
                    ("missing_input", Path(sys.executable), missing_input, "Failure"),
                    ("missing_interpreter", missing_interpreter, valid, "Failure"),
                    *((name, path, valid, "Failure") for name, path in fake_paths.items()),
                    ("preference_restore", fake_paths["nonhex"], valid, "Failure"),
                )
                for case_name, python_path, input_path, expectation in cases:
                    with self.subTest(mode=mode, case=case_name):
                        result = self._run_transport_harness(
                            shell,
                            harness,
                            self.launcher,
                            python_path,
                            input_path,
                            expectation,
                            case_name,
                        )
                        self.assertTrue(result["error_action_preference_restored"])
                        if case_name == "valid":
                            self.assertEqual(result["output"], [expected_digest])
                        else:
                            self.assertEqual(result["outcome"], "REFUSED")
                            self.assertIn(
                                "Canonical payload hashing failed",
                                str(result["message"]),
                            )
                        named_results[case_name] = {
                            "outcome": str(result["outcome"]),
                            "exit_code": int(result["exit_code"]),
                        }
                        observed_sha256 = str(result["function_sha256"])
                        if production_sha256 is None:
                            production_sha256 = observed_sha256
                        self.assertEqual(observed_sha256, production_sha256)

                evidence_interpreters.append(
                    {
                        "mode": mode,
                        "path": str(shell.resolve()),
                        "full_version": full_version,
                        "edition": identity["edition"],
                        "ps_native_command_argument_passing": identity[
                            "ps_native_command_argument_passing"
                        ],
                        "fixtures": named_results,
                    }
                )

            legacy_result: dict[str, object] = {
                "outcome": "NOT_APPLICABLE",
                "exit_code": None,
            }
            if os.name == "nt":
                legacy_source = root / "e336 launcher.ps1"
                legacy = subprocess.run(
                    [
                        "git",
                        "show",
                        "e3367f9e5de48a099a585077a58ce9cff1051cab:"
                        "scripts/Invoke-AstraStage2ControlIdentityBinding.ps1",
                    ],
                    cwd=self.repo,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    legacy.returncode,
                    0,
                    msg=legacy.stderr.decode("utf-8", errors="replace"),
                )
                legacy_source.write_bytes(legacy.stdout)
                legacy = self._run_transport_harness(
                    interpreters[0][1],
                    harness,
                    legacy_source,
                    Path(sys.executable),
                    valid,
                    "Failure",
                    "legacy_e336_valid",
                )
                self.assertEqual(legacy["outcome"], "REFUSED")
                self.assertEqual(legacy["exit_code"], 20)
                legacy_result = {
                    "outcome": "REPRODUCED_FAILURE",
                    "exit_code": int(legacy["exit_code"]),
                }

            evidence_dir = os.environ.get("ASTRA_TRANSPORT_EVIDENCE_DIR")
            if evidence_dir:
                evidence_path = Path(evidence_dir)
                evidence_path.mkdir(parents=True, exist_ok=True)
                platform_name = "windows" if os.name == "nt" else "linux"
                evidence = {
                    "schema": "tier-bench/astra-stage2-powershell-canonical-transport@1",
                    "platform": platform_name,
                    "production_function_sha256": production_sha256,
                    "interpreters": evidence_interpreters,
                    "legacy_e336_windows_powershell_5_1": legacy_result,
                    "valid_digest": expected_digest,
                    "malformed_json_refused_with_launcher_message": True,
                    "error_action_preference_restored": True,
                    "temporary_script_cleanup": "PASS",
                    "cleanup_error": "REFUSED",
                }
                (evidence_path / f"transport-{platform_name}.json").write_text(
                    json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
