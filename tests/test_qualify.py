#!/usr/bin/env python3
"""Witness tests for scripts/qualify.py.

Invoked strictly as a subprocess against the frozen CLI/output contract, the
same way tests/test_route.py holds route.py to its contract - nothing here
imports qualify.py as a module:

    python -B scripts/qualify.py --job <contract.json> [--repo <path>]
        [--check-discriminates] --json

qualify.py never calls a model and never dispatches; it only classifies a
job contract (or array of contracts) into one of:

    not_eligible | single_dispatch | parallel_dispatch | driver_loop | planner_first
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
QUALIFY = ROOT / "scripts" / "qualify.py"


def ok(label: str) -> None:
    print(f"ok - {label}")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def run_qualify(
    args: list[str], env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    env.update(env_overrides or {})
    cmd = [sys.executable, "-B", str(QUALIFY)] + args
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def run_job(
    parent: Path,
    name: str,
    job: Any,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    job_path = parent / f"{name}.job.json"
    write_json(job_path, job)
    args = ["--job", str(job_path), "--json"] + (extra_args or [])
    result = run_qualify(args, env_overrides)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"qualify did not print JSON: {exc}\nstdout={result.stdout!r}") from exc
    for key in ("mode", "reasons", "contracts", "discriminates", "verdict"):
        assert key in payload, (key, payload)
    return payload


def base_contract(**overrides: Any) -> dict[str, Any]:
    contract = {
        "schema": "tier-bench/job-contract@1",
        "objective": "implement the missing helper",
        "files": ["app/helper.py"],
        "acceptance": "python check.py",
    }
    contract.update(overrides)
    return contract


# -- witnesses ---------------------------------------------------------------


def test_no_acceptance_is_not_eligible(parent: Path) -> None:
    job = base_contract(acceptance="")
    payload = run_job(parent, "no_acceptance", job)
    assert payload["mode"] == "not_eligible", payload
    assert any("no_acceptance" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("no_acceptance_is_not_eligible: missing acceptance command -> not_eligible")


def test_model_ish_acceptance_is_not_eligible(parent: Path) -> None:
    job = base_contract(acceptance="have Claude review the diff")
    payload = run_job(parent, "model_ish", job)
    assert payload["mode"] == "not_eligible", payload
    assert any("model_ish_acceptance" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("model_ish_acceptance_is_not_eligible: 'have Claude review the diff' -> not_eligible, model-ish reason")


def test_unbounded_scope_is_not_eligible(parent: Path) -> None:
    job = base_contract(files=["src/utils/"])
    payload = run_job(parent, "unbounded_scope", job)
    assert payload["mode"] == "not_eligible", payload
    assert any("unbounded" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("unbounded_scope_is_not_eligible: directory-shaped scope -> not_eligible")


def test_forbidden_model_field_is_not_eligible(parent: Path) -> None:
    job = base_contract(model="claude-fable-5")
    payload = run_job(parent, "forbidden_field", job)
    assert payload["mode"] == "not_eligible", payload
    assert any("forbidden_field" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("forbidden_model_field_is_not_eligible: contract naming a model field is rejected (HARD RULE)")


def test_single_contract_no_deps_is_single_dispatch(parent: Path) -> None:
    job = base_contract()
    payload = run_job(parent, "single", job)
    assert payload["mode"] == "single_dispatch", payload
    assert payload["verdict"].startswith("single_dispatch:"), payload
    ok("single_contract_no_deps_is_single_dispatch: one contract, no depends_on -> single_dispatch")


def test_three_independent_contracts_is_parallel_dispatch(parent: Path) -> None:
    job = [
        base_contract(id="a", objective="implement helper a", files=["app/a.py"]),
        base_contract(id="b", objective="fix bug in b", files=["app/b.py"]),
        base_contract(id="c", objective="add feature c", files=["app/c.py"]),
    ]
    payload = run_job(parent, "parallel", job)
    assert payload["mode"] == "parallel_dispatch", payload
    assert len(payload["contracts"]) == 3, payload
    ok("three_independent_contracts_is_parallel_dispatch: 3 contracts, no depends_on -> parallel_dispatch")


def test_depends_on_is_driver_loop(parent: Path) -> None:
    job = [
        base_contract(id="a", objective="implement base helper", files=["app/a.py"]),
        base_contract(id="b", objective="implement dependent helper", files=["app/b.py"], depends_on=["a"]),
    ]
    payload = run_job(parent, "driver_deps", job)
    assert payload["mode"] == "driver_loop", payload
    assert any("depends_on" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("depends_on_is_driver_loop: a depends_on edge -> driver_loop")


def test_decomposition_unknown_hint_is_driver_loop(parent: Path) -> None:
    # A single contract with no depends_on would otherwise be single_dispatch;
    # the "decomposition is unknown" OR clause must override that by itself.
    job = base_contract(hints={"decomposition_unknown": True})
    payload = run_job(parent, "driver_unknown", job)
    assert payload["mode"] == "driver_loop", payload
    assert any("decomposition_unknown" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("decomposition_unknown_hint_is_driver_loop: hints.decomposition_unknown alone -> driver_loop")


def test_t4_objective_is_planner_first(parent: Path) -> None:
    job = base_contract(objective="design the interface for the new adapter layer")
    payload = run_job(parent, "planner_first", job)
    assert payload["mode"] == "planner_first", payload
    assert payload["contracts"][0]["tier"] in ("T4", "T5"), payload
    ok("t4_objective_is_planner_first: 'design the interface for...' classifies T4+ -> planner_first")


def test_check_discriminates_false_when_already_passing(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "check.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    job = base_contract(acceptance="python check.py")
    payload = run_job(parent, "discriminates_false", job, extra_args=["--repo", str(repo), "--check-discriminates"])
    assert payload["discriminates"] is False, payload
    assert payload["contracts"][0]["discriminates"] is False, payload
    ok("check_discriminates_false_when_already_passing: exit 0 before any patch -> discriminates false")


def test_check_discriminates_true_when_failing(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "check.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    job = base_contract(acceptance="python check.py")
    payload = run_job(parent, "discriminates_true", job, extra_args=["--repo", str(repo), "--check-discriminates"])
    assert payload["discriminates"] is True, payload
    assert payload["contracts"][0]["discriminates"] is True, payload
    ok("check_discriminates_true_when_failing: exit nonzero before any patch -> discriminates true")


def test_check_discriminates_timeout_is_unknown_not_true(parent: Path) -> None:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "slow.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    job = base_contract(acceptance="python slow.py")
    payload = run_job(
        parent,
        "discriminates_timeout",
        job,
        extra_args=["--repo", str(repo), "--check-discriminates"],
        env_overrides={"QUALIFY_DISCRIMINATE_TIMEOUT_SECONDS": "0.5"},
    )
    assert payload["discriminates"] is None, payload
    assert payload["contracts"][0]["discriminates"] is None, payload
    ok("check_discriminates_timeout_is_unknown_not_true: a timeout reports unknown, never true")


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-qualify-"))
    tests = [
        test_no_acceptance_is_not_eligible,
        test_model_ish_acceptance_is_not_eligible,
        test_unbounded_scope_is_not_eligible,
        test_forbidden_model_field_is_not_eligible,
        test_single_contract_no_deps_is_single_dispatch,
        test_three_independent_contracts_is_parallel_dispatch,
        test_depends_on_is_driver_loop,
        test_decomposition_unknown_hint_is_driver_loop,
        test_t4_objective_is_planner_first,
        test_check_discriminates_false_when_already_passing,
        test_check_discriminates_true_when_failing,
        test_check_discriminates_timeout_is_unknown_not_true,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS qualify {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL qualify {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
