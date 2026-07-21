#!/usr/bin/env python3
"""Provider-free witnesses for the frozen Tier Desk newsroom constitution.

The validator is exercised only through its CLI contract:

    python -B scripts/validate_newsroom.py <file.json|-> [--json]

Exit 0 means valid, exit 1 means invalid, and exit 2 means unreadable or
malformed JSON. The suite makes zero model, network, or repository mutations.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate_newsroom.py"
MANIFEST = ROOT / "newsroom.json"


def ok(label: str) -> None:
    print(f"ok - {label}")


def run_validate(source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(VALIDATE), str(source), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def base_manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def assert_invalid(
    parent: Path,
    label: str,
    mutate: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    manifest = copy.deepcopy(base_manifest())
    mutate(manifest)
    path = parent / f"{label}.json"
    write_json(path, manifest)
    result = run_validate(path)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False, payload
    joined = "\n".join(payload["violations"]).lower()
    assert expected.lower() in joined, payload["violations"]
    ok(label)


def role(manifest: dict[str, Any], role_id: str) -> dict[str, Any]:
    return next(item for item in manifest["roles"] if item["id"] == role_id)


def object_record(manifest: dict[str, Any], object_id: str) -> dict[str, Any]:
    return next(item for item in manifest["objects"] if item["id"] == object_id)


def test_valid_manifest(parent: Path) -> None:
    path = parent / "valid.json"
    write_json(path, base_manifest())
    result = run_validate(path)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload == {"valid": True, "violations": []}, payload
    ok("valid_manifest")


def test_runtime_binding_is_rejected(parent: Path) -> None:
    assert_invalid(
        parent,
        "runtime_binding_is_rejected",
        lambda manifest: manifest.update({"model": "frontier-latest"}),
        "forbidden runtime-binding field",
    )


def test_nested_command_is_rejected(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["implementation_status"]["command"] = "run anything"

    assert_invalid(
        parent,
        "nested_command_is_rejected",
        mutate,
        "forbidden runtime-binding field",
    )


def test_chair_cannot_queue_or_execute(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        role(manifest, "chair")["may"].append("EXECUTE_AUTHORIZED")

    assert_invalid(
        parent,
        "chair_cannot_queue_or_execute",
        mutate,
        "roles[8].may must be exactly",
    )


def test_external_submission_cannot_enter_action_plane(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        object_record(manifest, "submission")["may_enter_action_plane"] = True

    assert_invalid(
        parent,
        "external_submission_cannot_enter_action_plane",
        mutate,
        "action_task must be the only object eligible",
    )


def test_submission_cannot_publish_directly(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["epistemic_state_machine"]["transitions"].append(
            {
                "from": "SUBMITTED",
                "to": "PUBLISHED",
                "actor": "publisher",
                "approval": "PUBLISHER",
            }
        )

    assert_invalid(
        parent,
        "submission_cannot_publish_directly",
        mutate,
        "submitted may not transition directly to published",
    )


def test_queue_requires_publisher(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        transition = manifest["action_state_machine"]["transitions"][0]
        transition["actor"] = "production_desk"
        transition["approval"] = "NONE"

    assert_invalid(
        parent,
        "queue_requires_publisher",
        mutate,
        "only publisher approval may move a draft into queued",
    )


def test_referee_cannot_execute(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        role(manifest, "referee")["may"].append("EXECUTE_AUTHORIZED")

    assert_invalid(
        parent,
        "referee_cannot_execute",
        mutate,
        "roles[3].may must be exactly",
    )


def test_corrections_desk_is_mandatory(parent: Path) -> None:
    def mutate(manifest: dict[str, Any]) -> None:
        manifest["roles"] = [
            item for item in manifest["roles"] if item["id"] != "corrections_desk"
        ]

    assert_invalid(
        parent,
        "corrections_desk_is_mandatory",
        mutate,
        "role ids must be exactly",
    )


def test_malformed_json_exits_2(parent: Path) -> None:
    path = parent / "malformed.json"
    path.write_text("{not json", encoding="utf-8")
    result = run_validate(path)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False and "error" in payload, payload
    ok("malformed_json_exits_2")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-newsroom-contract-"))
    tests = [
        test_valid_manifest,
        test_runtime_binding_is_rejected,
        test_nested_command_is_rejected,
        test_chair_cannot_queue_or_execute,
        test_external_submission_cannot_enter_action_plane,
        test_submission_cannot_publish_directly,
        test_queue_requires_publisher,
        test_referee_cannot_execute,
        test_corrections_desk_is_mandatory,
        test_malformed_json_exits_2,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index:02d}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS newsroom contract {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL newsroom contract {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
