#!/usr/bin/env python3
"""Independent provider-free audit of the Astra Stage 2 semantic-custody assist."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from astra_stage2 import contracts
from astra_stage2.calibration import (
    derive_calibration_result,
    validate_calibration_result,
)
from astra_stage2.canonical import Stage2Error, sha256_object
from astra_stage2.contracts import (
    bind_empirical_control_manifest,
    validate_control_manifest,
    validate_generator_manifest,
    validate_observations,
    validate_plan,
    verify_stage1_blobs,
)
from astra_stage2.generator import (
    EXPECTED_CASE_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    empirical_control_template,
    fixture_control_manifest,
)

PARENT_HEAD = "49cd5999437c4eb797073357cc1c17685e4a1895"
PARENT_TREE = "dcaee26ad123842c325909f4a083eb9a1d76c7dc"
ASSIST_HEAD = "5663e3eb15c92cbb55d708c5fd365c893748e035"
ASSIST_TREE = "720cbf3f26f2e251613acedc52cff08ef33892dc"
ASSIST_PATHS = {
    ".github/workflows/astra-stage2-semantic-custody-assist.yml",
    "astra_stage2/calibration.py",
    "astra_stage2/ci_runner.py",
    "astra_stage2/cli.py",
    "astra_stage2/contracts.py",
    "schemas/astra-stage2-calibration-result.schema.json",
    "tests/test_astra_stage2_calibration.py",
}
AUDIT_PATHS = {
    ".github/workflows/astra-stage2-semantic-custody-final-audit.yml",
    "audits/astra_stage2_semantic_custody_final_audit.py",
}
RECOGNIZED_PROVIDER_ENV = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
}


def _git(repo_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or str(process.returncode)
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return process.stdout.strip()


def _git_success(repo_root: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _changed_paths(repo_root: Path, base: str, head: str) -> set[str]:
    return {
        line
        for line in _git(repo_root, "diff", "--name-only", f"{base}...{head}").splitlines()
        if line
    }


def _rehash(value: dict[str, Any], field: str = "payload_sha256") -> None:
    value[field] = sha256_object(
        {key: child for key, child in value.items() if key != field}
    )


def _ready_empirical_template() -> dict[str, Any]:
    template = empirical_control_template()
    for control in template["controls"]:
        identity = control["identity"]
        for field in contracts.IDENTITY_DIGEST_FIELDS:
            identity[field] = sha256_object(
                {"audit": ASSIST_HEAD, "field": field, "role": control["control_id"]}
            )
    return template


def _empirical_dataset() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    generator = build_generator_manifest()
    bound = bind_empirical_control_manifest(_ready_empirical_template())
    plan = build_calibration_plan(generator, bound)
    identities = {
        control["control_id"]: control["identity_sha256"]
        for control in bound["controls"]
    }
    rows = build_fixture_observations(plan)
    for row in rows:
        row["evidence_class"] = "empirical_local"
        row["control_identity_sha256"] = identities[row["control_id"]]
        _rehash(row, "record_sha256")
    return generator, bound, plan, rows


def _require_refusal(
    label: str,
    action: Callable[[], Any],
    attacks: list[dict[str, Any]],
) -> None:
    try:
        action()
    except Stage2Error as exc:
        attacks.append(
            {
                "label": label,
                "expected": "REFUSAL",
                "observed": "REFUSAL",
                "passed": True,
                "detail": str(exc),
            }
        )
        return
    attacks.append(
        {
            "label": label,
            "expected": "REFUSAL",
            "observed": "ACCEPTED",
            "passed": False,
            "detail": "authority-bearing mutation was admitted",
        }
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute(repo_root: Path) -> dict[str, Any]:
    audit_head = _git(repo_root, "rev-parse", "HEAD")
    audit_tree = _git(repo_root, "rev-parse", "HEAD^{tree}")
    if _git(repo_root, "rev-parse", f"{PARENT_HEAD}^{{tree}}") != PARENT_TREE:
        raise RuntimeError("parent tree differs from the frozen audit coordinate")
    if _git(repo_root, "rev-parse", f"{ASSIST_HEAD}^{{tree}}") != ASSIST_TREE:
        raise RuntimeError("assist tree differs from the frozen audit coordinate")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", PARENT_HEAD, ASSIST_HEAD):
        raise RuntimeError("assist head is not descended from the exact parent")
    if not _git_success(repo_root, "merge-base", "--is-ancestor", ASSIST_HEAD, audit_head):
        raise RuntimeError("audit head is not descended from the exact assist head")
    assist_paths = _changed_paths(repo_root, PARENT_HEAD, ASSIST_HEAD)
    audit_paths = _changed_paths(repo_root, ASSIST_HEAD, audit_head)
    if assist_paths != ASSIST_PATHS:
        raise RuntimeError(
            f"assist path set mismatch: expected={sorted(ASSIST_PATHS)}, "
            f"observed={sorted(assist_paths)}"
        )
    if audit_paths != AUDIT_PATHS:
        raise RuntimeError(
            f"audit path set mismatch: expected={sorted(AUDIT_PATHS)}, "
            f"observed={sorted(audit_paths)}"
        )
    if _git(repo_root, "status", "--porcelain"):
        raise RuntimeError("audit checkout is not clean")

    provider_credentials = sorted(
        name for name in RECOGNIZED_PROVIDER_ENV if os.environ.get(name)
    )
    if provider_credentials:
        raise RuntimeError(
            "recognized provider credentials are present: " + ", ".join(provider_credentials)
        )

    stage1_blobs = verify_stage1_blobs(repo_root)
    if stage1_blobs != contracts.STAGE1_BLOBS:
        raise RuntimeError("Stage 1 blob set did not rederive exactly")

    generator = build_generator_manifest()
    fixture_control = fixture_control_manifest()
    fixture_plan = build_calibration_plan(generator, fixture_control)
    fixture_rows = build_fixture_observations(fixture_plan)
    validate_generator_manifest(generator)
    validate_control_manifest(fixture_control)
    validate_plan(fixture_plan, generator, fixture_control)
    validated_rows, fixture_class = validate_observations(
        fixture_rows, fixture_plan, fixture_control
    )
    fixture_result = derive_calibration_result(
        validated_rows,
        fixture_plan,
        fixture_control,
        generator_manifest=generator,
        repo_root=repo_root,
    )
    validate_calibration_result(
        fixture_result,
        generator_manifest=generator,
        control_manifest=fixture_control,
        plan=fixture_plan,
        observations=validated_rows,
        repo_root=repo_root,
    )
    if generator["case_count"] != EXPECTED_CASE_COUNT or len(generator["cases"]) != 108:
        raise RuntimeError("generator denominator differs from 108")
    if fixture_plan["observation_count"] != EXPECTED_OBSERVATION_COUNT:
        raise RuntimeError("plan denominator differs from 648")
    if len(fixture_rows) != 648:
        raise RuntimeError("fixture observation denominator differs from 648")
    if fixture_class != "fixture_synthetic":
        raise RuntimeError("fixture evidence class changed")
    if fixture_result["state"] != "FIXTURE_CONFORMANCE_ONLY":
        raise RuntimeError("fixture result gained empirical authority")
    if fixture_result["stage2_frozen"] is not False:
        raise RuntimeError("fixture result froze Stage 2")
    if fixture_result["candidate_thresholds"] != {}:
        raise RuntimeError("fixture result retained candidate thresholds")
    if fixture_result["feature_sample_count"] != 36:
        raise RuntimeError("feature sample denominator differs from 36")

    empirical_generator, bound, empirical_plan, empirical_rows = _empirical_dataset()
    baseline = derive_calibration_result(
        empirical_rows,
        empirical_plan,
        bound,
        generator_manifest=empirical_generator,
        repo_root=repo_root,
    )
    if baseline["state"] != "EMPIRICAL_CALIBRATION_CANDIDATE":
        raise RuntimeError("attack baseline no longer reaches the candidate boundary")
    if len(baseline["candidate_thresholds"]) != 4:
        raise RuntimeError("attack baseline no longer carries four candidate thresholds")

    attacks: list[dict[str, Any]] = []

    wrong_answer_rows = copy.deepcopy(empirical_rows)
    wrong_answer_rows[0]["observed_checksum"] = "0" * 16
    if wrong_answer_rows[0]["observed_checksum"] == wrong_answer_rows[0]["expected_checksum"]:
        wrong_answer_rows[0]["observed_checksum"] = "f" * 16
    wrong_answer_rows[0]["accepted"] = False
    _rehash(wrong_answer_rows[0], "record_sha256")
    _require_refusal(
        "correctly marked wrong deterministic answer",
        lambda: derive_calibration_result(
            wrong_answer_rows,
            empirical_plan,
            bound,
            generator_manifest=empirical_generator,
            repo_root=repo_root,
        ),
        attacks,
    )

    unknown_observation = copy.deepcopy(empirical_rows)
    unknown_observation[0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _rehash(unknown_observation[0], "record_sha256")
    _require_refusal(
        "unknown observation property",
        lambda: derive_calibration_result(
            unknown_observation,
            empirical_plan,
            bound,
            generator_manifest=empirical_generator,
            repo_root=repo_root,
        ),
        attacks,
    )

    unknown_manifest = _ready_empirical_template()
    unknown_manifest["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _require_refusal(
        "unknown control-manifest property",
        lambda: bind_empirical_control_manifest(unknown_manifest),
        attacks,
    )

    unknown_control = _ready_empirical_template()
    unknown_control["controls"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
    _require_refusal(
        "unknown control property",
        lambda: bind_empirical_control_manifest(unknown_control),
        attacks,
    )

    unknown_identity = _ready_empirical_template()
    unknown_identity["controls"][0]["identity"]["notes"] = (
        "PRIVATE_TRANSCRIPT_CANARY"
    )
    _require_refusal(
        "unknown control-identity property",
        lambda: bind_empirical_control_manifest(unknown_identity),
        attacks,
    )

    changed_version = copy.deepcopy(empirical_generator)
    changed_version["generator_version"] = "astra-stage2-generator-v999"
    _rehash(changed_version)
    _require_refusal(
        "unfrozen generator-version substitution",
        lambda: validate_generator_manifest(changed_version),
        attacks,
    )

    changed_join = _ready_empirical_template()
    changed_join["stage1_join_head"] = "f" * 40
    _require_refusal(
        "unfrozen Stage 1 join substitution",
        lambda: bind_empirical_control_manifest(changed_join),
        attacks,
    )

    changed_repository = _ready_empirical_template()
    changed_repository["controls"][0]["identity"]["source_repository"] = (
        "attacker/substitute-control"
    )
    _require_refusal(
        "unfrozen control source repository substitution",
        lambda: bind_empirical_control_manifest(changed_repository),
        attacks,
    )

    changed_commit = _ready_empirical_template()
    changed_commit["controls"][0]["identity"]["source_commit_sha1"] = "1" * 40
    _require_refusal(
        "unfrozen control source commit substitution",
        lambda: bind_empirical_control_manifest(changed_commit),
        attacks,
    )

    changed_binding = copy.deepcopy(empirical_plan)
    changed_binding["generator_manifest_sha256"] = "0" * 64
    _rehash(changed_binding)
    _require_refusal(
        "direct derive with rewritten generator-manifest binding",
        lambda: derive_calibration_result(
            copy.deepcopy(empirical_rows),
            changed_binding,
            bound,
            generator_manifest=empirical_generator,
            repo_root=repo_root,
        ),
        attacks,
    )

    changed_plan = copy.deepcopy(empirical_plan)
    changed_rows = copy.deepcopy(empirical_rows)
    replacement = "s2obs_" + "0" * 24
    if any(item["observation_id"] == replacement for item in changed_plan["observations"]):
        replacement = "s2obs_" + "f" * 24
    changed_plan["observations"][0]["observation_id"] = replacement
    _rehash(changed_plan)
    changed_rows[0]["observation_id"] = replacement
    _rehash(changed_rows[0], "record_sha256")
    _require_refusal(
        "non-derived plan observation-id substitution",
        lambda: derive_calibration_result(
            changed_rows,
            changed_plan,
            bound,
            generator_manifest=empirical_generator,
            repo_root=repo_root,
        ),
        attacks,
    )

    fabricated_result = copy.deepcopy(baseline)
    fabricated_result["candidate_thresholds"] = {"fabricated": 999.0}
    fabricated_result["separation_checks"] = []
    fabricated_result["envelopes"] = {}
    _rehash(fabricated_result)
    _require_refusal(
        "self-consistent fabricated empirical result",
        lambda: validate_calibration_result(
            fabricated_result,
            generator_manifest=empirical_generator,
            control_manifest=bound,
            plan=empirical_plan,
            observations=empirical_rows,
            repo_root=repo_root,
        ),
        attacks,
    )

    altered_rows = copy.deepcopy(empirical_rows)
    altered_rows[0]["latency_ms"] += 1.0
    _rehash(altered_rows[0], "record_sha256")
    _require_refusal(
        "result replay against a different observation set",
        lambda: validate_calibration_result(
            baseline,
            generator_manifest=empirical_generator,
            control_manifest=bound,
            plan=empirical_plan,
            observations=altered_rows,
            repo_root=repo_root,
        ),
        attacks,
    )

    _require_refusal(
        "result validation without the complete input graph",
        lambda: validate_calibration_result(baseline),
        attacks,
    )

    failed = [attack for attack in attacks if not attack["passed"]]
    receipt: dict[str, Any] = {
        "record_type": "tier-bench/astra-stage2-semantic-custody-final-audit@1",
        "target": {
            "parent_pr": 181,
            "parent_head": PARENT_HEAD,
            "parent_tree": PARENT_TREE,
            "assist_pr": 184,
            "assist_head": ASSIST_HEAD,
            "assist_tree": ASSIST_TREE,
            "assist_qualification_run": 33719222347,
            "assist_artifact": 9879614150,
        },
        "audit": {
            "head_sha": audit_head,
            "tree_sha": audit_tree,
            "assist_paths": sorted(assist_paths),
            "audit_paths": sorted(audit_paths),
        },
        "rederived": {
            "stage1_join_head": contracts.STAGE1_JOIN_HEAD,
            "stage1_blobs": stage1_blobs,
            "generator_cases": len(generator["cases"]),
            "plan_rows": len(fixture_plan["observations"]),
            "fixture_rows": len(fixture_rows),
            "feature_samples": fixture_result["feature_sample_count"],
            "fixture_state": fixture_result["state"],
            "fixture_stage2_frozen": fixture_result["stage2_frozen"],
            "fixture_candidate_thresholds": fixture_result["candidate_thresholds"],
            "generator_manifest_sha256": generator["payload_sha256"],
            "fixture_control_manifest_sha256": fixture_control["payload_sha256"],
            "fixture_plan_sha256": fixture_plan["payload_sha256"],
            "fixture_result_sha256": fixture_result["payload_sha256"],
            "empirical_baseline_state": baseline["state"],
            "empirical_baseline_threshold_count": len(
                baseline["candidate_thresholds"]
            ),
            "empirical_baseline_input_binding_sha256": baseline[
                "input_binding_sha256"
            ],
            "empirical_baseline_observation_set_sha256": baseline[
                "observation_set_sha256"
            ],
        },
        "attacks": attacks,
        "attack_count": len(attacks),
        "refused_count": len(attacks) - len(failed),
        "failed_count": len(failed),
        "failed_labels": [attack["label"] for attack in failed],
        "source_file_sha256": {
            path: _sha256_file(repo_root / path)
            for path in sorted(ASSIST_PATHS)
            if not path.startswith(".github/workflows/")
        },
        "disposition": (
            "PASS_PROVIDER_FREE_ASSIST_ONLY"
            if not failed
            else "CHANGES_REQUESTED_BEFORE_EMPIRICAL_EXECUTION"
        ),
        "authority": {
            "target_branch_mutated": False,
            "assist_branch_mutated": False,
            "empirical_subject_execution": False,
            "provider_or_model_calls": 0,
            "live_provider_dispatch": "PROHIBITED",
            "callable_astra_identity": "UNBOUND",
            "optional_24_call_block": "DISABLED",
            "numeric_stage2_freeze": "PROHIBITED",
            "merge_authority": "NONE",
            "benchmark_verdict_authority": "NONE",
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
    if receipt["failed_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
