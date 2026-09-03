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

    @staticmethod
    def _powershell() -> str:
        for candidate in ("pwsh", "powershell"):
            executable = shutil.which(candidate)
            if executable:
                return executable
        raise AssertionError(
            "PowerShell executable is required for release tests"
        )

    def test_21_launcher_parses_with_terminating_powershell_gate(self) -> None:
        environment = dict(os.environ)
        environment["ASTRA_RELEASE_LAUNCHER"] = str(self.launcher)
        command = (
            "$ErrorActionPreference = 'Stop'; "
            "$text = Get-Content -Raw -LiteralPath "
            "$env:ASTRA_RELEASE_LAUNCHER; "
            "[void][scriptblock]::Create($text); "
            "Write-Output 'POWERSHELL_PARSE_PASS'"
        )
        process = subprocess.run(
            [self._powershell(), "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        self.assertEqual(
            process.returncode,
            0,
            msg=process.stdout + "\n" + process.stderr,
        )
        self.assertIn("POWERSHELL_PARSE_PASS", process.stdout)

    def test_22_launcher_pins_exact_qualified_binder_and_law(self) -> None:
        for value in (
            "af03cef494a509ab7ba5df29fa4b4ccba423f1f8",
            "519ea2f8f448a464e817a024ad8ed1ac64493931",
            "c36c35bf9b70d879e1e1c9ee2f0296879442df3e",
            "77abe4e177fc61e4f52f56ea64494b113f9662fc",
            "9babad4631ef517485c56ea4906aab123e30fad7",
            "60bca963d63edca267106bc5c7725c2cc1df8dd7",
        ):
            self.assertIn(value, self.text)

    def test_23_launcher_pins_all_source_and_checkpoint_coordinates(self) -> None:
        for value in (
            "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
            "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
            "b392d2cb7aaa73475b93028221523c47f49f66a2",
            "b87cf3aa2186937b0d0362a684d7d30f234543e3",
            "63de1ec1902ed143fe62250b6ddb14cb65f06e1a",
        ):
            self.assertIn(value, self.text)

    def test_24_launcher_discovers_repo_root_and_preserves_checkout(self) -> None:
        self.assertIn("Resolve-TierBenchRepositoryRoot", self.text)
        self.assertIn(
            r"D:\Projects\Measurement\Tier-Bench\main",
            self.text,
        )
        self.assertIn("Split-Path -Parent $PSScriptRoot", self.text)
        self.assertIn("worktree add --detach", self.text)
        self.assertNotIn("reset --hard", self.text.lower())
        self.assertNotIn("checkout -f", self.text.lower())

    def test_25_prepare_acquires_exact_assets_without_model_execution(self) -> None:
        self.assertIn("snapshot_download", self.text)
        self.assertIn("local_dir_use_symlinks=False", self.text)
        self.assertIn("Select-LargestNvidiaDevice", self.text)
        self.assertIn(
            "ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND",
            self.text,
        )
        for forbidden in (
            "model.generate(",
            "/v1/chat/completions",
            "vllm serve",
            "scripts/eval.py",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ):
            self.assertNotIn(forbidden.lower(), self.text.lower())

    def test_26_preflight_exercises_pinned_binder_import_boundary(self) -> None:
        self.assertIn(
            "[ValidateSet('Preflight', 'Prepare', 'Bind', 'Verify')]",
            self.text,
        )
        self.assertIn("function Invoke-BinderCommand", self.text)
        self.assertIn("Push-Location -LiteralPath $BinderRoot", self.text)
        self.assertIn("$env:PYTHONPATH = $BinderRoot", self.text)
        self.assertIn("'template'", self.text)
        self.assertIn(
            "schema = 'tier-bench/astra-stage2-control-identity-preflight@2'",
            self.text,
        )
        self.assertIn("state = 'PREFLIGHT_PASS'", self.text)
        self.assertIn("binder_command_import_probe = 'PASS'", self.text)
        self.assertIn("binder_template_probe_sha256", self.text)
        self.assertIn("downloads_performed = $false", self.text)
        self.assertIn("model_calls = 0", self.text)
        self.assertIn("provider_calls = 0", self.text)
        self.assertIn(
            "actual_executable_control_identities = 'UNBOUND'",
            self.text,
        )
        self.assertNotIn("& $wrapper -Command", self.text)

    def test_27_bind_refuses_placeholder_runtime_and_effort_mapping(self) -> None:
        self.assertRegex(
            self.text,
            re.compile(r"if \(\$raw -match 'REPLACE'\)", re.MULTILINE),
        )
        self.assertIn("non-authoritative template", self.text)
        self.assertIn("Bind is refused", self.text)
        for command in (
            "'validate-config'",
            "'bind'",
            "'verify'",
        ):
            self.assertIn(command, self.text)
        self.assertNotIn("& $wrapper -Command", self.text)


if __name__ == "__main__":
    unittest.main()
