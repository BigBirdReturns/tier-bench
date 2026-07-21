#!/usr/bin/env python3
"""Witness tests for tier_runner/init_arms.py.

These witnesses exercise build_manifest() (and the small per-tool arm
builders it calls) against fabricated probe dicts only -- no real
subprocess is spawned and no network call is made anywhere in this file.
probe_codex/probe_claude/probe_ollama themselves are not invoked; only their
documented *return shape* is fed into build_manifest, exactly as tier_init.py
would after calling them for real.

Run: python -B tests/test_init_arms.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tier_runner import init_arms, manifest  # noqa: E402


def ok(label: str) -> None:
    print(f"ok - {label}")


PROTOCOL_COMMIT = "a" * 40
TEMPLATE_BYTES = b"You are executing one bounded repository change.\n"
TEMPLATE_SHA256 = manifest.sha256_bytes(TEMPLATE_BYTES)


def base_probes() -> dict[str, Any]:
    """Scaffolding every build_manifest() call needs, with no tool probes."""
    return {
        "protocol_commit": PROTOCOL_COMMIT,
        "hands_template": {"path": ".tier/hands.prompt.txt", "sha256": TEMPLATE_SHA256},
    }


def write_manifest_tree(parent: Path, data: dict[str, Any]) -> Path:
    """Write `data` plus its declared hands template under `parent`; return the manifest path."""
    template_rel = data["prompt_templates"]["hands"]["path"]
    template_path = parent / Path(*Path(template_rel.replace("\\", "/")).parts)
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_bytes(TEMPLATE_BYTES)
    manifest_path = parent / "pilot_backends.json"
    manifest_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    return manifest_path


def custom_arm_stanza() -> dict[str, Any]:
    return {
        "model_id": "some-custom-model",
        "effort": "low",
        "surface": "custom-surface",
        "cost_basis": "shadow-estimated",
        "account": "custom-account",
        "tier": "local",
        "prompt_template": "hands",
        "tool_versions": {"custom_tool": "1.2.3"},
        "adapter": {
            "command": [
                "python", "-m", "custom_adapter",
                "--dispatch", "{dispatch_receipt}",
                "--prompt", "{prompt}",
                "--result", "{backend_result}",
                "--worktree", "{worktree}",
            ]
        },
    }


# -- witnesses -------------------------------------------------------------


def test_codex_absent_emits_no_codex_arms(_parent: Path) -> None:
    probes = base_probes()
    probes["codex"] = {"available": False, "version": None, "models": [], "source": None}
    probes["claude"] = {"available": True, "version": "2.1.0", "help_sha256": "f" * 64}
    result = init_arms.build_manifest(probes)
    codex_arm_names = {spec["arm"] for spec in init_arms.CODEX_ARM_SPECS.values()}
    assert not (codex_arm_names & set(result["arms"])), result["arms"]
    assert init_arms.CLAUDE_ARM in result["arms"], result["arms"]
    ok("codex_absent_emits_no_codex_arms: unavailable codex probe -> no arm_a/luna/terra/spark")


def test_claude_present_emits_arm_haiku_with_probed_version_and_hash(_parent: Path) -> None:
    probes = base_probes()
    probes["claude"] = {"available": True, "version": "2.1.215 (Claude Code)", "help_sha256": "b" * 64}
    result = init_arms.build_manifest(probes)
    arm = result["arms"][init_arms.CLAUDE_ARM]
    assert arm["tool_versions"]["claude_code"] == "2.1.215 (Claude Code)", arm
    assert arm["tool_versions"]["claude_help_sha256"] == "b" * 64, arm
    assert "--claude-version" in arm["adapter"]["command"], arm
    assert "2.1.215 (Claude Code)" in arm["adapter"]["command"], arm
    ok("claude_present_emits_arm_haiku_with_probed_version_and_hash: arm_haiku carries the exact probed values")


def test_build_manifest_loads_for_every_arm(parent: Path) -> None:
    probes = base_probes()
    probes["codex"] = {
        "available": True,
        "version": "codex-cli 0.144.6",
        "models": ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "unknown-slug-ignored"],
        "source": "probed",
    }
    probes["claude"] = {"available": True, "version": "2.1.215 (Claude Code)", "help_sha256": "c" * 64}
    probes["ollama"] = {
        "available": True,
        "version": "0.32.1",
        "models": {init_arms.OLLAMA_MODEL: "sha256:" + "d" * 64},
    }
    result = init_arms.build_manifest(probes)
    assert "unknown-slug-ignored" not in json.dumps(result), "unmapped codex slug must not become an arm"
    expected = {"arm_a", "arm_luna", "arm_spark", init_arms.CLAUDE_ARM, init_arms.OLLAMA_ARM}
    assert expected <= set(result["arms"]), result["arms"]

    manifest_path = write_manifest_tree(parent, result)
    for arm_name in result["arms"]:
        manifest.load_backend(manifest_path, arm_name)  # raises ManifestError on any mismatch
    ok(f"build_manifest_loads_for_every_arm: all {len(result['arms'])} generated arms pass load_backend()")


def test_existing_arm_survives_unchanged(_parent: Path) -> None:
    existing = {
        "schema": init_arms.SCHEMA,
        "protocol_commit": "e" * 40,
        "isolation": dict(init_arms.ISOLATION),
        "tool_versions": {"placeholder": "1"},
        "prompt_templates": {"hands": {"path": ".tier/hands.prompt.txt", "sha256": "f" * 64}},
        "arms": {"arm_custom": custom_arm_stanza(), init_arms.CLAUDE_ARM: custom_arm_stanza()},
    }
    probes = {
        # Deliberately omit protocol_commit/hands_template: they must come
        # from `existing` instead of raising.
        "claude": {"available": True, "version": "9.9.9", "help_sha256": "9" * 64},
    }
    result = init_arms.build_manifest(probes, existing=existing)
    assert result["arms"]["arm_custom"] == custom_arm_stanza(), result["arms"]["arm_custom"]
    # A fresh claude probe must NOT clobber the arm_haiku entry already in `existing`.
    assert result["arms"][init_arms.CLAUDE_ARM] == custom_arm_stanza(), result["arms"][init_arms.CLAUDE_ARM]
    assert result["protocol_commit"] == "e" * 40, result["protocol_commit"]
    ok("existing_arm_survives_unchanged: existing arm_custom and arm_haiku both pass through untouched")


def test_probe_missing_version_never_yields_arm(_parent: Path) -> None:
    probes = base_probes()
    probes["claude"] = {"available": True, "version": None, "help_sha256": "a" * 64}
    probes["codex"] = {"available": True, "version": "", "models": ["gpt-5.6-sol"], "source": "probed"}
    probes["ollama"] = {"available": True, "version": None, "models": {init_arms.OLLAMA_MODEL: "sha256:" + "0" * 64}}
    result = init_arms.build_manifest(probes)
    assert init_arms.CLAUDE_ARM not in result["arms"], result["arms"]
    assert "arm_a" not in result["arms"], result["arms"]
    assert init_arms.OLLAMA_ARM not in result["arms"], result["arms"]
    ok("probe_missing_version_never_yields_arm: a null/empty probed version withholds that arm, for every tool")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-init-arms-"))
    tests = [
        test_codex_absent_emits_no_codex_arms,
        test_claude_present_emits_arm_haiku_with_probed_version_and_hash,
        test_build_manifest_loads_for_every_arm,
        test_existing_arm_survives_unchanged,
        test_probe_missing_version_never_yields_arm,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS init_arms {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL init_arms {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
