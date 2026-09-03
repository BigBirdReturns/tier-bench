from __future__ import annotations

import re
import unittest
from pathlib import Path


class ControlIdentityReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]
        cls.launcher = cls.repo / "scripts" / "Invoke-AstraStage2ControlIdentityBinding.ps1"
        cls.text = cls.launcher.read_text(encoding="utf-8")

    def test_21_launcher_pins_exact_qualified_binder_coordinate(self) -> None:
        self.assertIn("af03cef494a509ab7ba5df29fa4b4ccba423f1f8", self.text)
        self.assertIn("519ea2f8f448a464e817a024ad8ed1ac64493931", self.text)
        self.assertIn("77abe4e177fc61e4f52f56ea64494b113f9662fc", self.text)
        self.assertIn("9babad4631ef517485c56ea4906aab123e30fad7", self.text)

    def test_22_launcher_pins_all_three_source_and_checkpoint_coordinates(self) -> None:
        for value in (
            "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
            "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
            "b392d2cb7aaa73475b93028221523c47f49f66a2",
            "b87cf3aa2186937b0d0362a684d7d30f234543e3",
            "63de1ec1902ed143fe62250b6ddb14cb65f06e1a",
        ):
            self.assertIn(value, self.text)

    def test_23_prepare_uses_separate_worktree_and_preserves_primary_checkout(self) -> None:
        self.assertIn("worktree add --detach", self.text)
        self.assertNotIn("reset --hard", self.text.lower())
        self.assertNotIn("checkout -f", self.text.lower())
        self.assertIn("Binder worktree is dirty", self.text)

    def test_24_prepare_downloads_exact_snapshots_without_executing_models(self) -> None:
        self.assertIn("snapshot_download", self.text)
        self.assertIn("local_dir_use_symlinks=False", self.text)
        forbidden = (
            "model.generate(",
            "pipeline(\"text-generation\"",
            "scripts/eval.py",
            "vllm serve",
            "/v1/chat/completions",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        )
        for token in forbidden:
            self.assertNotIn(token.lower(), self.text.lower())

    def test_25_prepare_selects_hardware_and_stops_with_runtime_unbound(self) -> None:
        self.assertIn("Select-LargestNvidiaDevice", self.text)
        self.assertIn("ASSETS_PREPARED_EXECUTABLE_IDENTITIES_UNBOUND", self.text)
        self.assertIn("runtime_identity = 'UNBOUND'", self.text)
        self.assertIn("effort_mapping = 'UNBOUND'", self.text)
        self.assertIn("model_calls = 0", self.text)
        self.assertIn("provider_calls = 0", self.text)

    def test_26_bind_refuses_template_runtime_and_effort_mapping(self) -> None:
        self.assertRegex(self.text, re.compile(r"if \(\$raw -match 'REPLACE'\)", re.MULTILINE))
        self.assertIn("Effort mapping for", self.text)
        self.assertIn("non-authoritative template", self.text)
        self.assertIn("Bind is refused", self.text)

    def test_27_bind_only_hashes_and_verifies_after_explicit_bind_mode(self) -> None:
        self.assertIn("[ValidateSet('Prepare', 'Bind', 'Verify')]", self.text)
        self.assertIn("[string]$Mode = 'Prepare'", self.text)
        bind_block = self.text.split("if ($Mode -eq 'Bind')", 1)[1]
        self.assertIn("-Command validate-config", bind_block)
        self.assertIn("-Command bind", bind_block)
        self.assertIn("-Command verify", bind_block)
        self.assertIn("No model was executed", bind_block)


if __name__ == "__main__":
    unittest.main()
