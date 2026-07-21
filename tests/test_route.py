#!/usr/bin/env python3
"""Witness tests for scripts/route.py.

route.py is being written concurrently with this file, so these witnesses are
built strictly against the frozen CLI/output contract, not against whatever
happens to be on disk. Nothing here imports route.py as a module; the script
under test is invoked only as a subprocess:

    python -B scripts/route.py plan --job <job.json> [--policy <cartridges.json>] --json
    python -B scripts/route.py report --state-dir <dir> [--policy <cartridges.json>] --json

Both subcommands print one JSON object to stdout and exit 0 on success.

ACCEPTED-LOCAL-COVERAGE (the metric these tests hold route.py to):
Scan receipts at <state_dir>/tier-runs/monster-wrangler/*/attempt-*/receipt.json.
Each receipt has {arm, state, task_id, errors}. Per arm: accepted =
count(state=="ACCEPTED"); rejected = count(state=="REJECTED"); errors =
count(state=="ERROR"); coverage = accepted / (accepted + rejected), or null
when that denominator is 0. ERROR rows never enter the denominator (see
docs/monster-wrangler.md: transport/infrastructure errors "do not contaminate
the capability denominator").
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
ROUTE = ROOT / "scripts" / "route.py"

TIER_ORDER = ["T0", "T1", "T2", "T3", "T4"]

# Ladder policy shared by the plan() witnesses. Kept deliberately tiny and
# self-contained so these tests never depend on the repo's own
# cartridges.json (that file is checked directly, and only for the one
# witness that cares about it).
POLICY = {
    "ladders": {
        "T0": ["arm_spark", "arm_luna", "arm_a"],
        "T1": ["arm_spark", "arm_luna", "arm_a"],
        "T2": ["arm_luna", "arm_a"],
        "T3": ["arm_a"],
        "T4": ["arm_a"],
    }
}


def ok(label: str) -> None:
    print(f"ok - {label}")


def run_route(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-B", str(ROUTE)] + args
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


def tier_at_least(tier: str, minimum: str) -> bool:
    assert tier in TIER_ORDER, f"unrecognized tier: {tier!r}"
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(minimum)


def run_plan(parent: Path, name: str, job: dict[str, Any]) -> dict[str, Any]:
    job_path = parent / f"{name}.job.json"
    policy_path = parent / f"{name}.cartridges.json"
    write_json(job_path, job)
    write_json(policy_path, POLICY)
    result = run_route(
        ["plan", "--job", str(job_path), "--policy", str(policy_path), "--json"]
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"plan did not print JSON: {exc}\nstdout={result.stdout!r}") from exc
    for key in ("tier", "arm", "escalate", "reasons"):
        assert key in payload, (key, payload)
    assert isinstance(payload["escalate"], list), payload
    assert isinstance(payload["reasons"], list), payload
    return payload


def write_receipt(
    state_dir: Path,
    task_id: str,
    attempt: int,
    arm: str,
    state: str,
    errors: Any = None,
    task: str = "",
    files: list[str] | None = None,
    acceptance_command: str = "",
) -> None:
    """Write a synthetic receipt.json.

    task/files/acceptance_command mirror the real receipt schema (see
    tier-runs/monster-wrangler/*/attempt-*/receipt.json in the repo) and are
    what route.py's difficulty-tier derivation reconstructs a job contract
    from. They default to empty, which classify()'s own rules treat as a
    non-match (its documented no-rule-fired default is T2) -- existing
    witnesses that don't pass these kwargs are unaffected.
    """
    directory = state_dir / "tier-runs" / "monster-wrangler" / task_id / f"attempt-{attempt:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {
        "arm": arm,
        "state": state,
        "task_id": task_id,
        "errors": errors if errors is not None else [],
        "task": task,
        "files": files if files is not None else [],
        "acceptance_command": acceptance_command,
    }
    write_json(directory / "receipt.json", receipt)


def run_report(state_dir: Path) -> dict[str, Any]:
    result = run_route(["report", "--state-dir", str(state_dir), "--json"])
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"report did not print JSON: {exc}\nstdout={result.stdout!r}") from exc
    assert "total" in payload, payload
    return payload


def get_arm_entry(payload: dict[str, Any], arm: str) -> dict[str, Any]:
    """Find the per-arm {accepted, rejected, errors, coverage} block.

    The contract only pins the per-arm field names, not the wrapping shape,
    so accept either a top-level {"arms": {arm: {...}}} block or the arm
    keyed directly at the top level alongside "total".
    """
    arms = payload.get("arms")
    if isinstance(arms, dict) and arm in arms:
        return arms[arm]
    if arm in payload:
        return payload[arm]
    raise AssertionError(f"no per-arm block for {arm!r} in report payload: {payload}")


def _iter_list_strings(node: Any):
    if isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                yield item
            else:
                yield from _iter_list_strings(item)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _iter_list_strings(value)


# -- witnesses -------------------------------------------------------------


def test_clerical_job_routes_to_cheap_floor(parent: Path) -> None:
    job = {
        "objective": "rename the helper",
        "files": ["app/helper.py"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "clerical", job)
    assert payload["tier"] == "T0", payload
    assert payload["arm"], payload
    assert payload["arm"] != "arm_b", "cheap floor must not be the local arm by default"
    ok("clerical_job_routes_to_cheap_floor: tier T0, non-local primary arm")


def test_tier_is_max_not_last_rule(parent: Path) -> None:
    job = {
        "objective": "rename a symbol",
        "files": ["a.py", "b.py", "c.py"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "max_rule", job)
    assert payload["tier"] == "T3", payload
    reasons = payload["reasons"]
    assert any("scope_files" in reason for reason in reasons), reasons
    ok("tier_is_max_not_last_rule: T0 verb + 3 scopes -> T3 (max, not last), scope_files in reasons")


def test_directory_scope_escalates(parent: Path) -> None:
    job = {
        "objective": "rename the module",
        "files": ["src/utils/"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "dir_scope", job)
    assert tier_at_least(payload["tier"], "T2"), payload
    ok("directory_scope_escalates: directory-suffixed scope with a T0 verb reaches >= T2")


def test_unrecognised_job_defaults_to_T2_not_T0(parent: Path) -> None:
    # Luna's P1, generalised: a verb list is never exhaustive. An objective that
    # fires no rule at all must fail UPWARD, or an unrecognised destructive job
    # ("purge the tenant cache") lands on the cheapest arm.
    job = {
        "objective": "purge the tenant cache",
        "files": ["app/cache_control.py"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "no_rule", job)
    assert payload["tier"] == "T2", payload
    assert payload["arm"] != "arm_b", payload
    assert any("default" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("unrecognised_job_defaults_to_T2_not_T0: no rule fires -> T2 with an explicit default reason")


def test_extensionless_directory_scope_escalates(parent: Path) -> None:
    # Luna's P2: a directory written without a trailing slash means the same
    # unbounded thing and must not evade the directory rule.
    job = {
        "objective": "rename the module",
        "files": ["src/utils"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "bare_dir", job)
    assert tier_at_least(payload["tier"], "T2"), payload
    assert any("directory_scope" in reason for reason in payload["reasons"]), payload["reasons"]
    ok("extensionless_directory_scope_escalates: 'src/utils' with no trailing slash still reaches >= T2")


def test_destructive_verb_escalates_past_default_floor(parent: Path) -> None:
    job = {
        "objective": "delete the migration table",
        "files": ["db/migrations/0007_drop_legacy.py"],
        "acceptance": "python check.py",
    }
    payload = run_plan(parent, "destructive_verb", job)
    assert tier_at_least(payload["tier"], "T3"), payload
    assert any("delete" in reason for reason in payload["reasons"]), payload
    ok("destructive_verb_escalates_past_default_floor: a destructive verb never silently defaults to T0")


def test_local_arm_never_on_default_ladder(_parent: Path) -> None:
    cartridges_path = ROOT / "cartridges.json"
    assert cartridges_path.exists(), f"expected repo policy at {cartridges_path}"
    data = json.loads(cartridges_path.read_text(encoding="utf-8"))
    strings = set(_iter_list_strings(data))
    assert "arm_b" not in strings, "arm_b (local) must not appear on any default ladder"
    ok("local_arm_never_on_default_ladder: arm_b absent from every ladder in the repo cartridges.json")


def test_coverage_excludes_errors(parent: Path) -> None:
    state_dir = parent / "state"
    task = 0
    for _ in range(3):
        task += 1
        write_receipt(state_dir, f"task-{task}", 1, "arm_spark", "ACCEPTED")
    task += 1
    write_receipt(state_dir, f"task-{task}", 1, "arm_spark", "REJECTED")
    for _ in range(5):
        task += 1
        write_receipt(state_dir, f"task-{task}", 1, "arm_spark", "ERROR", errors=["transport timeout"])

    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_spark")
    assert entry["accepted"] == 3, entry
    assert entry["rejected"] == 1, entry
    assert entry["errors"] == 5, entry
    assert entry["coverage"] == 0.75, entry
    # Terra P1 (tiny-denominator gaming): coverage's adjudicated-only denominator
    # must never be the only number printed. attempts/error_rate ride beside it
    # so a high coverage sitting on a small adjudicated slice of a mostly-ERROR
    # arm can't be read as strong evidence without also seeing the error rate.
    assert entry["attempts"] == 9, entry
    assert entry["error_rate"] == 5 / 9, entry
    ok("coverage_excludes_errors: 3 ACCEPTED / 1 REJECTED / 5 ERROR -> coverage == 0.75 exactly, errors == 5")


def test_coverage_null_when_no_adjudicated_rows(parent: Path) -> None:
    state_dir = parent / "state"
    for index in range(1, 5):
        write_receipt(state_dir, f"task-{index}", 1, "arm_only_errors", "ERROR", errors=["backend unavailable"])

    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_only_errors")
    assert entry["accepted"] == 0, entry
    assert entry["rejected"] == 0, entry
    assert entry["errors"] == 4, entry
    coverage = entry["coverage"]
    assert coverage in (None, "n/a"), f"coverage with a zero denominator must be null/n-a, got {coverage!r}"
    assert coverage != 0.0, "a zero-denominator arm must never be reported as 0.0 coverage"
    ok("coverage_null_when_no_adjudicated_rows: all-ERROR arm reports coverage as null, not 0.0")


def test_trivial_tier_arm_not_comparable_even_at_full_coverage(parent: Path) -> None:
    # Terra P1 (tiny-denominator/easy-mix gaming), generalised further: five
    # ACCEPTED receipts clear the minimum-adjudicated-evidence floor, but every
    # one of them is a T0 (rename) job -- no T2+ clear -- so a naive reader of
    # coverage alone would mistake this arm for the strongest in the fleet.
    state_dir = parent / "state"
    for index in range(1, 6):
        write_receipt(
            state_dir,
            f"trivial-{index}",
            1,
            "arm_trivial",
            "ACCEPTED",
            task="rename the helper",
            files=["a.py"],
            acceptance_command="python check.py",
        )
    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_trivial")
    assert entry["coverage"] == 1.0, entry
    assert entry["shared_work"] == 0, entry
    assert entry["comparable"] is False, entry
    ok(
        "trivial_tier_arm_not_comparable_even_at_full_coverage: "
        "5/5 ACCEPTED on work no other arm attempted -> coverage 1.0 but comparable=false"
    )


def test_wording_never_confers_comparability(parent: Path) -> None:
    # REGRESSION. Difficulty was once derived from the receipt's task PROSE, and
    # on real receipts it inverted the truth: the local arm was credited with
    # clearing T4 because its request happened to contain a T4 verb, and was
    # marked comparable, while the arm that actually cleared the hard
    # hidden-graded job was marked not comparable. An arm that only ever ran
    # solo work must stay incomparable no matter how impressive its jobs sound.
    state_dir = parent / "state"
    for index, objective in enumerate(
        ["migrate the whole architecture", "decompose and redesign the deploy path"], start=1
    ):
        write_receipt(
            state_dir, f"grand-{index}", 1, "arm_grandiose", "ACCEPTED",
            task=objective, files=["a.py"], acceptance_command=f"python solo_check_{index}.py",
        )
    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_grandiose")
    assert entry["coverage"] == 1.0, entry
    assert entry["shared_work"] == 0, entry
    assert entry["comparable"] is False, entry
    ok("wording_never_confers_comparability: T4-sounding solo work still yields comparable=false")


def test_same_work_groups_across_differing_task_ids(parent: Path) -> None:
    # The charclass bake-off dispatched ONE job to five arms under five distinct
    # task ids. Comparison must group on the work (acceptance + scopes), not the id.
    state_dir = parent / "state"
    shared = {"files": ["fixtures/x/input.py"], "acceptance_command": "python -B check_x.py"}
    write_receipt(state_dir, "job-on-alpha", 1, "arm_alpha", "ACCEPTED", task="implement x", **shared)
    write_receipt(state_dir, "job-on-beta", 1, "arm_beta", "REJECTED", task="implement x", **shared)
    write_receipt(
        state_dir, "solo-on-alpha", 1, "arm_alpha", "ACCEPTED",
        task="implement y", files=["fixtures/y/input.py"], acceptance_command="python -B check_y.py",
    )

    payload = run_report(state_dir)
    head = payload.get("head_to_head")
    assert isinstance(head, dict) and len(head) == 1, head
    contenders = next(iter(head.values()))
    assert set(contenders) == {"arm_alpha", "arm_beta"}, contenders
    assert contenders["arm_alpha"]["accepted"] == 1, contenders
    assert contenders["arm_beta"]["rejected"] == 1, contenders

    alpha = get_arm_entry(payload, "arm_alpha")
    assert alpha["shared_work"] == 1, alpha
    assert alpha["shared_coverage"] == 1.0, alpha
    assert alpha["coverage"] == 1.0, alpha
    beta = get_arm_entry(payload, "arm_beta")
    assert beta["shared_coverage"] == 0.0, beta
    ok(
        "same_work_groups_across_differing_task_ids: identical acceptance+scopes group "
        "under one head_to_head key; the solo job does not"
    )


def test_by_tier_breakdown_sums_to_flat_totals(parent: Path) -> None:
    state_dir = parent / "state"
    write_receipt(
        state_dir, "mix-1", 1, "arm_mixed", "ACCEPTED",
        task="rename x", files=["a.py"], acceptance_command="python check.py",
    )
    write_receipt(
        state_dir, "mix-2", 1, "arm_mixed", "ACCEPTED",
        task="rename y", files=["b.py"], acceptance_command="python check.py",
    )
    write_receipt(
        state_dir, "mix-3", 1, "arm_mixed", "ACCEPTED",
        task="fix the bug", files=["c.py"], acceptance_command="pytest tests/",
    )
    write_receipt(
        state_dir, "mix-4", 1, "arm_mixed", "REJECTED",
        task="fix the bug", files=["d.py"], acceptance_command="pytest tests/",
    )

    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_mixed")
    by_tier = entry["by_requested_tier"]
    summed_accepted = sum(bucket["accepted"] for bucket in by_tier.values())
    summed_rejected = sum(bucket["rejected"] for bucket in by_tier.values())
    assert summed_accepted == entry["accepted"] == 3, (by_tier, entry)
    assert summed_rejected == entry["rejected"] == 1, (by_tier, entry)
    assert by_tier["T0"]["accepted"] == 2, by_tier
    assert by_tier["T2"]["accepted"] == 1 and by_tier["T2"]["rejected"] == 1, by_tier
    ok(
        "by_requested_tier_sums_to_flat_totals: "
        "T0(2 acc) + T2(1 acc/1 rej) sums back to flat accepted=3, rejected=1"
    )


def test_hardest_cleared_null_without_any_accepted(parent: Path) -> None:
    state_dir = parent / "state"
    write_receipt(
        state_dir, "rej-1", 1, "arm_no_accept", "REJECTED",
        task="fix the bug", files=["a.py"], acceptance_command="pytest tests/",
    )
    write_receipt(
        state_dir, "rej-2", 1, "arm_no_accept", "REJECTED",
        task="fix another bug", files=["b.py"], acceptance_command="pytest tests/",
    )
    write_receipt(state_dir, "err-1", 1, "arm_no_accept", "ERROR", errors=["transport timeout"])

    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_no_accept")
    assert entry["coverage"] == 0.0, entry
    assert entry["shared_work"] == 0, entry
    assert entry["comparable"] is False, entry
    ok(
        "no_accept_arm_is_incomparable: "
        "REJECTED/ERROR-only arm reports coverage 0.0 with comparable=false"
    )


def test_flat_coverage_unaffected_by_tier_breakdown(parent: Path) -> None:
    state_dir = parent / "state"
    write_receipt(
        state_dir, "flat-1", 1, "arm_flat", "ACCEPTED",
        task="rename x", files=["a.py"], acceptance_command="python check.py",
    )
    write_receipt(
        state_dir, "flat-2", 1, "arm_flat", "ACCEPTED",
        task="fix the bug", files=["b.py"], acceptance_command="pytest tests/",
    )
    write_receipt(
        state_dir, "flat-3", 1, "arm_flat", "ACCEPTED",
        task="refactor the module", files=["c.py", "d.py", "e.py"], acceptance_command="pytest tests/",
    )
    write_receipt(
        state_dir, "flat-4", 1, "arm_flat", "REJECTED",
        task="fix another bug", files=["f.py"], acceptance_command="pytest tests/",
    )
    write_receipt(state_dir, "flat-5", 1, "arm_flat", "ERROR", errors=["transport timeout"])

    payload = run_report(state_dir)
    entry = get_arm_entry(payload, "arm_flat")
    assert entry["accepted"] == 3, entry
    assert entry["rejected"] == 1, entry
    assert entry["errors"] == 1, entry
    # Same shape as the pre-existing test_coverage_excludes_errors witness:
    # the flat number must be exactly what state-counting alone would give,
    # unperturbed by three of these four adjudicated receipts landing in
    # three different difficulty tiers (T0, T2, T3).
    assert entry["coverage"] == 0.75, entry
    assert sum(b["accepted"] for b in entry["by_requested_tier"].values()) == entry["accepted"], entry
    assert sum(b["rejected"] for b in entry["by_requested_tier"].values()) == entry["rejected"], entry
    ok(
        "flat_coverage_unaffected_by_tier_breakdown: "
        "mixed-tier (T0/T2/T3) receipts still yield flat coverage 0.75"
    )


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="test-route-"))
    tests = [
        test_clerical_job_routes_to_cheap_floor,
        test_tier_is_max_not_last_rule,
        test_directory_scope_escalates,
        test_extensionless_directory_scope_escalates,
        test_unrecognised_job_defaults_to_T2_not_T0,
        test_destructive_verb_escalates_past_default_floor,
        test_local_arm_never_on_default_ladder,
        test_coverage_excludes_errors,
        test_coverage_null_when_no_adjudicated_rows,
        test_trivial_tier_arm_not_comparable_even_at_full_coverage,
        test_wording_never_confers_comparability,
        test_same_work_groups_across_differing_task_ids,
        test_by_tier_breakdown_sums_to_flat_totals,
        test_hardest_cleared_null_without_any_accepted,
        test_flat_coverage_unaffected_by_tier_breakdown,
    ]
    passed = 0
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case)
            passed += 1
        print(f"PASS route {passed}/{len(tests)}")
        return 0
    except AssertionError as exc:
        print(f"FAIL route {passed}/{len(tests)}: {exc}")
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
