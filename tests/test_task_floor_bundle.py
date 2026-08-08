#!/usr/bin/env python3
"""Interop bundle, export, replay, and skill-supply-chain tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "tests" / "fixtures" / "task_floor" / "accepted-run"
MANIFEST = ROOT / "experiments" / "task_floor" / "reference_manifest.json"

from tier_runner.playwright_computer_common import (  # noqa: E402
    PlaywrightComputerError,
    load_json,
)
from tier_runner.task_floor_conformance import assess_bundle  # noqa: E402
from tier_runner.task_floor_export import (  # noqa: E402
    build_bundle,
    verify_bundle,
    write_bundle_directory,
)
from tier_runner.task_floor_replay import (  # noqa: E402
    compile_replay_plan,
    propose_skill_package,
)
from tier_runner.task_floor_protocol import validate_skill_package  # noqa: E402

EXPECTED_EXPORTS = {
    "mcp",
    "a2a",
    "ag-ui",
    "opentelemetry",
    "in-toto",
    "opa",
    "browsergym",
    "cloudevents",
    "agentrx",
    "cua",
    "cedar",
    "langgraph",
}


def _bundle(parent: Path) -> dict:
    base = build_bundle(FIXTURE, load_json(MANIFEST))
    return write_bundle_directory(
        parent / "bundle",
        base,
        a2a_endpoint="https://example.invalid/a2a",
        artifact_source_root=FIXTURE,
    )


def test_bundle_is_portable_through_twelve_exports_and_tf5() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-floor-bundle-"))
    try:
        bundle = _bundle(parent)
        assert verify_bundle(bundle, root=parent / "bundle") == []
        assert set(bundle["exports"]) == EXPECTED_EXPORTS
        report = assess_bundle(bundle)
        assert report["highest_contiguous_profile"] == "TF5", report
        assert report["profiles"]["TF6"]["pass"] is False
        failed_tf6 = {
            row["id"] for row in report["checks"] if row["profile"] == "TF6" and not row["pass"]
        }
        assert failed_tf6 == {"execution.compensation"}
        assert report["claims"]["overclaimed_profiles"] == []
        assert bundle["metrics"]["accepted_work_units"] == 1
        assert bundle["trajectory"]["events"]
        assert (parent / "bundle" / "agent-card.json").is_file()
        assert (parent / "bundle" / "attestation.json").is_file()
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_bundle_tamper_and_overclaim_are_detected() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-floor-tamper-"))
    try:
        bundle = _bundle(parent)
        tampered = deepcopy(bundle)
        tampered["trajectory"]["events"][0]["data"]["title"] = "tampered"
        errors = verify_bundle(tampered)
        assert any("trajectory" in error or "bundle" in error for error in errors), errors

        overclaimed = deepcopy(bundle)
        overclaimed["manifest"]["conformance"]["profiles_claimed"].append("TF7")
        report = assess_bundle(overclaimed)
        assert "TF7" in report["claims"]["overclaimed_profiles"]
        assert report["claims"]["production_qualified"] is False
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_replay_fails_closed_and_accepted_run_can_only_propose_unreviewed_skill() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-floor-replay-"))
    try:
        bundle = _bundle(parent)
        simulated = compile_replay_plan(bundle, mode="simulate")
        assert simulated["execution_authorized"] is False
        assert simulated["steps"]
        execute = compile_replay_plan(bundle, mode="execute", allow_effects=["read"])
        assert execute["execution_authorized"] is False
        assert [row["effect"] for row in execute["blocked_actions"]] == ["local_write"]

        artifact = parent / "skill.py"
        artifact.write_text("def run():\n    return 'fixture'\n", encoding="utf-8")
        skill = propose_skill_package(
            bundle,
            skill_id="task-floor.synthetic.skill",
            version="0.1.0",
            name="Synthetic accepted trajectory skill",
            entrypoint="skill:run",
            artifact_path=artifact,
            runtime={"kind": "python", "version": f"{sys.version_info.major}.{sys.version_info.minor}"},
        )
        assert validate_skill_package(skill) == skill
        assert skill["production_authorized"] is False
        assert skill["review"]["status"] == "unreviewed"
        assert any(test["kind"] == "prompt-injection" for test in skill["tests"])
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [
        test_bundle_is_portable_through_twelve_exports_and_tf5,
        test_bundle_tamper_and_overclaim_are_detected,
        test_replay_fails_closed_and_accepted_run_can_only_propose_unreviewed_skill,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Floor bundle tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
