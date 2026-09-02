"""Thermodynamic and survival analysis for MENACE edge observations."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .menace_edge_common import (
    REPORT_SCHEMA,
    EdgeError,
    TreatmentTotals,
    fraction_record,
    hash_json,
    need_array,
)
from .menace_edge_plan import compile_plan, verify_plan
from .menace_edge_schema import validate_manifest, validate_observation


def _sum_metrics(rows: list[dict[str, Any]]) -> TreatmentTotals:
    metric = lambda key: sum(row["metrics"][key] for row in rows)  # noqa: E731
    return TreatmentTotals(
        planned_cells=0,
        measured_cells=len(rows),
        accepted_products=metric("accepted_products"),
        rejected_products=metric("rejected_products"),
        consequential_misses=metric("consequential_misses"),
        wall_energy_mwh=metric("wall_energy_mwh"),
        gpu_energy_mwh=metric("gpu_energy_mwh"),
        human_active_ms=metric("human_active_ms"),
        external_bytes_in=metric("external_bytes_in"),
        external_bytes_avoided=metric("external_bytes_avoided"),
        role_seconds_served=metric("role_seconds_served"),
        operator_interventions=metric("operator_interventions"),
        max_recovery_ms=max((row["metrics"]["recovery_ms"] for row in rows), default=0),
    )


def _metric_vector(totals: TreatmentTotals) -> dict[str, Any]:
    return {
        "accepted_products": totals.accepted_products,
        "rejected_products": totals.rejected_products,
        "consequential_misses": totals.consequential_misses,
        "wall_energy_mwh": totals.wall_energy_mwh,
        "gpu_energy_mwh": totals.gpu_energy_mwh,
        "human_active_ms": totals.human_active_ms,
        "external_bytes_in": totals.external_bytes_in,
        "external_bytes_avoided": totals.external_bytes_avoided,
        "role_seconds_served": totals.role_seconds_served,
        "operator_interventions": totals.operator_interventions,
        "max_recovery_ms": totals.max_recovery_ms,
        "accepted_products_per_wh": fraction_record(
            totals.accepted_products * 1000, totals.wall_energy_mwh, "accepted_products/Wh"
        ),
        "human_active_ms_per_accepted_product": fraction_record(
            totals.human_active_ms,
            totals.accepted_products,
            "human_active_ms/accepted_product",
        ),
        "external_bytes_avoided_per_wh": fraction_record(
            totals.external_bytes_avoided * 1000,
            totals.wall_energy_mwh,
            "external_bytes/Wh",
        ),
        "role_seconds_served_per_wh": fraction_record(
            totals.role_seconds_served * 1000,
            totals.wall_energy_mwh,
            "role_seconds/Wh",
        ),
    }


def _survival_failures(
    manifest: dict[str, Any],
    plan_cells: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    recovery_limit = manifest["survival_floor"]["max_recovery_ms"]
    for row in rows:
        cell = plan_cells[row["cell_id"]]
        outcomes = row["outcomes"]
        metrics = row["metrics"]
        def add(reason: str) -> None:
            failures.append({"cell_id": row["cell_id"], "reason": reason})

        if outcomes["authority_widened"]:
            add("authority widened")
        if not outcomes["history_preserved"]:
            add("history was not preserved")
        if outcomes["gpu_required_for_basic_state"]:
            add("basic state incorrectly required the burst GPU")
        if outcomes["wan_required_for_basic_state"]:
            add("basic state incorrectly required WAN")
        if cell["faults"] and not outcomes["survival_floor_retained"]:
            add("survival floor was not retained during a declared fault")
        if cell["faults"] and metrics["recovery_ms"] > recovery_limit:
            add("recovery exceeded the declared survival limit")
        for fault in cell["faults"]:
            if fault["human_disposition_required"] and not outcomes["human_disposition_recorded"]:
                add(f"fault {fault['id']} required a human disposition")
            if fault["kind"] in {"remote_local_conflict", "stale_remote_report"}:
                if not outcomes["conflict_disclosed"]:
                    add(f"fault {fault['id']} did not disclose conflict or staleness")
    return failures


def _matched_rows(
    rows: list[dict[str, Any]],
    plan_cells: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {plan_cells[row["cell_id"]]["comparison_key"]: row for row in rows}


def _delta_record(candidate: TreatmentTotals, baseline: TreatmentTotals) -> dict[str, int]:
    return {
        "accepted_products": candidate.accepted_products - baseline.accepted_products,
        "rejected_products": candidate.rejected_products - baseline.rejected_products,
        "consequential_misses": candidate.consequential_misses - baseline.consequential_misses,
        "wall_energy_mwh": candidate.wall_energy_mwh - baseline.wall_energy_mwh,
        "gpu_energy_mwh": candidate.gpu_energy_mwh - baseline.gpu_energy_mwh,
        "human_active_ms_saved": baseline.human_active_ms - candidate.human_active_ms,
        "external_bytes_avoided": (
            candidate.external_bytes_avoided - baseline.external_bytes_avoided
        ),
        "role_seconds_served": candidate.role_seconds_served - baseline.role_seconds_served,
        "operator_interventions_reduced": (
            baseline.operator_interventions - candidate.operator_interventions
        ),
        "max_recovery_ms_change": candidate.max_recovery_ms - baseline.max_recovery_ms,
    }


def analyze(raw_manifest: Any, raw_plan: Any, raw_observations: Any) -> dict[str, Any]:
    manifest = validate_manifest(raw_manifest)
    plan_errors = verify_plan(manifest, raw_plan)
    if plan_errors:
        raise EdgeError("cannot analyze a non-deterministic plan: " + "; ".join(plan_errors))
    plan = compile_plan(manifest)
    cells = {row["cell_id"]: row for row in plan["cells"]}
    observations_raw = need_array(raw_observations, "observations")
    observations = [
        validate_observation(
            item,
            required_metrics=manifest["required_metrics"],
            plan_cells=cells,
            plan_id=plan["plan_id"],
        )
        for item in observations_raw
    ]
    seen: set[str] = set()
    for observation in observations:
        if observation["cell_id"] in seen:
            raise EdgeError(f"duplicate observation cell: {observation['cell_id']}")
        seen.add(observation["cell_id"])

    measured = [row for row in observations if row["status"] == "measured"]
    errored = [row for row in observations if row["status"] == "error"]
    unmeasured = [row for row in observations if row["status"] == "unmeasured"]
    measured_by_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    error_by_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in measured:
        measured_by_treatment[row["treatment_id"]].append(row)
    for row in errored:
        error_by_treatment[row["treatment_id"]].append(row)

    planned_by_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in plan["cells"]:
        planned_by_treatment[cell["treatment_id"]].append(cell)

    baseline_id = manifest["acceptance"]["baseline_treatment"]
    baseline_rows = measured_by_treatment[baseline_id]
    baseline_by_key = _matched_rows(baseline_rows, cells)

    treatments_out = []
    for treatment in manifest["treatments"]:
        treatment_id = treatment["id"]
        rows = measured_by_treatment[treatment_id]
        planned = planned_by_treatment[treatment_id]
        row_by_key = _matched_rows(rows, cells)
        matched_keys = sorted(set(row_by_key) & set(baseline_by_key))
        candidate_matched = [row_by_key[key] for key in matched_keys]
        baseline_matched = [baseline_by_key[key] for key in matched_keys]
        totals = _sum_metrics(rows)
        matched_totals = _sum_metrics(candidate_matched)
        baseline_totals = _sum_metrics(baseline_matched)
        failures = _survival_failures(manifest, cells, rows)
        planned_fault_ids = {
            fault["id"] for cell in planned for fault in cell["faults"]
        }
        measured_fault_ids = {
            fault["id"]
            for row in rows
            for fault in cells[row["cell_id"]]["faults"]
        }
        missing_faults = sorted(planned_fault_ids - measured_fault_ids)
        missing_cells = len(planned) - len(rows) - len(error_by_treatment[treatment_id])
        deltas = _delta_record(matched_totals, baseline_totals)

        consequential_increase = (
            manifest["acceptance"]["require_no_consequential_miss_increase"]
            and treatment_id != baseline_id
            and matched_keys
            and deltas["consequential_misses"] > 0
        )
        complete_enough = (
            len(rows) >= manifest["acceptance"]["minimum_complete_cells"]
            and missing_cells == 0
            and not error_by_treatment[treatment_id]
            and not missing_faults
        )

        if treatment_id == baseline_id:
            verdict = "BASELINE"
        elif failures or consequential_increase:
            verdict = "REJECTED"
        elif not complete_enough or not matched_keys:
            verdict = "HELD"
        elif treatment["claim_class"] == "comparison_only":
            verdict = "COMPARISON_ONLY"
        else:
            weakly_no_worse = (
                deltas["accepted_products"] >= 0
                and deltas["consequential_misses"] <= 0
            )
            materially_better = any(
                (
                    deltas["accepted_products"] > 0,
                    deltas["human_active_ms_saved"] > 0,
                    deltas["external_bytes_avoided"] > 0,
                    deltas["role_seconds_served"] > 0,
                    deltas["operator_interventions_reduced"] > 0,
                )
            )
            verdict = "ADMISSIBLE" if weakly_no_worse and materially_better else "PILOT_ONLY"

        treatments_out.append(
            {
                "treatment_id": treatment_id,
                "title": treatment["title"],
                "claim_class": treatment["claim_class"],
                "verdict": verdict,
                "planned_cells": len(planned),
                "measured_cells": len(rows),
                "error_cells": len(error_by_treatment[treatment_id]),
                "missing_cells": missing_cells,
                "matched_baseline_cells": len(matched_keys),
                "missing_faults": missing_faults,
                "survival_failures": failures,
                "consequential_miss_increase": consequential_increase,
                "metric_vector": _metric_vector(totals),
                "matched_baseline_delta": deltas,
                "production_claim": False,
                "promotion_authorized": False,
            }
        )

    body = {
        "schema": REPORT_SCHEMA,
        "campaign_id": manifest["id"],
        "manifest_sha256": hash_json(manifest),
        "plan_id": plan["plan_id"],
        "baseline_treatment": baseline_id,
        "observations": {
            "submitted": len(observations),
            "measured": len(measured),
            "errors": len(errored),
            "unmeasured": len(unmeasured),
            "planned": len(plan["cells"]),
        },
        "treatments": treatments_out,
        "acceptance_law": manifest["acceptance"],
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"report_id": f"menacereport1_{hash_json(body)}", **body}
