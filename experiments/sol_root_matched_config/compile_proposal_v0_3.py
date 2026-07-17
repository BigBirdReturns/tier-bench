"""Compile the proposal-only Sol-root v0.3 schedule and contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PREFIX = "tier-bench/sol-root-matched-config"
STATUS = "proposal_only_unactivated_unfrozen"
OUTPUTS = {
    "schedule": "schedule_proposal_v0_3.json",
    "acceptance": "acceptance_contract_proposal_v0_3.json",
    "custody": "custody_contract_proposal_v0_3.json",
    "receipt": "offline_verification_receipt_v0_3.json",
}
COMPILER_SHA256 = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class ProposalError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProposalError(message)


def integer(value: Any, name: str, minimum: int = 0) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= minimum, f"invalid {name}")
    return value


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def component(name: str, formula: str, calls: int, conditional: bool = False) -> dict[str, Any]:
    return {"name": name, "formula": formula, "call_ceiling": calls, "conditional": conditional}


def total(items: list[dict[str, Any]]) -> int:
    return sum(item["call_ceiling"] for item in items)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(f"cannot load {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def validate_inputs(catalog: dict[str, Any], design: dict[str, Any]) -> tuple[int, str]:
    require(catalog.get("schema") == f"{PREFIX}/catalog-projection@0.2", "wrong catalog schema")
    require(catalog.get("status") == STATUS, "catalog is not proposal-only")
    require(design.get("schema") == f"{PREFIX}/design-proposal@0.3", "wrong design schema")
    require(design.get("status") == STATUS, "design is not proposal-only")
    pinned = design.get("pinned_owner_cell_id")
    matches = [cell for cell in catalog.get("cells", []) if cell.get("cell_id") == pinned]
    require(len(matches) == 1 and matches[0].get("model") == "gpt-5.6-sol", "pinned owner cell missing or not Sol")
    authority = design.get("catalog_authority", {})
    require(authority.get("primary") == "codex_debug_models_json", "CLI catalog must be primary")
    require(authority.get("display_screenshot_role") == "corroboration_only", "screenshot may only corroborate")
    require(authority.get("invocation_equivalence_proven") is False, "proposal cannot pre-prove invocation equivalence")
    reporting = design.get("reporting", {})
    require(reporting.get("schedule_may_depend_on_ratio_points") is False, "schedule must be threshold-independent")
    points = reporting.get("gross_token_ratio_points")
    require(isinstance(points, list) and len(points) > 0, "reporting points missing")
    require(all(isinstance(point, (int, float)) and not isinstance(point, bool) and 0 < point <= 1 for point in points), "invalid reporting point")
    executors = integer(catalog["counts"]["advertised_configuration_cells"], "executor cells", 1)
    return executors, pinned


def compile_schedule(catalog: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    executor_count, pinned = validate_inputs(catalog, design)
    atomic_cfg = design["atomic_direct"]
    gate = integer(atomic_cfg["gate_observations_per_cell"], "gate", 1)
    crates = integer(atomic_cfg["confirmation_crates"], "crates", 1)
    reps = integer(atomic_cfg["confirmation_replicates"], "replicates", 1)
    executor_cap = min(integer(atomic_cfg["executor_confirmation_cap"], "executor cap", 1), executor_count)
    atomic = [
        component("pinned_owner_gate", f"1*{gate}", gate),
        component("pinned_owner_confirmation", f"1*{crates}*{reps}", crates * reps),
        component("executor_gate", f"{executor_count}*{gate}", executor_count * gate),
        component("executor_confirmation", f"{executor_cap}*{crates}*{reps}", executor_cap * crates * reps),
    ]

    frozen = design["frozen_plan_direct"]
    families = integer(frozen["families"], "frozen families", 1)
    widths = [integer(n, "frozen width", 1) for n in frozen["widths"]]
    hands = min(integer(frozen["executor_cells"], "frozen executor cells", 1), executor_count)
    b_max = integer(frozen["baseline_call_ceiling"], "baseline ceiling", 1)
    plan_calls = integer(frozen["plan_calls_per_family_width"], "plan calls", 1)
    closeout = integer(frozen["closeout_calls_per_executor_graph"], "closeout", 0)
    frozen_direct = [
        component("sealed_plan_production", f"{families}*{len(widths)}*{plan_calls}", families * len(widths) * plan_calls),
        component("matched_sol_baseline", f"{families}*{len(widths)}*{b_max}", families * len(widths) * b_max),
        component("executor_graphs", f"{hands}*{families}*sum(n+{closeout})", hands * families * sum(n + closeout for n in widths)),
    ]

    validation = design["composition_validation"]
    vf = integer(validation["positive_families"], "validation families", 1)
    vw = [integer(n, "validation width", 1) for n in validation["widths"]]
    vh = min(integer(validation["executor_cells"], "validation executors", 1), executor_count)
    vb = integer(validation["baseline_call_ceiling"], "validation baseline", 1)
    nt = integer(validation["negative_tasks"], "negative tasks", 1)
    nw = integer(validation["negative_width"], "negative width", 1)
    nh = integer(validation["negative_executor_cells"], "negative executors", 1)
    composition = [
        component("matched_sol_baseline", f"{vf}*{len(vw)}*{vb}", vf * len(vw) * vb),
        component("observed_direct_e2e", f"{vh}*{vf}*sum(n+2)", vh * vf * sum(n + 2 for n in vw)),
        component("negative_controls", f"{nt}*({vb}+{nh}*({nw}+2))", nt * (vb + nh * (nw + 2))),
    ]
    require(validation.get("additivity_tolerance_status") == "GATED_UNFROZEN", "additivity tolerance must remain gated")
    require(validation.get("failure_default") == "composition_rejected_fresh_end_to_end_required", "composition must fail closed")

    hold = design["holdout_direct"]
    repos = integer(hold["repositories"], "holdout repositories", 1)
    hf = integer(hold["positive_families"], "holdout families", 1)
    seeds = integer(hold["seeds"], "holdout seeds", 1)
    hw = [integer(n, "holdout width", 1) for n in hold["widths"]]
    hb = integer(hold["baseline_call_ceiling"], "holdout baseline", 1)
    hnt = integer(hold["negative_tasks"], "holdout negatives", 1)
    hnw = integer(hold["negative_width"], "holdout negative width", 1)
    cases = repos * hf * seeds
    holdout = [
        component("matched_sol_baseline", f"{cases}*{len(hw)}*{hb}", cases * len(hw) * hb),
        component("adaptive_direct_positive", f"{cases}*sum(n+2)", cases * sum(n + 2 for n in hw)),
        component("negative_boundary", f"{hnt}*({hb}+{hnw}+2)", hnt * (hb + hnw + 2)),
    ]

    sentinel = design["paired_sentinels"]
    engine_count = len(sentinel.get("engines", []))
    require(engine_count == 2 and sentinel.get("packet_bytes_must_match") is True, "sentinels must be paired byte-identically")
    sentinel_calls = (integer(sentinel["phase_count"], "sentinel phases", 1)
                      * integer(sentinel["boundaries_per_phase"], "sentinel boundaries", 1)
                      * integer(sentinel["probes_per_engine_per_boundary"], "sentinel probes", 1)
                      * engine_count)

    deferred = design["deferred_topology_c"]
    require(deferred.get("activation_gate") == "direct_a_quality_noninferior_and_median_ratio_below_1", "C gate must not use the 60% target")
    coordinator_count = executor_count
    coordinator_cap = min(integer(deferred["coordinator_confirmation_cap"], "coordinator cap", 1), coordinator_count)
    deferred_atomic = [
        component("coordinator_gate", f"{coordinator_count}*{gate}", coordinator_count * gate, True),
        component("coordinator_confirmation", f"{coordinator_cap}*{crates}*{reps}", coordinator_cap * crates * reps, True),
    ]
    pairs = integer(deferred["coordinator_pairs"], "coordinator pairs", 1)
    cf = integer(deferred["families"], "coordinator families", 1)
    cw = [integer(n, "coordinator width", 1) for n in deferred["widths"]]
    deferred_topology = [component("coordinator_graphs", f"{pairs}*{cf}*sum(n+1)", pairs * cf * sum(n + 1 for n in cw), True)]
    vp = integer(deferred["composition_pairs"], "composition pairs", 1)
    vcf = integer(deferred["composition_families"], "composition families", 1)
    vcw = [integer(n, "composition C width", 1) for n in deferred["composition_widths"]]
    cnt = integer(deferred["negative_tasks"], "coordinator negatives", 1)
    cnw = integer(deferred["negative_width"], "coordinator negative width", 1)
    deferred_composition = [
        component("matched_sol_baseline", f"{vcf}*{len(vcw)}*{vb}", vcf * len(vcw) * vb, True),
        component("observed_coordinator_e2e", f"{vp}*{vcf}*sum(n+3)", vp * vcf * sum(n + 3 for n in vcw), True),
        component("coordinator_negative_controls", f"{cnt}*({vb}+{cnw}+3)", cnt * (vb + cnw + 3), True),
    ]

    phase_totals = {
        "atomic_direct": total(atomic),
        "frozen_plan_direct": total(frozen_direct),
        "composition_validation": total(composition),
        "holdout_direct": total(holdout),
        "paired_cross_engine_sentinels": sentinel_calls,
    }
    initial_total = sum(phase_totals.values())
    deferred_totals = {
        "coordinator_atomic": total(deferred_atomic),
        "coordinator_topology": total(deferred_topology),
        "coordinator_composition_validation": total(deferred_composition),
    }
    hand_repairs = (hands * families * sum(widths)
                    + vh * vf * sum(vw) + nt * nh * nw
                    + cases * sum(hw) + hnt * hnw)
    canary_initial = 1 + executor_count
    canary_deferred = coordinator_count
    return {
        "schema": f"{PREFIX}/schedule-proposal@0.3",
        "status": STATUS,
        "provider_calls_authorized": False,
        "scientific_schedule_frozen": False,
        "pinned_owner_cell_id": pinned,
        "catalog_cells": {"owner": 1, "executor": executor_count, "coordinator_deferred": coordinator_count},
        "reporting_ratio_points": design["reporting"]["gross_token_ratio_points"],
        "schedule_depends_on_reporting_ratio_points": False,
        "phases": {
            "atomic_direct": {"components": atomic, "call_ceiling": phase_totals["atomic_direct"]},
            "frozen_plan_direct": {"components": frozen_direct, "call_ceiling": phase_totals["frozen_plan_direct"]},
            "composition_validation": {"components": composition, "call_ceiling": phase_totals["composition_validation"], "additivity_tolerance_status": "GATED_UNFROZEN", "failure_default": validation["failure_default"]},
            "holdout_direct": {"components": holdout, "call_ceiling": phase_totals["holdout_direct"]},
            "paired_cross_engine_sentinels": {"call_ceiling": sentinel_calls, "calls_per_engine": sentinel_calls // engine_count},
        },
        "initial_scientific_call_ceiling": initial_total,
        "administrative_canary_ceiling_if_separately_authorized": {"initial_owner_executor": canary_initial, "deferred_coordinator": canary_deferred},
        "deferred_topology_c": {
            "activation_gate": deferred["activation_gate"],
            "phases": {
                "atomic": {"components": deferred_atomic, "call_ceiling": deferred_totals["coordinator_atomic"]},
                "topology": {"components": deferred_topology, "call_ceiling": deferred_totals["coordinator_topology"]},
                "composition_validation": {"components": deferred_composition, "call_ceiling": deferred_totals["coordinator_composition_validation"]},
            },
            "scientific_call_ceiling": sum(deferred_totals.values()),
        },
        "conditional_repair": {
            "maximum_hand_repairs": hand_repairs,
            "absolute_initial_call_ceiling": initial_total + hand_repairs,
        },
        "provider_calls": 0,
        "scientific_observations": 0,
    }


def compile_acceptance(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": f"{PREFIX}/acceptance-contract-proposal@0.3",
        "status": STATUS,
        "primary_whole_task_authority": ["controller_observed_allowed_path_diff", "deterministic_visible_validator", "sealed_hidden_grader"],
        "sol_state_ownership": "workflow_only_not_primary_grade",
        "model_narration_is_grade": False,
        "above_ruler_judgment": {
            "primary_result_eligible": False,
            "required_fields": ["grader_engine", "grader_lineage", "subject_lineage", "shares_subject_lineage", "cross_engine_grader_flag", "rationale_hash"],
            "confirmatory_requirement": "independent_adjudication_or_report_as_qualitative_only",
        },
        "grader_implementation_authorized": False,
        "hidden_vectors_created": False,
        "provider_calls": 0,
    }


def compile_custody() -> dict[str, Any]:
    return {
        "schema": f"{PREFIX}/custody-contract-proposal@0.3",
        "status": STATUS,
        "portable_ref_fields": ["repo", "commit", "path", "blob_sha256"],
        "states": ["prepared_local", "reachable_unverified", "cross_engine_verified_unmerged", "custody_closed", "custody_failed"],
        "transitions": [
            {"from": "prepared_local", "to": "reachable_unverified", "evidence": "exact Sol commit pushed to named codex branch"},
            {"from": "reachable_unverified", "to": "cross_engine_verified_unmerged", "evidence": "cold Claude checkout, digest checks, regressions, reproduced counts, receipt on claude/*"},
            {"from": "reachable_unverified", "to": "custody_failed", "evidence": "preserved divergence receipt on claude/*"},
            {"from": "cross_engine_verified_unmerged", "to": "custody_closed", "evidence": "separately authorized receipt PR merged"},
        ],
        "receipt_required_fields": ["schema", "engine_id", "lineage", "source_commit", "commit_oid_verified", "blob_results", "test_results", "reproduced_counts", "disposition"],
        "pr_authorized": False,
        "merge_authorized": False,
        "provider_calls": 0,
    }


def count_signature(schedule: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase_calls": {name: phase["call_ceiling"] for name, phase in schedule["phases"].items()},
        "initial": schedule["initial_scientific_call_ceiling"],
        "canary": schedule["administrative_canary_ceiling_if_separately_authorized"],
        "deferred_c": schedule["deferred_topology_c"]["scientific_call_ceiling"],
        "repair": schedule["conditional_repair"],
    }


def verification(catalog: dict[str, Any], design: dict[str, Any], schedule: dict[str, Any], acceptance: dict[str, Any], custody: dict[str, Any]) -> dict[str, Any]:
    expected_schedule = compile_schedule(catalog, design)
    expected_acceptance = compile_acceptance(design)
    expected_custody = compile_custody()
    alternate_design = json.loads(json.dumps(design))
    alternate_design["reporting"]["gross_token_ratio_points"] = [0.33, 0.5, 0.67]
    alternate_schedule = compile_schedule(catalog, alternate_design)
    checks = {
        "schedule_exact_match": schedule == expected_schedule,
        "acceptance_exact_match": acceptance == expected_acceptance,
        "custody_exact_match": custody == expected_custody,
        "pinned_owner_exactly_one": schedule.get("catalog_cells", {}).get("owner") == 1,
        "threshold_independent": (schedule.get("schedule_depends_on_reporting_ratio_points") is False
                                  and count_signature(schedule) == count_signature(alternate_schedule)),
        "composition_fails_closed": schedule.get("phases", {}).get("composition_validation", {}).get("failure_default") == "composition_rejected_fresh_end_to_end_required",
        "topology_c_deferred": schedule.get("deferred_topology_c", {}).get("scientific_call_ceiling", 0) > 0,
        "deterministic_grader_precedence": acceptance.get("sol_state_ownership") == "workflow_only_not_primary_grade",
        "custody_requires_remote_receipt": "cross_engine_verified_unmerged" in custody.get("states", []),
    }
    return {
        "schema": f"{PREFIX}/offline-verification@0.3",
        "status": STATUS,
        "checks": checks,
        "all_pass": all(checks.values()),
        "canonical_sha256": {"compiler": COMPILER_SHA256, "catalog": digest(catalog), "design": digest(design), "schedule": digest(schedule), "acceptance": digest(acceptance), "custody": digest(custody)},
        "provider_calls": 0,
        "scientific_observations": 0,
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"refusing to overwrite {path}")
    path.write_bytes(canonical(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("compile-all")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--design", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--catalog", type=Path, required=True)
    verify.add_argument("--design", type=Path, required=True)
    verify.add_argument("--schedule", type=Path, required=True)
    verify.add_argument("--acceptance", type=Path, required=True)
    verify.add_argument("--custody", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        catalog, design = load(args.catalog), load(args.design)
        if args.action == "compile-all":
            require(not args.out.exists(), f"refusing to overwrite {args.out}")
            args.out.mkdir(parents=True)
            schedule = compile_schedule(catalog, design)
            acceptance = compile_acceptance(design)
            custody = compile_custody()
            receipt = verification(catalog, design, schedule, acceptance, custody)
            write_new(args.out / OUTPUTS["schedule"], schedule)
            write_new(args.out / OUTPUTS["acceptance"], acceptance)
            write_new(args.out / OUTPUTS["custody"], custody)
            write_new(args.out / OUTPUTS["receipt"], receipt)
        else:
            receipt = verification(catalog, design, load(args.schedule), load(args.acceptance), load(args.custody))
        print(canonical(receipt).decode("utf-8"), end="")
        return 0 if receipt["all_pass"] else 2
    except ProposalError as exc:
        print(f"proposal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
