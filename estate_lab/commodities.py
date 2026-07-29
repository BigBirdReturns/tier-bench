"""Machine-readable OSS, community, and commodity acquisition ledger.

Estate Lab does not treat an upstream project as architecture merely because it
is impressive or popular.  The catalog separates four dispositions:

* consume: use the upstream unchanged behind its public contract;
* adapt: keep it outside AXM authority and write a bounded adapter;
* reference: harvest design and test lessons without taking a dependency;
* reject: retain the reason the candidate is unsuitable so it is not repeatedly
  rediscovered as an apparently new option.

The catalog is deliberately static.  Network discovery belongs in a separate
observation transaction; this module validates and projects the reviewed
supplier decision that is already in custody.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .canonical import load_json, stable_id, write_json
from .errors import CommodityCatalogError

CATALOG_FORMAT = "axm-commodity-catalog/1"
DECISIONS = frozenset({"consume", "adapt", "reference", "reject"})
PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})
MATURITY = frozenset(
    {
        "standard",
        "commodity",
        "mature-community",
        "active-emerging",
        "reference-only",
        "retired",
    }
)
LICENSE_POSTURES = frozenset(
    {
        "permissive",
        "weak-copyleft",
        "strong-copyleft",
        "standard",
        "mixed",
        "proprietary",
        "unknown",
    }
)
INTEGRATION_MODES = frozenset(
    {
        "library",
        "protocol",
        "external-process",
        "firmware-supplier",
        "test-harness",
        "visualization-client",
        "design-reference",
        "retired-avoid",
    }
)


@dataclass(frozen=True)
class CommodityCandidate:
    candidate_id: str
    name: str
    category: str
    supplier_role: str
    decision: str
    priority: str
    maturity: str
    license: str
    license_posture: str
    integration_mode: str
    upstream: dict[str, Any]
    community_signal: str
    capabilities: tuple[str, ...]
    estate_targets: tuple[str, ...]
    decision_basis: str
    reuse_surface: str
    required_adapter: str | None
    substitution_test: str | None
    authority_exclusions: tuple[str, ...]
    risks: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class CommodityCatalog:
    catalog_id: str
    reviewed_as_of: str
    scope: str
    candidates: tuple[CommodityCandidate, ...]
    raw: dict[str, Any]


def _require_string(raw: dict[str, Any], key: str, *, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommodityCatalogError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(raw: dict[str, Any], key: str, *, where: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CommodityCatalogError(f"{where}.{key} must be null or a non-empty string")
    return value.strip()


def _require_string_list(raw: dict[str, Any], key: str, *, where: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise CommodityCatalogError(f"{where}.{key} must be a non-empty array")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise CommodityCatalogError(f"{where}.{key}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        raise CommodityCatalogError(f"{where}.{key} contains duplicates")
    return tuple(normalized)


def _require_evidence(raw: dict[str, Any], *, where: str) -> tuple[dict[str, str], ...]:
    value = raw.get("evidence")
    if not isinstance(value, list) or not value:
        raise CommodityCatalogError(f"{where}.evidence must be a non-empty array")
    evidence: list[dict[str, str]] = []
    for index, row in enumerate(value):
        row_where = f"{where}.evidence[{index}]"
        if not isinstance(row, dict):
            raise CommodityCatalogError(f"{row_where} must be an object")
        claim = _require_string(row, "claim", where=row_where)
        locator = _require_string(row, "locator", where=row_where)
        kind = _require_string(row, "kind", where=row_where)
        if not locator.startswith("https://"):
            raise CommodityCatalogError(f"{row_where}.locator must be an https URL")
        evidence.append({"kind": kind, "locator": locator, "claim": claim})
    return tuple(evidence)


def catalog_identity_projection(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": raw.get("format"),
        "reviewed_as_of": raw.get("reviewed_as_of"),
        "scope": raw.get("scope"),
        "candidates": raw.get("candidates"),
    }


def derived_catalog_id(raw: dict[str, Any]) -> str:
    return stable_id("commoditycat1", catalog_identity_projection(raw), length=32)


def load_commodity_catalog(path: Path) -> CommodityCatalog:
    try:
        raw = load_json(path)
    except (OSError, ValueError) as exc:
        raise CommodityCatalogError(f"cannot load commodity catalog {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CommodityCatalogError("commodity catalog root must be an object")
    if raw.get("format") != CATALOG_FORMAT:
        raise CommodityCatalogError(f"format must be {CATALOG_FORMAT!r}")

    reviewed_as_of = _require_string(raw, "reviewed_as_of", where="catalog")
    scope = _require_string(raw, "scope", where="catalog")
    declared_id = _require_string(raw, "catalog_id", where="catalog")
    expected_id = derived_catalog_id(raw)
    if declared_id != expected_id:
        raise CommodityCatalogError(
            f"catalog_id mismatch: declared {declared_id!r}, expected {expected_id!r}"
        )

    rows = raw.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise CommodityCatalogError("catalog.candidates must be a non-empty array")

    candidates: list[CommodityCandidate] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        where = f"catalog.candidates[{index}]"
        if not isinstance(row, dict):
            raise CommodityCatalogError(f"{where} must be an object")
        candidate_id = _require_string(row, "id", where=where)
        if candidate_id in seen_ids:
            raise CommodityCatalogError(f"duplicate candidate id: {candidate_id}")
        seen_ids.add(candidate_id)

        decision = _require_string(row, "decision", where=where)
        priority = _require_string(row, "priority", where=where)
        maturity = _require_string(row, "maturity", where=where)
        license_posture = _require_string(row, "license_posture", where=where)
        integration_mode = _require_string(row, "integration_mode", where=where)
        if decision not in DECISIONS:
            raise CommodityCatalogError(f"{where}.decision must be one of {sorted(DECISIONS)}")
        if priority not in PRIORITIES:
            raise CommodityCatalogError(f"{where}.priority must be one of {sorted(PRIORITIES)}")
        if maturity not in MATURITY:
            raise CommodityCatalogError(f"{where}.maturity must be one of {sorted(MATURITY)}")
        if license_posture not in LICENSE_POSTURES:
            raise CommodityCatalogError(
                f"{where}.license_posture must be one of {sorted(LICENSE_POSTURES)}"
            )
        if integration_mode not in INTEGRATION_MODES:
            raise CommodityCatalogError(
                f"{where}.integration_mode must be one of {sorted(INTEGRATION_MODES)}"
            )

        upstream = row.get("upstream")
        if not isinstance(upstream, dict):
            raise CommodityCatalogError(f"{where}.upstream must be an object")
        project_url = _require_string(upstream, "project_url", where=f"{where}.upstream")
        if not project_url.startswith("https://"):
            raise CommodityCatalogError(f"{where}.upstream.project_url must be an https URL")
        repository = upstream.get("repository")
        if repository is not None and (not isinstance(repository, str) or "/" not in repository):
            raise CommodityCatalogError(
                f"{where}.upstream.repository must be null or owner/name"
            )

        capabilities = _require_string_list(row, "capabilities", where=where)
        estate_targets = _require_string_list(row, "estate_targets", where=where)
        authority_exclusions = _require_string_list(row, "authority_exclusions", where=where)
        risks = tuple(row.get("risks", []))
        if not isinstance(row.get("risks", []), list) or any(
            not isinstance(item, str) or not item.strip() for item in risks
        ):
            raise CommodityCatalogError(f"{where}.risks must be an array of non-empty strings")
        evidence = _require_evidence(row, where=where)
        required_adapter = _optional_string(row, "required_adapter", where=where)
        substitution_test = _optional_string(row, "substitution_test", where=where)

        if decision == "consume":
            if license_posture not in {"permissive", "standard"}:
                raise CommodityCatalogError(
                    f"{where}: consume requires permissive code or an open standard"
                )
            if not substitution_test:
                raise CommodityCatalogError(f"{where}: consume requires a substitution_test")
            if integration_mode in {"design-reference", "retired-avoid"}:
                raise CommodityCatalogError(f"{where}: consume has an invalid integration_mode")
        elif decision == "adapt":
            if not required_adapter:
                raise CommodityCatalogError(f"{where}: adapt requires required_adapter")
            if not substitution_test:
                raise CommodityCatalogError(f"{where}: adapt requires a substitution_test")
        elif decision == "reference":
            if integration_mode != "design-reference":
                raise CommodityCatalogError(
                    f"{where}: reference candidates must use design-reference integration"
                )
        elif decision == "reject":
            if integration_mode != "retired-avoid":
                raise CommodityCatalogError(
                    f"{where}: reject candidates must use retired-avoid integration"
                )
            if not risks:
                raise CommodityCatalogError(f"{where}: reject requires at least one risk")

        candidates.append(
            CommodityCandidate(
                candidate_id=candidate_id,
                name=_require_string(row, "name", where=where),
                category=_require_string(row, "category", where=where),
                supplier_role=_require_string(row, "supplier_role", where=where),
                decision=decision,
                priority=priority,
                maturity=maturity,
                license=_require_string(row, "license", where=where),
                license_posture=license_posture,
                integration_mode=integration_mode,
                upstream=dict(upstream),
                community_signal=_require_string(row, "community_signal", where=where),
                capabilities=capabilities,
                estate_targets=estate_targets,
                decision_basis=_require_string(row, "decision_basis", where=where),
                reuse_surface=_require_string(row, "reuse_surface", where=where),
                required_adapter=required_adapter,
                substitution_test=substitution_test,
                authority_exclusions=authority_exclusions,
                risks=tuple(item.strip() for item in risks),
                evidence=evidence,
            )
        )

    return CommodityCatalog(
        catalog_id=declared_id,
        reviewed_as_of=reviewed_as_of,
        scope=scope,
        candidates=tuple(candidates),
        raw=raw,
    )


def select_candidates(
    catalog: CommodityCatalog,
    *,
    decisions: Iterable[str] = (),
    categories: Iterable[str] = (),
    priorities: Iterable[str] = (),
    targets: Iterable[str] = (),
) -> tuple[CommodityCandidate, ...]:
    decision_set = set(decisions)
    category_set = set(categories)
    priority_set = set(priorities)
    target_set = set(targets)
    unknown_decisions = decision_set - DECISIONS
    unknown_priorities = priority_set - PRIORITIES
    if unknown_decisions:
        raise CommodityCatalogError(f"unknown decisions: {sorted(unknown_decisions)}")
    if unknown_priorities:
        raise CommodityCatalogError(f"unknown priorities: {sorted(unknown_priorities)}")

    selected = [
        item
        for item in catalog.candidates
        if (not decision_set or item.decision in decision_set)
        and (not category_set or item.category in category_set)
        and (not priority_set or item.priority in priority_set)
        and (not target_set or target_set.intersection(item.estate_targets))
    ]
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    decision_order = {"consume": 0, "adapt": 1, "reference": 2, "reject": 3}
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                priority_order[item.priority],
                decision_order[item.decision],
                item.category,
                item.name.casefold(),
            ),
        )
    )


def build_acquisition_plan(
    catalog: CommodityCatalog,
    candidates: Iterable[CommodityCandidate] | None = None,
) -> dict[str, Any]:
    rows = tuple(candidates) if candidates is not None else catalog.candidates
    grouped: dict[str, list[dict[str, Any]]] = {decision: [] for decision in sorted(DECISIONS)}
    categories: dict[str, int] = {}
    priorities: dict[str, int] = {priority: 0 for priority in sorted(PRIORITIES)}
    for item in rows:
        categories[item.category] = categories.get(item.category, 0) + 1
        priorities[item.priority] += 1
        grouped[item.decision].append(
            {
                "id": item.candidate_id,
                "name": item.name,
                "category": item.category,
                "priority": item.priority,
                "supplier_role": item.supplier_role,
                "integration_mode": item.integration_mode,
                "license": item.license,
                "license_posture": item.license_posture,
                "estate_targets": list(item.estate_targets),
                "required_adapter": item.required_adapter,
                "substitution_test": item.substitution_test,
                "decision_basis": item.decision_basis,
                "authority_exclusions": list(item.authority_exclusions),
                "risks": list(item.risks),
                "upstream": item.upstream,
            }
        )
    for decision in grouped:
        grouped[decision].sort(key=lambda row: (row["priority"], row["category"], row["name"]))
    return {
        "format": "axm-commodity-acquisition-plan/1",
        "catalog_id": catalog.catalog_id,
        "reviewed_as_of": catalog.reviewed_as_of,
        "candidate_count": len(rows),
        "counts_by_decision": {key: len(value) for key, value in grouped.items()},
        "counts_by_priority": priorities,
        "counts_by_category": dict(sorted(categories.items())),
        "decisions": grouped,
        "control_question": (
            "Can each acquired supplier be upgraded, substituted, disabled, or removed while "
            "AXM retains semantic law, authority, canonical state, replay receipts, and a "
            "supplier-independent fallback?"
        ),
    }


def render_acquisition_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# AXM commodity acquisition plan",
        "",
        f"Catalog: `{plan['catalog_id']}`",
        f"Reviewed as of: `{plan['reviewed_as_of']}`",
        f"Candidates in this projection: **{plan['candidate_count']}**",
        "",
        "| Decision | Count | Meaning |",
        "|---|---:|---|",
        f"| Consume | {plan['counts_by_decision']['consume']} | Use unchanged behind the upstream contract. |",
        f"| Adapt | {plan['counts_by_decision']['adapt']} | Keep external and translate through an AXM-owned adapter. |",
        f"| Reference | {plan['counts_by_decision']['reference']} | Harvest design and test evidence without taking a dependency. |",
        f"| Reject | {plan['counts_by_decision']['reject']} | Preserve the refusal so it is not repeatedly rediscovered. |",
        "",
    ]
    titles = {
        "consume": "Consume unchanged",
        "adapt": "Adapt behind an AXM boundary",
        "reference": "Reference without dependency",
        "reject": "Reject as a supplier",
    }
    for decision in ("consume", "adapt", "reference", "reject"):
        lines.extend([f"## {titles[decision]}", ""])
        rows = plan["decisions"][decision]
        if not rows:
            lines.extend(["No candidates in this projection.", ""])
            continue
        lines.extend(
            [
                "| Priority | Candidate | Category | Estate targets | Acquisition boundary |",
                "|---|---|---|---|---|",
            ]
        )
        for row in rows:
            boundary = row["required_adapter"] or row["integration_mode"]
            lines.append(
                "| {priority} | {name} | `{category}` | {targets} | {boundary} |".format(
                    priority=row["priority"],
                    name=row["name"].replace("|", "\\|"),
                    category=row["category"],
                    targets=", ".join(row["estate_targets"]),
                    boundary=boundary.replace("|", "\\|"),
                )
            )
        lines.append("")
    lines.extend(["## Control question", "", plan["control_question"], ""])
    return "\n".join(lines)


def write_acquisition_plan(path: Path, plan: dict[str, Any], *, markdown: bool) -> None:
    if markdown:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_acquisition_plan_markdown(plan), encoding="utf-8", newline="\n")
    else:
        write_json(path, plan)
