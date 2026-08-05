"""Deterministic Venn census and minimal witness selection for MENACE edge."""
from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable

from .menace_edge_common import EdgeError, canonical_bytes, hash_json
from .menace_seam_schema import (
    PLAN_SCHEMA,
    REPORT_SCHEMA,
    validate_coverage_matrix,
    validate_donor_piles,
    validate_seam_catalog,
)


def validate_bundle(
    raw_donors: Any,
    raw_seams: Any,
    raw_coverage: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    donors = validate_donor_piles(raw_donors)
    seams = validate_seam_catalog(raw_seams)
    coverage = validate_coverage_matrix(raw_coverage, donors, seams)
    return donors, seams, coverage


def _selection_support(
    selected: Iterable[dict[str, Any]],
    seam_id: str,
) -> dict[str, Any]:
    witnesses = [item for item in selected if seam_id in item["covers_seams"]]
    return {
        "witnesses": sorted(item["id"] for item in witnesses),
        "piles": sorted({pile for item in witnesses for pile in item["donor_piles"]}),
        "evidence_classes": sorted({item["evidence_class"] for item in witnesses}),
        "independence_groups": sorted(
            {group for item in witnesses for group in item["independence_groups"]}
        ),
    }


def _feasibility(
    selected: tuple[dict[str, Any], ...],
    seam_catalog: dict[str, Any],
    coverage: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    constraints = coverage["selection_constraints"]
    selected_ids = {item["id"] for item in selected}
    evidence_classes = {item["evidence_class"] for item in selected}
    selected_seams = {seam for item in selected for seam in item["covers_seams"]}
    selected_negative = {
        witness for item in selected for witness in item["covers_negative_witnesses"]
    }
    required_seams = {
        item["id"]
        for item in seam_catalog["seams"]
        if item["mandatory"] and constraints["require_all_mandatory_seams"]
    }
    required_negative = {
        item["id"]
        for item in seam_catalog["negative_witnesses"]
        if item["mandatory"]
        and constraints["require_all_mandatory_negative_witnesses"]
    }
    missing_prerequisites = sorted(
        {
            prerequisite
            for item in selected
            for prerequisite in item["prerequisites"]
            if prerequisite not in selected_ids
        }
    )
    missing_evidence = sorted(
        set(constraints["required_evidence_classes"]) - evidence_classes
    )
    missing_seams = sorted(required_seams - selected_seams)
    missing_negative = sorted(required_negative - selected_negative)
    pile_deficits = []
    for seam in seam_catalog["seams"]:
        if seam["id"] not in required_seams:
            continue
        support = _selection_support(selected, seam["id"])
        if len(support["piles"]) < seam["minimum_independent_piles"]:
            pile_deficits.append(
                {
                    "seam_id": seam["id"],
                    "required": seam["minimum_independent_piles"],
                    "observed": len(support["piles"]),
                    "piles": support["piles"],
                }
            )
    detail = {
        "missing_prerequisites": missing_prerequisites,
        "missing_evidence_classes": missing_evidence,
        "missing_seams": missing_seams,
        "missing_negative_witnesses": missing_negative,
        "pile_support_deficits": pile_deficits,
    }
    return not any(detail.values()), detail


def compile_plan(raw_donors: Any, raw_seams: Any, raw_coverage: Any) -> dict[str, Any]:
    donors, seam_catalog, coverage = validate_bundle(raw_donors, raw_seams, raw_coverage)
    constraints = coverage["selection_constraints"]
    admissible = [
        item for item in coverage["witnesses"] if item["state"] in constraints["admissible_states"]
    ]
    solutions: list[tuple[tuple[Any, ...], tuple[dict[str, Any], ...]]] = []
    evaluated = 0
    maximum = min(constraints["maximum_witnesses"], len(admissible))
    for size in range(1, maximum + 1):
        for selected in combinations(admissible, size):
            evaluated += 1
            feasible, _ = _feasibility(selected, seam_catalog, coverage)
            if not feasible:
                continue
            ids = tuple(sorted(item["id"] for item in selected))
            cost = sum(item["cost_units"] for item in selected)
            objective = (cost, len(selected), ids)
            solutions.append((objective, tuple(sorted(selected, key=lambda item: item["id"]))))
    if not solutions:
        raise EdgeError("no admissible witness set covers the mandatory seams and negative witnesses")
    solutions.sort(key=lambda item: item[0])
    best_objective, best = solutions[0]
    optimum_cost, optimum_count, _ = best_objective
    alternatives = [
        [item["id"] for item in selected]
        for objective, selected in solutions[1:]
        if objective[0] == optimum_cost and objective[1] == optimum_count
    ]

    mandatory_seams = [item for item in seam_catalog["seams"] if item["mandatory"]]
    mandatory_negative = [
        item for item in seam_catalog["negative_witnesses"] if item["mandatory"]
    ]
    seam_support = []
    for seam in mandatory_seams:
        support = _selection_support(best, seam["id"])
        seam_support.append(
            {
                "seam_id": seam["id"],
                "minimum_independent_piles": seam["minimum_independent_piles"],
                **support,
                "support_satisfied": (
                    len(support["piles"]) >= seam["minimum_independent_piles"]
                ),
            }
        )

    covered_seams = sorted({seam for item in best for seam in item["covers_seams"]})
    covered_negative = sorted(
        {witness for item in best for witness in item["covers_negative_witnesses"]}
    )
    body = {
        "schema": PLAN_SCHEMA,
        "campaign_id": donors["campaign_id"],
        "donor_piles_sha256": hash_json(donors),
        "seam_catalog_sha256": hash_json(seam_catalog),
        "coverage_matrix_sha256": hash_json(coverage),
        "objective": {
            "method": "exact_cost_weighted_set_cover",
            "total_cost_units": optimum_cost,
            "witness_count": optimum_count,
            "tie_break": "cost_then_count_then_lexicographic_ids",
            "subsets_evaluated": evaluated,
        },
        "selected_witnesses": [
            {
                "id": item["id"],
                "title": item["title"],
                "cost_units": item["cost_units"],
                "state": item["state"],
                "evidence_class": item["evidence_class"],
                "donor_piles": item["donor_piles"],
                "independence_groups": item["independence_groups"],
                "covers_seams": item["covers_seams"],
                "covers_negative_witnesses": item["covers_negative_witnesses"],
                "hardware_required": item["hardware_required"],
                "connectivity_profiles": item["connectivity_profiles"],
            }
            for item in best
        ],
        "alternative_optima": alternatives,
        "coverage": {
            "mandatory_seams": sorted(item["id"] for item in mandatory_seams),
            "covered_seams": covered_seams,
            "uncovered_seams": sorted(
                {item["id"] for item in mandatory_seams} - set(covered_seams)
            ),
            "mandatory_negative_witnesses": sorted(
                item["id"] for item in mandatory_negative
            ),
            "covered_negative_witnesses": covered_negative,
            "uncovered_negative_witnesses": sorted(
                {item["id"] for item in mandatory_negative} - set(covered_negative)
            ),
            "required_evidence_classes": constraints["required_evidence_classes"],
            "selected_evidence_classes": sorted(
                {item["evidence_class"] for item in best}
            ),
            "seam_support": seam_support,
        },
        "unselected_witnesses": sorted(
            item["id"] for item in coverage["witnesses"] if item["id"] not in {x["id"] for x in best}
        ),
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"plan_id": f"menaceseamplan1_{hash_json(body)}", **body}


def verify_plan(
    raw_donors: Any,
    raw_seams: Any,
    raw_coverage: Any,
    candidate: Any,
) -> list[str]:
    expected = compile_plan(raw_donors, raw_seams, raw_coverage)
    if not isinstance(candidate, dict):
        return ["minimal witness plan must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in (
        "schema",
        "plan_id",
        "campaign_id",
        "donor_piles_sha256",
        "seam_catalog_sha256",
        "coverage_matrix_sha256",
        "objective",
        "selected_witnesses",
        "coverage",
    ):
        if candidate.get(key) != expected.get(key):
            errors.append(f"minimal witness plan.{key} differs from deterministic compilation")
    return errors or ["minimal witness plan differs from deterministic compilation"]


def _pile_seam_map(
    donor_piles: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, set[str]]:
    result = {item["id"]: set() for item in donor_piles["piles"]}
    for witness in coverage["witnesses"]:
        for pile in witness["donor_piles"]:
            result[pile].update(witness["covers_seams"])
    return result


def compile_report(raw_donors: Any, raw_seams: Any, raw_coverage: Any) -> dict[str, Any]:
    donors, seam_catalog, coverage = validate_bundle(raw_donors, raw_seams, raw_coverage)
    plan = compile_plan(donors, seam_catalog, coverage)
    pile_map = _pile_seam_map(donors, coverage)
    witnesses = coverage["witnesses"]

    intersections = []
    pile_ids = sorted(pile_map)
    for order in (2, 3):
        for group in combinations(pile_ids, order):
            shared = sorted(set.intersection(*(pile_map[pile] for pile in group)))
            if not shared:
                continue
            shared_witnesses = sorted(
                item["id"]
                for item in witnesses
                if set(group).issubset(item["donor_piles"])
            )
            intersections.append(
                {
                    "order": order,
                    "piles": list(group),
                    "shared_seams": shared,
                    "shared_witnesses": shared_witnesses,
                }
            )

    seam_support = []
    for seam in seam_catalog["seams"]:
        support = _selection_support(witnesses, seam["id"])
        observed = len(support["piles"])
        if observed == 0:
            state = "uncovered"
        elif observed < seam["minimum_independent_piles"]:
            state = "under_supported"
        elif observed == 1:
            state = "single_pile"
        else:
            state = "multi_pile"
        seam_support.append(
            {
                "seam_id": seam["id"],
                "title": seam["title"],
                "category": seam["category"],
                "mandatory": seam["mandatory"],
                "minimum_independent_piles": seam["minimum_independent_piles"],
                "support_state": state,
                **support,
            }
        )

    donor_rows = []
    for pile in donors["piles"]:
        pile_witnesses = [item for item in witnesses if pile["id"] in item["donor_piles"]]
        donor_rows.append(
            {
                "pile_id": pile["id"],
                "title": pile["title"],
                "donor_count": len(pile["donors"]),
                "witness_count": len(pile_witnesses),
                "seam_count": len(pile_map[pile["id"]]),
                "seams": sorted(pile_map[pile["id"]]),
                "evidence_classes": sorted(
                    {donor["evidence_class"] for donor in pile["donors"]}
                ),
            }
        )

    body = {
        "schema": REPORT_SCHEMA,
        "campaign_id": donors["campaign_id"],
        "donor_piles_sha256": hash_json(donors),
        "seam_catalog_sha256": hash_json(seam_catalog),
        "coverage_matrix_sha256": hash_json(coverage),
        "minimal_witness_plan_id": plan["plan_id"],
        "totals": {
            "donor_piles": len(donors["piles"]),
            "donors": sum(len(item["donors"]) for item in donors["piles"]),
            "seams": len(seam_catalog["seams"]),
            "mandatory_seams": sum(item["mandatory"] for item in seam_catalog["seams"]),
            "negative_witnesses": len(seam_catalog["negative_witnesses"]),
            "coverage_witnesses": len(coverage["witnesses"]),
            "selected_witnesses": len(plan["selected_witnesses"]),
            "pair_and_triple_intersections": len(intersections),
        },
        "donor_piles": donor_rows,
        "seam_support": seam_support,
        "pile_intersections": intersections,
        "minimal_witness_plan": {
            "plan_id": plan["plan_id"],
            "selected_witnesses": [item["id"] for item in plan["selected_witnesses"]],
            "total_cost_units": plan["objective"]["total_cost_units"],
            "witness_count": plan["objective"]["witness_count"],
            "alternative_optima": plan["alternative_optima"],
        },
        "uncovered_mandatory_seams": sorted(
            item["seam_id"]
            for item in seam_support
            if item["mandatory"] and item["support_state"] == "uncovered"
        ),
        "under_supported_mandatory_seams": sorted(
            item["seam_id"]
            for item in seam_support
            if item["mandatory"] and item["support_state"] == "under_supported"
        ),
        "single_pile_seams": sorted(
            item["seam_id"] for item in seam_support if item["support_state"] == "single_pile"
        ),
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"report_id": f"menaceseamreport1_{hash_json(body)}", **body}


def verify_report(
    raw_donors: Any,
    raw_seams: Any,
    raw_coverage: Any,
    candidate: Any,
) -> list[str]:
    expected = compile_report(raw_donors, raw_seams, raw_coverage)
    if not isinstance(candidate, dict):
        return ["seam census report must be an object"]
    if canonical_bytes(expected) == canonical_bytes(candidate):
        return []
    errors = []
    for key in (
        "schema",
        "report_id",
        "campaign_id",
        "minimal_witness_plan_id",
        "totals",
        "donor_piles",
        "seam_support",
        "pile_intersections",
        "minimal_witness_plan",
    ):
        if candidate.get(key) != expected.get(key):
            errors.append(f"seam census report.{key} differs from deterministic compilation")
    return errors or ["seam census report differs from deterministic compilation"]


def render_markdown(report: dict[str, Any]) -> str:
    if report.get("schema") != REPORT_SCHEMA:
        raise EdgeError("Markdown rendering requires a MENACE seam census report")
    lines = [
        "# MENACE Edge Seam Census",
        "",
        f"Campaign: `{report['campaign_id']}`  ",
        f"Report: `{report['report_id']}`  ",
        f"Minimal witness plan: `{report['minimal_witness_plan_id']}`",
        "",
        "This report is a requirements-mining artifact. It inventories donor piles, repeated seams,",
        "negative witnesses, and the smallest declared witness set that covers the mandatory seam",
        "contract. It is not field acceptance and grants no production or action authority.",
        "",
        "## Denominator",
        "",
        "| Object | Count |",
        "|---|---:|",
        f"| Donor piles | {report['totals']['donor_piles']} |",
        f"| Sanitized donor records | {report['totals']['donors']} |",
        f"| Seams | {report['totals']['seams']} |",
        f"| Mandatory seams | {report['totals']['mandatory_seams']} |",
        f"| Negative witnesses | {report['totals']['negative_witnesses']} |",
        f"| Candidate integrated witnesses | {report['totals']['coverage_witnesses']} |",
        f"| Selected minimal witnesses | {report['totals']['selected_witnesses']} |",
        "",
        "## Minimal witness set",
        "",
        f"Declared cost: `{report['minimal_witness_plan']['total_cost_units']}` units.  ",
        f"Alternative optima: `{len(report['minimal_witness_plan']['alternative_optima'])}`.",
        "",
    ]
    for witness_id in report["minimal_witness_plan"]["selected_witnesses"]:
        lines.append(f"- `{witness_id}`")
    lines.extend(
        [
            "",
            "## Seam support",
            "",
            "| Seam | Category | Piles | Witnesses | Minimum | State |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for seam in report["seam_support"]:
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                seam["seam_id"],
                seam["category"],
                len(seam["piles"]),
                len(seam["witnesses"]),
                seam["minimum_independent_piles"],
                seam["support_state"],
            )
        )
    lines.extend(
        [
            "",
            "## Donor piles",
            "",
            "| Pile | Donors | Witnesses | Seams | Evidence classes |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for pile in report["donor_piles"]:
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                pile["pile_id"],
                pile["donor_count"],
                pile["witness_count"],
                pile["seam_count"],
                ", ".join(pile["evidence_classes"]),
            )
        )
    lines.extend(
        [
            "",
            "## Highest-order pile intersections",
            "",
            "| Piles | Shared seams | Shared integrated witnesses |",
            "|---|---:|---:|",
        ]
    )
    for intersection in sorted(
        report["pile_intersections"],
        key=lambda item: (-item["order"], -len(item["shared_seams"]), item["piles"]),
    )[:20]:
        lines.append(
            "| {} | {} | {} |".format(
                " + ".join(f"`{item}`" for item in intersection["piles"]),
                len(intersection["shared_seams"]),
                len(intersection["shared_witnesses"]),
            )
        )
    lines.extend(
        [
            "",
            "## Visible gaps",
            "",
            f"Uncovered mandatory seams: `{len(report['uncovered_mandatory_seams'])}`.  ",
            f"Under-supported mandatory seams: `{len(report['under_supported_mandatory_seams'])}`.  ",
            f"Seams supported by only one donor pile: `{len(report['single_pile_seams'])}`.",
            "",
            "The control question is whether each selected witness can be replaced by an independent",
            "implementation while preserving the same seam invariants, negative controls, and receipts.",
            "",
        ]
    )
    return "\n".join(lines)
