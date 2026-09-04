from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
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
        cls.text = cls.launcher.read_text(encoding="utf-8")

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
            "3079883f1b4a1486e5859b97eb2ff2a7e3c6fb07",
            "097f958ad5eafdadeb0f5ca79ea05437dad0bd26",
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


if __name__ == "__main__":
    unittest.main()
