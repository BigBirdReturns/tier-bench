#!/usr/bin/env python3
"""Witness tests for scripts/validate_contract.py.

Nothing here imports validate_contract.py as a module; the script under test
is invoked only as a subprocess, against its frozen CLI contract:

    python -B scripts/validate_contract.py <file.json|-> [--json]

Exit 0 = valid, exit 1 = invalid (violations printed), exit 2 = unreadable
or not JSON. Zero model calls.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate_contract.py"


def ok(label: str) -> None:
    print(f"ok - {label}")


def run_validate(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-B", str(VALIDATE)] + args
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def base_contract() -> dict[str, Any]:
    return {
        "schema": "tier-bench/job-contract@1",
        "id": "fix-slugify",
        "objective": "make slugify() handle unicode input without raising",
        "files": ["harness/util_text.py"],
        "acceptance": "python -B tests/test_util_text.py",
    }


def test_valid_contract_passes(parent: Path) -> None:
    contract_path = parent / "valid.job.json"
    write_json(contract_path, base_contract())
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is True, payload
    assert payload["violations"] == [], payload
    ok("valid_contract_passes: a well-formed contract validates with exit 0 and no violations")


def test_model_field_is_rejected(parent: Path) -> None:
    contract = base_contract()
    contract["model"] = "gpt-5.6-sol"
    contract_path = parent / "model.job.json"
    write_json(contract_path, contract)
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False, payload
    assert any("model" in v.lower() for v in payload["violations"]), payload["violations"]
    assert any("gpt-5.6-sol" in v for v in payload["violations"]), payload["violations"]
    ok('model_field_is_rejected: {"model": "gpt-5.6-sol"} is REJECTED with a model-naming reason')


def test_dotdot_scope_is_rejected(parent: Path) -> None:
    contract = base_contract()
    contract["files"] = ["../outside/escape.py"]
    contract_path = parent / "dotdot.job.json"
    write_json(contract_path, contract)
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False, payload
    assert any(".." in v or "safe repo-relative" in v for v in payload["violations"]), payload["violations"]
    ok("dotdot_scope_is_rejected: a files entry containing '..' is rejected")


def test_absolute_scope_is_rejected(parent: Path) -> None:
    contract = base_contract()
    contract["files"] = ["C:/Windows/System32/config.py"]
    contract_path = parent / "absolute.job.json"
    write_json(contract_path, contract)
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False, payload
    assert any("safe repo-relative" in v for v in payload["violations"]), payload["violations"]
    ok("absolute_scope_is_rejected: a drive-letter-absolute files entry is rejected")


def test_empty_acceptance_is_rejected(parent: Path) -> None:
    contract = base_contract()
    contract["acceptance"] = ""
    contract_path = parent / "empty_acceptance.job.json"
    write_json(contract_path, contract)
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False, payload
    assert any("acceptance" in v.lower() for v in payload["violations"]), payload["violations"]
    ok("empty_acceptance_is_rejected: an empty acceptance string is rejected")


def test_non_json_input_exits_2(parent: Path) -> None:
    contract_path = parent / "garbage.job.json"
    contract_path.write_text("{ this is not json", encoding="utf-8")
    result = run_validate([str(contract_path), "--json"])
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    ok("non_json_input_exits_2: malformed JSON input exits 2, not 1")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-contract-"))
    tests = [
        test_valid_contract_passes,
        test_model_field_is_rejected,
        test_dotdot_scope_is_rejected,
        test_absolute_scope_is_rejected,
        test_empty_acceptance_is_rejected,
        test_non_json_input_exits_2,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS contract {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL contract {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
