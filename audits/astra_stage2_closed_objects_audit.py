#!/usr/bin/env python3
"""Independent adversarial audit of the PR #181 closed-object repair."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from astra_stage2 import contracts
from astra_stage2.calibration import derive_calibration_result
from astra_stage2.canonical import Stage2Error, sha256_object
from astra_stage2.contracts import (
    bind_empirical_control_manifest,
    validate_control_manifest,
    validate_generator_manifest,
    validate_observations,
    validate_plan,
)
from astra_stage2.generator import (
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    empirical_control_template,
)


TARGET_HEAD = "49cd5999437c4eb797073357cc1c17685e4a1895"
TARGET_TREE = "dcaee26ad123842c325909f4a083eb9a1d76c7dc"
ALLOWED_AUDIT_PATHS = {
    ".github/workflows/astra-stage2-closed-objects-audit.yml",
    "audits/astra_stage2_closed_objects_audit.py",
}


def _git(repo_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return process.stdout.strip()


def _rehash(value: dict[str, Any], field: str = "payload_sha256") -> dict[str, Any]:
    value[field] = sha256_object({key: child for key, child in value.items() if key != field})
    return value


def _rehash_observation(row: dict[str, Any]) -> dict[str, Any]:
    return _rehash(row, "record_sha256")


def _empirical_template_with_digests() -> dict[str, Any]:
    template = empirical_control_template()
    for control in template["controls"]:
        identity = control["identity"]
        for field in contracts.IDENTITY_DIGEST_FIELDS:
            identity[field] = sha256_object(
                {"field": field, "role": control["control_id"], "audit": TARGET_HEAD}
            )
    return template


def _rows_for_bound(
    generator: dict[str, Any],
    bound: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = build_calibration_plan(generator, bound)
    identities = {
        control["control_id"]: control["identity_sha256"] for control in bound["controls"]
    }
    rows = build_fixture_observations(plan)
    for row in rows:
        row["evidence_class"] = "empirical_local"
        row["control_identity_sha256"] = identities[row["control_id"]]
        _rehash_observation(row)
    return plan, rows


def _expect_refusal(
    label: str,
    action: Callable[[], Any],
    results: list[dict[str, Any]],
) -> None:
    try:
        action()
    except Stage2Error as exc:
        results.append(
            {
                "label": label,
                "expected": "REFUSAL",
                "observed": "REFUSAL",
                "passed": True,
                "detail": str(exc),
            }
        )
        return
    results.append(
        {
            "label": label,
            "expected": "REFUSAL",
            "observed": "ACCEPTED",
            "passed": False,
            "detail": "malformed object was admitted",
        }
    )


def _candidate_attack(
    label: str,
    action: Callable[[], dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    try:
        result = action()
    except Stage2Error as exc:
        results.append(
            {
                "label": label,
                "expected": "REFUSAL",
                "observed": "REFUSAL",
                "passed": True,
                "detail": str(exc),
            }
        )
        return

    state = result.get("state")
    thresholds = result.get("candidate_thresholds")
    admitted = state == "EMPIRICAL_CALIBRATION_CANDIDATE" and bool(thresholds)
    results.append(
        {
            "label": label,
            "expected": "REFUSAL",
            "observed": state,
            "passed": not admitted,
            "candidate_threshold_count": len(thresholds or {}),
            "detail": (
                "malformed semantic substitution minted an empirical candidate"
                if admitted
                else "no empirical candidate was minted"
            ),
        }
    )


def execute(repo_root: Path) -> dict[str, Any]:
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")
    if _git(repo_root, "merge-base", TARGET_HEAD, audit_head) != TARGET_HEAD:
        raise RuntimeError("audit branch is not rooted in the exact target head")
    target_tree = _git(repo_root, "rev-parse", f"{TARGET_HEAD}^{{tree}}")
    if target_tree != TARGET_TREE:
        raise RuntimeError("target tree does not match the frozen audit coordinate")
    changed_paths = {
        line
        for line in _git(repo_root, "diff", "--name-only", f"{TARGET_HEAD}...{audit_head}").splitlines()
        if line
    }
    if changed_paths != ALLOWED_AUDIT_PATHS:
        raise RuntimeError(
            f"audit branch path set differs: expected {sorted(ALLOWED_AUDIT_PATHS)}, "
            f"observed {sorted(changed_paths)}"
        )
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is not clean")

    generator = build_generator_manifest()
    template = _empirical_template_with_digests()
    bound = bind_empirical_control_manifest(copy.deepcopy(template))
    baseline_plan, baseline_rows = _rows_for_bound(generator, bound)
    baseline = derive_calibration_result(
        baseline_rows,
        baseline_plan,
        bound,
        repo_root=repo_root,
    )
    if baseline.get("state") != "EMPIRICAL_CALIBRATION_CANDIDATE":
        raise RuntimeError("attack fixture no longer reaches the empirical-candidate boundary")

    results: list[dict[str, Any]] = []

    unknown_identity = copy.deepcopy(template)
    unknown_identity["controls"][0]["identity"]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _expect_refusal(
        "unknown control-identity property",
        lambda: bind_empirical_control_manifest(unknown_identity),
        results,
    )

    unknown_manifest = copy.deepcopy(template)
    unknown_manifest["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _expect_refusal(
        "unknown control-manifest property",
        lambda: bind_empirical_control_manifest(unknown_manifest),
        results,
    )

    unknown_control = copy.deepcopy(template)
    unknown_control["controls"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _expect_refusal(
        "unknown control property",
        lambda: bind_empirical_control_manifest(unknown_control),
        results,
    )

    mutated_generator = copy.deepcopy(generator)
    mutated_generator["generator_version"] = "astra-stage2-generator-v999"
    _rehash(mutated_generator)
    _expect_refusal(
        "unfrozen generator-version substitution",
        lambda: validate_generator_manifest(mutated_generator),
        results,
    )

    def stage1_join_substitution() -> dict[str, Any]:
        altered = copy.deepcopy(bound)
        altered["stage1_join_head"] = "f" * 40
        _rehash(altered)
        validate_control_manifest(altered, require_bound_empirical=True)
        plan, rows = _rows_for_bound(generator, altered)
        return derive_calibration_result(rows, plan, altered, repo_root=repo_root)

    _candidate_attack(
        "unfrozen Stage-1 join substitution",
        stage1_join_substitution,
        results,
    )

    def source_identity_substitution() -> dict[str, Any]:
        altered_template = _empirical_template_with_digests()
        identity = altered_template["controls"][0]["identity"]
        identity["source_repository"] = "attacker/substitute-control"
        identity["source_commit_sha1"] = "1" * 40
        altered_bound = bind_empirical_control_manifest(altered_template)
        plan, rows = _rows_for_bound(generator, altered_bound)
        return derive_calibration_result(rows, plan, altered_bound, repo_root=repo_root)

    _candidate_attack(
        "unfrozen control source repository and commit substitution",
        source_identity_substitution,
        results,
    )

    def plan_generator_binding_substitution() -> dict[str, Any]:
        altered_plan = copy.deepcopy(baseline_plan)
        altered_plan["generator_manifest_sha256"] = "0" * 64
        _rehash(altered_plan)
        return derive_calibration_result(
            copy.deepcopy(baseline_rows),
            altered_plan,
            bound,
            repo_root=repo_root,
        )

    _candidate_attack(
        "direct derive with rewritten generator-manifest binding",
        plan_generator_binding_substitution,
        results,
    )

    def plan_observation_id_substitution() -> dict[str, Any]:
        altered_plan = copy.deepcopy(baseline_plan)
        altered_rows = copy.deepcopy(baseline_rows)
        replacement = "s2obs_" + "0" * 24
        if any(item["observation_id"] == replacement for item in altered_plan["observations"]):
            replacement = "s2obs_" + "f" * 24
        altered_plan["observations"][0]["observation_id"] = replacement
        _rehash(altered_plan)
        altered_rows[0]["observation_id"] = replacement
        _rehash_observation(altered_rows[0])
        return derive_calibration_result(
            altered_rows,
            altered_plan,
            bound,
            repo_root=repo_root,
        )

    _candidate_attack(
        "non-derived plan observation-id substitution",
        plan_observation_id_substitution,
        results,
    )

    validate_plan(baseline_plan, generator, bound)
    validate_observations(baseline_rows, baseline_plan, bound)

    failed = [result for result in results if not result["passed"]]
    disposition = (
        "CHANGES_REQUESTED_BEFORE_EMPIRICAL_EXECUTION"
        if failed
        else "AUDIT_PASS_PROVIDER_FREE_ONLY"
    )
    receipt: dict[str, Any] = {
        "record_type": "tier-bench/astra-stage2-closed-object-audit@1",
        "target": {
            "pull_request": 181,
            "head_sha": TARGET_HEAD,
            "tree_sha": TARGET_TREE,
            "active_claim_comment_id": 5519576043,
            "qualification_run_id": 33709644468,
            "evidence_artifact_id": 9876461834,
            "publication_artifact_id": 9876462077,
        },
        "audit": {
            "head_sha": audit_head,
            "tree_sha": audit_tree,
            "changed_paths": sorted(changed_paths),
        },
        "baseline": {
            "state": baseline["state"],
            "candidate_threshold_count": len(baseline.get("candidate_thresholds", {})),
            "stage2_frozen": baseline.get("stage2_frozen"),
        },
        "attacks": results,
        "failed_attack_count": len(failed),
        "failed_attack_labels": [result["label"] for result in failed],
        "disposition": disposition,
        "authority": {
            "target_branch_mutated": False,
            "provider_or_model_calls": 0,
            "audit_script_external_network_calls": 0,
            "workflow_network_egress": "PRESENT_FOR_GIT_AND_ACTION_DOWNLOADS",
            "empirical_control_execution": False,
            "live_provider_dispatch": "PROHIBITED",
            "callable_astra_identity": "UNBOUND",
            "optional_24_call_block": "DISABLED",
            "merge_authority": "NONE",
        },
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = execute(args.repo_root.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
