"""Strict public donor, seam, and coverage contracts for MENACE edge."""
from __future__ import annotations

from typing import Any

from .menace_edge_common import (
    EdgeError,
    exact_keys,
    need_array,
    need_boolean,
    need_integer,
    need_object,
    need_text,
    safe_id,
    unique_by_id,
)

DONOR_SCHEMA = "tier-bench/menace-edge-donor-piles@1"
SEAM_SCHEMA = "tier-bench/menace-edge-seam-catalog@1"
COVERAGE_SCHEMA = "tier-bench/menace-edge-coverage-matrix@1"
PLAN_SCHEMA = "tier-bench/menace-edge-minimal-witness-plan@1"
REPORT_SCHEMA = "tier-bench/menace-edge-seam-census-report@1"

SOURCE_VISIBILITY = {"public", "private", "mixed"}
PUBLIC_USE = {"exact", "sanitized_shape_only", "none"}
DONOR_KINDS = {
    "implemented_system",
    "private_reported_trace",
    "public_record",
    "operator_observation",
    "synthetic_fixture",
}
EVIDENCE_CLASSES = {
    "implemented_fixture",
    "private_reported_trace",
    "public_record",
    "operator_observation",
    "synthetic_control",
}
SEAM_CATEGORIES = {"survival", "judgment", "portability"}
WITNESS_STATES = {"implemented", "shape_available", "synthetic_control", "proposed"}


def _ids(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [safe_id(item, label) for item in rows]
    if len(result) != len(set(result)):
        raise EdgeError(f"{label} contains duplicates")
    return sorted(result)


def _texts(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [need_text(item, label, limit=4000) for item in rows]
    if len(result) != len(set(result)):
        raise EdgeError(f"{label} contains duplicates")
    return result


def validate_donor_piles(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "donor piles")
    exact_keys(row, {"schema", "campaign_id", "public_boundary", "piles"}, set(), "donor piles")
    if row["schema"] != DONOR_SCHEMA:
        raise EdgeError(f"donor piles.schema must be {DONOR_SCHEMA}")
    public_boundary = need_object(row["public_boundary"], "donor piles.public_boundary")
    exact_keys(
        public_boundary,
        {
            "private_source_bytes_allowed",
            "personal_names_required",
            "operational_locations_allowed",
            "sanitized_private_shapes_allowed",
        },
        set(),
        "donor piles.public_boundary",
    )
    normalized_boundary = {
        key: need_boolean(public_boundary[key], f"donor piles.public_boundary.{key}")
        for key in public_boundary
    }
    if normalized_boundary["private_source_bytes_allowed"]:
        raise EdgeError("the public donor ledger cannot contain private source bytes")
    if normalized_boundary["personal_names_required"]:
        raise EdgeError("the public donor ledger must not require personal names")
    if normalized_boundary["operational_locations_allowed"]:
        raise EdgeError("the public donor ledger cannot contain operational locations")
    if not normalized_boundary["sanitized_private_shapes_allowed"]:
        raise EdgeError("the public donor ledger must permit sanitized private workload shapes")

    piles: list[dict[str, Any]] = []
    donor_ids: set[str] = set()
    for pile_index, raw_pile in enumerate(need_array(row["piles"], "donor piles.piles", nonempty=True)):
        pile = need_object(raw_pile, f"donor piles.piles[{pile_index}]")
        exact_keys(
            pile,
            {
                "id",
                "title",
                "domain",
                "core_questions",
                "irreducible_constraints",
                "donors",
            },
            set(),
            f"donor piles.piles[{pile_index}]",
        )
        pile_id = safe_id(pile["id"], f"donor piles.piles[{pile_index}].id")
        donors: list[dict[str, Any]] = []
        for donor_index, raw_donor in enumerate(
            need_array(pile["donors"], f"donor pile {pile_id}.donors", nonempty=True)
        ):
            donor = need_object(raw_donor, f"donor pile {pile_id}.donors[{donor_index}]")
            exact_keys(
                donor,
                {
                    "id",
                    "title",
                    "kind",
                    "evidence_class",
                    "custody",
                    "source_visibility",
                    "allowed_public_use",
                    "contains_private_source_bytes",
                },
                set(),
                f"donor pile {pile_id}.donors[{donor_index}]",
            )
            donor_id = safe_id(donor["id"], f"donor pile {pile_id}.donors[{donor_index}].id")
            if donor_id in donor_ids:
                raise EdgeError(f"duplicate donor id: {donor_id}")
            donor_ids.add(donor_id)
            kind = need_text(donor["kind"], f"donor {donor_id}.kind", limit=80)
            evidence_class = need_text(
                donor["evidence_class"], f"donor {donor_id}.evidence_class", limit=80
            )
            visibility = need_text(
                donor["source_visibility"], f"donor {donor_id}.source_visibility", limit=40
            )
            public_use = need_text(
                donor["allowed_public_use"], f"donor {donor_id}.allowed_public_use", limit=40
            )
            if kind not in DONOR_KINDS:
                raise EdgeError(f"donor {donor_id}.kind is invalid")
            if evidence_class not in EVIDENCE_CLASSES:
                raise EdgeError(f"donor {donor_id}.evidence_class is invalid")
            if visibility not in SOURCE_VISIBILITY:
                raise EdgeError(f"donor {donor_id}.source_visibility is invalid")
            if public_use not in PUBLIC_USE:
                raise EdgeError(f"donor {donor_id}.allowed_public_use is invalid")
            has_private_bytes = need_boolean(
                donor["contains_private_source_bytes"],
                f"donor {donor_id}.contains_private_source_bytes",
            )
            if has_private_bytes:
                raise EdgeError(f"public donor {donor_id} cannot embed private source bytes")
            if visibility in {"private", "mixed"} and public_use == "exact":
                raise EdgeError(
                    f"private or mixed donor {donor_id} may only expose a sanitized shape or nothing"
                )
            donors.append(
                {
                    "id": donor_id,
                    "title": need_text(donor["title"], f"donor {donor_id}.title", limit=300),
                    "kind": kind,
                    "evidence_class": evidence_class,
                    "custody": safe_id(donor["custody"], f"donor {donor_id}.custody"),
                    "source_visibility": visibility,
                    "allowed_public_use": public_use,
                    "contains_private_source_bytes": has_private_bytes,
                }
            )
        piles.append(
            {
                "id": pile_id,
                "title": need_text(pile["title"], f"donor pile {pile_id}.title", limit=300),
                "domain": safe_id(pile["domain"], f"donor pile {pile_id}.domain"),
                "core_questions": _texts(
                    pile["core_questions"], f"donor pile {pile_id}.core_questions", nonempty=True
                ),
                "irreducible_constraints": _texts(
                    pile["irreducible_constraints"],
                    f"donor pile {pile_id}.irreducible_constraints",
                    nonempty=True,
                ),
                "donors": sorted(donors, key=lambda item: item["id"]),
            }
        )
    unique_by_id(piles, "donor pile")
    return {
        "schema": DONOR_SCHEMA,
        "campaign_id": safe_id(row["campaign_id"], "donor piles.campaign_id"),
        "public_boundary": normalized_boundary,
        "piles": sorted(piles, key=lambda item: item["id"]),
    }


def validate_seam_catalog(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "seam catalog")
    exact_keys(row, {"schema", "campaign_id", "seams", "negative_witnesses"}, set(), "seam catalog")
    if row["schema"] != SEAM_SCHEMA:
        raise EdgeError(f"seam catalog.schema must be {SEAM_SCHEMA}")

    raw_negative = need_array(
        row["negative_witnesses"], "seam catalog.negative_witnesses", nonempty=True
    )
    negative_ids = {
        safe_id(item.get("id") if isinstance(item, dict) else None, "negative witness id")
        for item in raw_negative
    }
    if len(negative_ids) != len(raw_negative):
        raise EdgeError("negative witness ids must be unique")

    raw_seams = need_array(row["seams"], "seam catalog.seams", nonempty=True)
    seam_ids = {
        safe_id(item.get("id") if isinstance(item, dict) else None, "seam id")
        for item in raw_seams
    }
    if len(seam_ids) != len(raw_seams):
        raise EdgeError("seam ids must be unique")

    seams: list[dict[str, Any]] = []
    for index, raw_seam in enumerate(raw_seams):
        seam = need_object(raw_seam, f"seam catalog.seams[{index}]")
        exact_keys(
            seam,
            {
                "id",
                "title",
                "category",
                "producer",
                "consumer",
                "invariant",
                "owner",
                "degradation_law",
                "must_survive",
                "required_receipts",
                "negative_witnesses",
                "minimum_independent_piles",
                "mandatory",
            },
            set(),
            f"seam catalog.seams[{index}]",
        )
        seam_id = safe_id(seam["id"], f"seam catalog.seams[{index}].id")
        category = need_text(seam["category"], f"seam {seam_id}.category", limit=40)
        if category not in SEAM_CATEGORIES:
            raise EdgeError(f"seam {seam_id}.category is invalid")
        referenced_negative = _ids(
            seam["negative_witnesses"], f"seam {seam_id}.negative_witnesses", nonempty=True
        )
        unknown = sorted(set(referenced_negative) - negative_ids)
        if unknown:
            raise EdgeError(f"seam {seam_id} references unknown negative witnesses: {unknown}")
        seams.append(
            {
                "id": seam_id,
                "title": need_text(seam["title"], f"seam {seam_id}.title", limit=300),
                "category": category,
                "producer": need_text(seam["producer"], f"seam {seam_id}.producer", limit=1000),
                "consumer": need_text(seam["consumer"], f"seam {seam_id}.consumer", limit=1000),
                "invariant": need_text(seam["invariant"], f"seam {seam_id}.invariant", limit=4000),
                "owner": safe_id(seam["owner"], f"seam {seam_id}.owner"),
                "degradation_law": need_text(
                    seam["degradation_law"], f"seam {seam_id}.degradation_law", limit=4000
                ),
                "must_survive": _ids(
                    seam["must_survive"], f"seam {seam_id}.must_survive", nonempty=True
                ),
                "required_receipts": _ids(
                    seam["required_receipts"], f"seam {seam_id}.required_receipts", nonempty=True
                ),
                "negative_witnesses": referenced_negative,
                "minimum_independent_piles": need_integer(
                    seam["minimum_independent_piles"],
                    f"seam {seam_id}.minimum_independent_piles",
                    1,
                    20,
                ),
                "mandatory": need_boolean(seam["mandatory"], f"seam {seam_id}.mandatory"),
            }
        )

    negative_witnesses: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_negative):
        item = need_object(raw_item, f"seam catalog.negative_witnesses[{index}]")
        exact_keys(
            item,
            {"id", "title", "mechanism", "refusal_condition", "seams", "mandatory"},
            set(),
            f"seam catalog.negative_witnesses[{index}]",
        )
        identifier = safe_id(item["id"], f"negative witness[{index}].id")
        referenced_seams = _ids(item["seams"], f"negative witness {identifier}.seams", nonempty=True)
        unknown = sorted(set(referenced_seams) - seam_ids)
        if unknown:
            raise EdgeError(f"negative witness {identifier} references unknown seams: {unknown}")
        negative_witnesses.append(
            {
                "id": identifier,
                "title": need_text(item["title"], f"negative witness {identifier}.title", limit=300),
                "mechanism": need_text(
                    item["mechanism"], f"negative witness {identifier}.mechanism", limit=4000
                ),
                "refusal_condition": need_text(
                    item["refusal_condition"],
                    f"negative witness {identifier}.refusal_condition",
                    limit=4000,
                ),
                "seams": referenced_seams,
                "mandatory": need_boolean(
                    item["mandatory"], f"negative witness {identifier}.mandatory"
                ),
            }
        )

    seam_map = {item["id"]: item for item in seams}
    for negative in negative_witnesses:
        for seam_id in negative["seams"]:
            if negative["id"] not in seam_map[seam_id]["negative_witnesses"]:
                raise EdgeError(
                    f"negative witness {negative['id']} and seam {seam_id} must reference each other"
                )
    return {
        "schema": SEAM_SCHEMA,
        "campaign_id": safe_id(row["campaign_id"], "seam catalog.campaign_id"),
        "seams": sorted(seams, key=lambda item: item["id"]),
        "negative_witnesses": sorted(negative_witnesses, key=lambda item: item["id"]),
    }


def validate_coverage_matrix(
    raw: Any,
    donor_piles: dict[str, Any],
    seam_catalog: dict[str, Any],
) -> dict[str, Any]:
    row = need_object(raw, "coverage matrix")
    exact_keys(
        row,
        {"schema", "campaign_id", "selection_constraints", "witnesses"},
        set(),
        "coverage matrix",
    )
    if row["schema"] != COVERAGE_SCHEMA:
        raise EdgeError(f"coverage matrix.schema must be {COVERAGE_SCHEMA}")
    campaign_id = safe_id(row["campaign_id"], "coverage matrix.campaign_id")
    if campaign_id != donor_piles["campaign_id"] or campaign_id != seam_catalog["campaign_id"]:
        raise EdgeError("donor, seam, and coverage campaign ids must match")

    constraints = need_object(row["selection_constraints"], "coverage matrix.selection_constraints")
    exact_keys(
        constraints,
        {
            "required_evidence_classes",
            "admissible_states",
            "maximum_witnesses",
            "require_all_mandatory_seams",
            "require_all_mandatory_negative_witnesses",
        },
        set(),
        "coverage matrix.selection_constraints",
    )
    required_evidence = _ids(
        constraints["required_evidence_classes"],
        "coverage matrix.selection_constraints.required_evidence_classes",
        nonempty=True,
    )
    unknown_classes = sorted(set(required_evidence) - EVIDENCE_CLASSES)
    if unknown_classes:
        raise EdgeError(f"unknown required evidence classes: {unknown_classes}")
    admissible_states = _ids(
        constraints["admissible_states"],
        "coverage matrix.selection_constraints.admissible_states",
        nonempty=True,
    )
    unknown_states = sorted(set(admissible_states) - WITNESS_STATES)
    if unknown_states:
        raise EdgeError(f"unknown admissible witness states: {unknown_states}")

    pile_ids = {item["id"] for item in donor_piles["piles"]}
    seam_ids = {item["id"] for item in seam_catalog["seams"]}
    negative_ids = {item["id"] for item in seam_catalog["negative_witnesses"]}
    raw_witnesses = need_array(row["witnesses"], "coverage matrix.witnesses", nonempty=True)
    witness_ids = {
        safe_id(item.get("id") if isinstance(item, dict) else None, "coverage witness id")
        for item in raw_witnesses
    }
    if len(witness_ids) != len(raw_witnesses):
        raise EdgeError("coverage witness ids must be unique")

    witnesses: list[dict[str, Any]] = []
    for index, raw_witness in enumerate(raw_witnesses):
        witness = need_object(raw_witness, f"coverage matrix.witnesses[{index}]")
        exact_keys(
            witness,
            {
                "id",
                "title",
                "state",
                "evidence_class",
                "cost_units",
                "donor_piles",
                "independence_groups",
                "covers_seams",
                "covers_negative_witnesses",
                "prerequisites",
                "hardware_required",
                "connectivity_profiles",
            },
            set(),
            f"coverage matrix.witnesses[{index}]",
        )
        identifier = safe_id(witness["id"], f"coverage witness[{index}].id")
        state = need_text(witness["state"], f"coverage witness {identifier}.state", limit=40)
        evidence_class = need_text(
            witness["evidence_class"], f"coverage witness {identifier}.evidence_class", limit=80
        )
        if state not in WITNESS_STATES:
            raise EdgeError(f"coverage witness {identifier}.state is invalid")
        if evidence_class not in EVIDENCE_CLASSES:
            raise EdgeError(f"coverage witness {identifier}.evidence_class is invalid")
        piles = _ids(
            witness["donor_piles"], f"coverage witness {identifier}.donor_piles", nonempty=True
        )
        covered_seams = _ids(
            witness["covers_seams"], f"coverage witness {identifier}.covers_seams", nonempty=True
        )
        covered_negative = _ids(
            witness["covers_negative_witnesses"],
            f"coverage witness {identifier}.covers_negative_witnesses",
        )
        prerequisites = _ids(
            witness["prerequisites"], f"coverage witness {identifier}.prerequisites"
        )
        unknown_piles = sorted(set(piles) - pile_ids)
        unknown_seams = sorted(set(covered_seams) - seam_ids)
        unknown_negative = sorted(set(covered_negative) - negative_ids)
        unknown_prerequisites = sorted(set(prerequisites) - witness_ids)
        if unknown_piles:
            raise EdgeError(f"coverage witness {identifier} references unknown piles: {unknown_piles}")
        if unknown_seams:
            raise EdgeError(f"coverage witness {identifier} references unknown seams: {unknown_seams}")
        if unknown_negative:
            raise EdgeError(
                f"coverage witness {identifier} references unknown negative witnesses: {unknown_negative}"
            )
        if unknown_prerequisites:
            raise EdgeError(
                f"coverage witness {identifier} references unknown prerequisites: {unknown_prerequisites}"
            )
        if identifier in prerequisites:
            raise EdgeError(f"coverage witness {identifier} cannot depend on itself")
        witnesses.append(
            {
                "id": identifier,
                "title": need_text(witness["title"], f"coverage witness {identifier}.title", limit=300),
                "state": state,
                "evidence_class": evidence_class,
                "cost_units": need_integer(
                    witness["cost_units"], f"coverage witness {identifier}.cost_units", 1, 100000
                ),
                "donor_piles": piles,
                "independence_groups": _ids(
                    witness["independence_groups"],
                    f"coverage witness {identifier}.independence_groups",
                    nonempty=True,
                ),
                "covers_seams": covered_seams,
                "covers_negative_witnesses": covered_negative,
                "prerequisites": prerequisites,
                "hardware_required": need_boolean(
                    witness["hardware_required"],
                    f"coverage witness {identifier}.hardware_required",
                ),
                "connectivity_profiles": _ids(
                    witness["connectivity_profiles"],
                    f"coverage witness {identifier}.connectivity_profiles",
                    nonempty=True,
                ),
            }
        )

    available_classes = {item["evidence_class"] for item in witnesses}
    missing_classes = sorted(set(required_evidence) - available_classes)
    if missing_classes:
        raise EdgeError(f"coverage matrix cannot satisfy required evidence classes: {missing_classes}")
    return {
        "schema": COVERAGE_SCHEMA,
        "campaign_id": campaign_id,
        "selection_constraints": {
            "required_evidence_classes": required_evidence,
            "admissible_states": admissible_states,
            "maximum_witnesses": need_integer(
                constraints["maximum_witnesses"],
                "coverage matrix.selection_constraints.maximum_witnesses",
                1,
                30,
            ),
            "require_all_mandatory_seams": need_boolean(
                constraints["require_all_mandatory_seams"],
                "coverage matrix.selection_constraints.require_all_mandatory_seams",
            ),
            "require_all_mandatory_negative_witnesses": need_boolean(
                constraints["require_all_mandatory_negative_witnesses"],
                "coverage matrix.selection_constraints.require_all_mandatory_negative_witnesses",
            ),
        },
        "witnesses": sorted(witnesses, key=lambda item: item["id"]),
    }
