#!/usr/bin/env python3
"""Deterministic compiler for the proposal-only Sol-root economics protocol.

This module performs no network access and contains no provider invocation.
It projects an already-local Codex model cache, compiles call ceilings from a
reviewable design input, and verifies generated proposal artifacts byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_PREFIX = "tier-bench/sol-root-matched-config"
PROPOSAL_STATUS = "proposal_only_unactivated_unfrozen"
ROLES = ("owner", "coordinator", "executor")


class ProposalError(ValueError):
    """Typed fail-closed refusal for invalid proposal inputs."""


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalError(f"invalid UTF-8 JSON: {path}") from exc


def write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise ProposalError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProposalError(message)


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{name} must be an integer")
    require(value >= minimum, f"{name} must be >= {minimum}")
    return value


def normalize_display(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return normalized[3:] if normalized.startswith("gpt") else normalized


def speed_names(model: dict[str, Any]) -> list[str]:
    extra = model.get("additional_speed_tiers", [])
    if extra is None:
        extra = []
    if isinstance(extra, str):
        extra = [extra]
    require(isinstance(extra, list) and all(isinstance(item, str) and item for item in extra),
            f"invalid additional_speed_tiers for {model.get('slug')}")
    speeds = ["standard", *extra]
    require(len(speeds) == len(set(speeds)), f"duplicate speed for {model.get('slug')}")
    return speeds


def effort_names(model: dict[str, Any]) -> list[str]:
    levels = model.get("supported_reasoning_levels")
    require(isinstance(levels, list) and levels, f"missing reasoning levels for {model.get('slug')}")
    efforts: list[str] = []
    for level in levels:
        require(isinstance(level, dict) and isinstance(level.get("effort"), str) and level["effort"],
                f"invalid reasoning level for {model.get('slug')}")
        efforts.append(level["effort"])
    require(len(efforts) == len(set(efforts)), f"duplicate effort for {model.get('slug')}")
    return efforts


def compile_catalog(raw_catalog: bytes, catalog: dict[str, Any], display: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(catalog, dict), "catalog must be an object")
    require(isinstance(catalog.get("client_version"), str), "catalog client_version missing")
    require(isinstance(catalog.get("fetched_at"), str), "catalog fetched_at missing")
    require(isinstance(catalog.get("models"), list), "catalog models missing")
    require(isinstance(display, dict) and isinstance(display.get("labels"), list), "display labels missing")
    require(display.get("status") == PROPOSAL_STATUS, "display inventory is not proposal-only")

    visible = [model for model in catalog["models"] if model.get("visibility") == "list"]
    require(visible, "catalog has no visible models")
    slugs = [model.get("slug") for model in visible]
    require(all(isinstance(slug, str) and slug for slug in slugs), "visible model slug missing")
    require(len(slugs) == len(set(slugs)), "duplicate visible model slug")

    families: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    by_slug: dict[str, dict[str, Any]] = {}
    for model in visible:
        slug = model["slug"]
        display_name = model.get("display_name")
        require(isinstance(display_name, str) and display_name, f"display_name missing for {slug}")
        efforts = effort_names(model)
        speeds = speed_names(model)
        family_cells = len(efforts) * len(speeds)
        family = {
            "slug": slug,
            "display_name": display_name,
            "default_effort": model.get("default_reasoning_level"),
            "efforts": efforts,
            "speeds": speeds,
            "configuration_count": family_cells,
            "comp_hash": model.get("comp_hash"),
            "context_window": model.get("context_window"),
            "effective_context_window_percent": model.get("effective_context_window_percent"),
        }
        families.append(family)
        by_slug[slug] = family
        for effort in efforts:
            for speed in speeds:
                cells.append({
                    "cell_id": f"{slug}@{effort}#{speed}",
                    "model": slug,
                    "effort": effort,
                    "speed": speed,
                    "role_status": {role: "unverified" for role in ROLES},
                })

    mappings: list[dict[str, Any]] = []
    seen_display_slugs: set[str] = set()
    for entry in display["labels"]:
        require(isinstance(entry, dict), "display label must be an object")
        label, slug = entry.get("label"), entry.get("cli_slug")
        require(isinstance(label, str) and label, "display label text missing")
        require(isinstance(slug, str) and slug, "display cli_slug missing")
        require(slug not in seen_display_slugs, f"duplicate display mapping for {slug}")
        seen_display_slugs.add(slug)
        family = by_slug.get(slug)
        mappings.append({
            "display_label": label,
            "proposed_cli_slug": slug,
            "catalog_display_name": family["display_name"] if family else None,
            "family_name_aligned": bool(family and normalize_display(label) == normalize_display(family["display_name"])),
            "invocation_equivalence_proven": False,
        })

    all_names_aligned = len(mappings) == len(families) and all(item["family_name_aligned"] for item in mappings)
    sol_count = sum(family["configuration_count"] for family in families if family["slug"] == "gpt-5.6-sol")
    require(sol_count > 0, "gpt-5.6-sol owner family missing")
    return {
        "schema": f"{SCHEMA_PREFIX}/catalog-projection@0.2",
        "status": PROPOSAL_STATUS,
        "provider_calls": 0,
        "scientific_observations": 0,
        "source": {
            "client_version": catalog["client_version"],
            "fetched_at": catalog["fetched_at"],
            "raw_catalog_sha256": sha256(raw_catalog),
            "display_evidence": display.get("source_evidence"),
        },
        "counts": {
            "visible_families": len(families),
            "advertised_configuration_cells": len(cells),
            "sol_owner_configuration_cells": sol_count,
            "role_admissible_cells": 0,
            "role_admissible_cells_by_role": {role: 0 for role in ROLES},
        },
        "families": families,
        "cells": cells,
        "display_mapping": {
            "family_name_alignment": all_names_aligned,
            "invocation_equivalence_proven": False,
            "entries": mappings,
        },
        "activation_rule": "A cell remains unverified until a separately authorized role canary passes on frozen bytes.",
    }


def component(name: str, formula: str, calls: int, conditional: bool = False) -> dict[str, Any]:
    return {"name": name, "formula": formula, "call_ceiling": calls, "conditional": conditional}


def sum_components(items: list[dict[str, Any]]) -> int:
    return sum(item["call_ceiling"] for item in items)


def compile_budget(catalog: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    require(catalog.get("schema") == f"{SCHEMA_PREFIX}/catalog-projection@0.2", "wrong catalog projection schema")
    require(catalog.get("status") == PROPOSAL_STATUS, "catalog projection is not proposal-only")
    require(isinstance(design, dict), "design must be an object")
    require(design.get("schema") == f"{SCHEMA_PREFIX}/design-proposal@0.2", "wrong design schema")
    require(design.get("status") == PROPOSAL_STATUS, "design is not proposal-only")
    counts = catalog["counts"]
    catalog_cells = catalog.get("cells")
    require(isinstance(catalog_cells, list), "catalog cells missing")
    observed_role_counts = {
        role: sum(1 for cell in catalog_cells if cell.get("role_status", {}).get(role) == "passed")
        for role in ROLES
    }
    basis = design.get("catalog_cell_basis")
    require(basis in {"advertised_ceiling", "role_admissible"}, "invalid catalog_cell_basis")
    if basis == "advertised_ceiling":
        s = require_int(counts["sol_owner_configuration_cells"], "Sol cells", 1)
        h = require_int(counts["advertised_configuration_cells"], "hand cells", 1)
        c = h
    else:
        s = sum(1 for cell in catalog_cells if cell.get("model") == "gpt-5.6-sol" and cell.get("role_status", {}).get("owner") == "passed")
        h = observed_role_counts["executor"]
        c = observed_role_counts["coordinator"]
        require(min(s, h, c) > 0, "role-admissible schedule basis has an empty required role")
    caps = design["promotion_caps"]
    sp = min(require_int(caps["sol_after_gate"], "sol_after_gate", 1), s)
    hp = min(require_int(caps["hands_after_gate"], "hands_after_gate", 1), h)
    cp = min(require_int(caps["coordinators_after_gate"], "coordinators_after_gate", 1), c)
    sol_top = min(require_int(caps["sol_for_topology"], "sol_for_topology", 1), sp)
    ht = min(require_int(caps["hands_for_topology"], "hands_for_topology", 1), hp)
    pairs_t = min(require_int(caps["coordinator_hand_pairs_for_topology"], "pairs_for_topology", 1), ht * cp)
    sol_e2e = min(require_int(caps["sol_for_end_to_end"], "sol_for_end_to_end", 1), sp)
    hands_e2e = min(require_int(caps["hands_for_end_to_end"], "hands_for_end_to_end", 1), hp)
    pairs_e2e = min(require_int(caps["coordinator_hand_pairs_for_end_to_end"], "pairs_for_end_to_end", 1), pairs_t)
    direct_ext = min(require_int(caps["direct_cells_for_width_extension"], "direct_cells_for_width_extension", 1),
                     sol_e2e * hands_e2e)
    pair_ext = min(require_int(caps["coordinator_pairs_for_width_extension"], "coordinator_pairs_for_width_extension", 1),
                   pairs_e2e)
    effective_caps = {
        "sol_after_gate": sp,
        "hands_after_gate": hp,
        "coordinators_after_gate": cp,
        "sol_for_topology": sol_top,
        "hands_for_topology": ht,
        "coordinator_hand_pairs_for_topology": pairs_t,
        "sol_for_end_to_end": sol_e2e,
        "hands_for_end_to_end": hands_e2e,
        "coordinator_hand_pairs_for_end_to_end": pairs_e2e,
        "direct_cells_for_width_extension": direct_ext,
        "coordinator_pairs_for_width_extension": pair_ext,
    }

    atomic_cfg = design["atomic"]
    gate = require_int(atomic_cfg["gate_observations_per_cell"], "gate observations", 1)
    confirm_crates = require_int(atomic_cfg["confirmation_crates"], "confirmation crates", 1)
    confirm_reps = require_int(atomic_cfg["confirmation_replicates"], "confirmation replicates", 1)
    atomic = [
        component("sol_gate", f"{s}*{gate}", s * gate),
        component("executor_gate", f"{h}*{gate}", h * gate),
        component("sol_confirmation", f"{sp}*{confirm_crates}*{confirm_reps}", sp * confirm_crates * confirm_reps),
        component("executor_confirmation", f"{hp}*{confirm_crates}*{confirm_reps}", hp * confirm_crates * confirm_reps),
        component("coordinator_gate", f"{c}*{gate}", c * gate),
        component("coordinator_confirmation", f"{cp}*{confirm_crates}*{confirm_reps}", cp * confirm_crates * confirm_reps),
    ]

    topology_cfg = design["frozen_plan_topology"]
    tf = require_int(topology_cfg["families"], "topology families", 1)
    widths = [require_int(item, "topology width", 1) for item in topology_cfg["base_widths"]]
    extension_width = require_int(topology_cfg["extension_width"], "topology extension width", 1)
    base_sum = sum(widths)
    base_waves = sum(width + 1 for width in widths)
    topology = [
        component("bounded_sol_graph_execution", f"{sol_top}*{tf}*{len(widths)}", sol_top * tf * len(widths)),
        component("hands_without_coordinator", f"{ht}*{tf}*{base_sum}", ht * tf * base_sum),
        component("coordinator_hand_pairs", f"{pairs_t}*{tf}*{base_waves}", pairs_t * tf * base_waves),
        component("width_extension_sol", f"{sol_top}*{tf}", sol_top * tf, True),
        component("width_extension_hands", f"{topology_cfg['extension_hands']}*{tf}*{extension_width}",
                  require_int(topology_cfg["extension_hands"], "topology extension hands", 1) * tf * extension_width, True),
        component("width_extension_coordinator", f"{topology_cfg['extension_pairs']}*{tf}*({extension_width}+1)",
                  require_int(topology_cfg["extension_pairs"], "topology extension pairs", 1) * tf * (extension_width + 1), True),
    ]

    e2e = design["end_to_end"]
    families = require_int(e2e["positive_families"], "positive families", 1)
    coord_families = require_int(e2e["coordinator_families"], "coordinator families", 1)
    e2e_widths = [require_int(item, "end-to-end width", 1) for item in e2e["base_widths"]]
    ext_widths = [require_int(item, "extension width", 1) for item in e2e["extension_widths"]]
    b_max = require_int(e2e["root_owner_call_ceiling"], "root owner call ceiling", 1)
    require(e2e.get("root_continuation_policy") == "controller_triggered_only", "root continuation must be trigger-only")
    require(require_int(e2e["root_owner_min_calls"], "root owner minimum", 1) == 1, "root owner minimum must be one")
    k_a = lambda n: n + 2
    k_c = lambda n, waves: n + waves + 2
    direct_base_cells = sol_e2e * hands_e2e
    e2e_components = [
        component("matched_b_base", f"{sol_e2e}*{families}*{len(e2e_widths)}*{b_max}",
                  sol_e2e * families * len(e2e_widths) * b_max),
        component("direct_a_base", f"{direct_base_cells}*{families}*sum(n+2)",
                  direct_base_cells * families * sum(k_a(n) for n in e2e_widths)),
        component("coordinator_c_base", f"{pairs_e2e}*{coord_families}*sum(n+1+2)",
                  pairs_e2e * coord_families * sum(k_c(n, 1) for n in e2e_widths)),
    ]
    negative = e2e["negative_controls"]
    negative_tasks = require_int(negative["tasks"], "negative tasks", 1)
    coordinator_negatives = require_int(negative["coordinator_sensitive_tasks"], "coordinator negatives", 0)
    negative_width = require_int(negative["delegated_width_ceiling"], "negative delegated width", 1)
    negative_b = negative_tasks * sol_e2e * b_max
    negative_a = negative_tasks * sol_e2e * k_a(negative_width)
    negative_c = coordinator_negatives * k_c(negative_width, 1)
    e2e_components.append(component("negative_controls", "B+A+C declared negative schedule", negative_b + negative_a + negative_c))
    e2e_components.extend([
        component("matched_b_width_extension", f"{sol_e2e}*{families}*{len(ext_widths)}*{b_max}",
                  sol_e2e * families * len(ext_widths) * b_max, True),
        component("direct_a_width_extension", f"{direct_ext}*{families}*sum(n+2)",
                  direct_ext * families * sum(k_a(n) for n in ext_widths), True),
        component("coordinator_c_width_extension", f"{pair_ext}*{coord_families}*sum(n+1+2)",
                  pair_ext * coord_families * sum(k_c(n, 1) for n in ext_widths), True),
    ])

    holdout_cfg = design["holdout"]
    repos = require_int(holdout_cfg["repositories"], "holdout repositories", 1)
    seeds = require_int(holdout_cfg["seeds"], "holdout seeds", 1)
    hold_families = require_int(holdout_cfg["positive_families"], "holdout families", 1)
    negatives = require_int(holdout_cfg["negative_boundary_tasks"], "holdout negatives", 1)
    negative_max_width = require_int(holdout_cfg["negative_delegated_width_ceiling"], "holdout negative width", 1)
    positive_per_width = repos * seeds * hold_families

    def holdout_components(width_pair: list[int]) -> list[dict[str, Any]]:
        pair = [require_int(item, "holdout width", 1) for item in width_pair]
        require(len(pair) == 2, "holdout needs exactly two widths")
        positive_tasks = positive_per_width * len(pair)
        return [
            component("matched_b", f"{positive_tasks}*{b_max}", positive_tasks * b_max),
            component("adaptive_positive", f"{positive_per_width}*sum(n+1+2)",
                      positive_per_width * sum(k_c(n, 1) for n in pair)),
            component("negative_boundary", f"{negatives}*({b_max}+{negative_max_width}+1+2)",
                      negatives * (b_max + k_c(negative_max_width, 1))),
        ]

    hold_8_16 = holdout_components(holdout_cfg["width_pair_8_16"])
    hold_16_32 = holdout_components(holdout_cfg["width_pair_16_32"])

    sentinel = design["sentinels"]
    sentinel_calls = (require_int(sentinel["phase_count"], "phase count", 1)
                      * require_int(sentinel["boundaries_per_phase"], "boundaries per phase", 1)
                      * require_int(sentinel["calls_per_boundary"], "calls per boundary", 1))
    atomic_total, topology_total, e2e_total = map(sum_components, (atomic, topology, e2e_components))
    hold_8_16_total, hold_16_32_total = map(sum_components, (hold_8_16, hold_16_32))
    total_8_16 = atomic_total + topology_total + e2e_total + hold_8_16_total + sentinel_calls
    total_16_32 = atomic_total + topology_total + e2e_total + hold_16_32_total + sentinel_calls

    fresh_repair_hands = (
        direct_base_cells * families * sum(e2e_widths)
        + pairs_e2e * coord_families * sum(e2e_widths)
        + negative_tasks * sol_e2e * negative_width
        + coordinator_negatives * negative_width
        + direct_ext * families * sum(ext_widths)
        + pair_ext * coord_families * sum(ext_widths)
    )
    hold_repair_8_16 = positive_per_width * sum(holdout_cfg["width_pair_8_16"]) + negatives * negative_max_width
    hold_repair_16_32 = positive_per_width * sum(holdout_cfg["width_pair_16_32"]) + negatives * negative_max_width

    return {
        "schema": f"{SCHEMA_PREFIX}/call-budget-proposal@0.2",
        "status": PROPOSAL_STATUS,
        "provider_calls_authorized": False,
        "scientific_schedule_frozen": False,
        "benchmark_tasks_defined": False,
        "inputs": {
            "catalog_projection_canonical_sha256": sha256(canonical(catalog)),
            "design_canonical_sha256": sha256(canonical(design)),
            "catalog_cell_basis": basis,
            "advertised_cells": counts["advertised_configuration_cells"],
            "observed_role_admissible_cells": observed_role_counts,
            "eligible_role_cells": {"owner": s, "executor": h, "coordinator": c},
        },
        "baseline_call_rule": {
            "minimum_owner_calls": 1,
            "owner_call_ceiling": b_max,
            "continuation": "controller_triggered_only",
            "unused_opportunities_are_not_charged": True,
        },
        "promotion_caps": caps,
        "effective_promotion_caps": effective_caps,
        "phases": {
            "atomic_screening": {"components": atomic, "call_ceiling": atomic_total},
            "frozen_plan_topology": {"components": topology, "call_ceiling": topology_total},
            "fresh_end_to_end": {"components": e2e_components, "call_ceiling": e2e_total},
            "holdout_8_16": {"components": hold_8_16, "call_ceiling": hold_8_16_total},
            "holdout_16_32": {"components": hold_16_32, "call_ceiling": hold_16_32_total},
            "phase_boundary_sentinels": {"call_ceiling": sentinel_calls, "measurement_epochs_created": 0},
        },
        "scheduled_call_ceilings": {
            "holdout_8_16": total_8_16,
            "holdout_16_32": total_16_32,
        },
        "conditional_repair": {
            "policy": "At most one validator-triggered repair per failed hand crate in promoted end-to-end phases only.",
            "fresh_end_to_end_hand_calls": fresh_repair_hands,
            "holdout_8_16_hand_calls": hold_repair_8_16,
            "holdout_16_32_hand_calls": hold_repair_16_32,
            "absolute_call_ceiling_8_16": total_8_16 + fresh_repair_hands + hold_repair_8_16,
            "absolute_call_ceiling_16_32": total_16_32 + fresh_repair_hands + hold_repair_16_32,
        },
        "epoch_rule": {
            "phase_boundary_sentinel_does_not_create_epoch": True,
            "split_only_on_frozen_identity_or_behavioral_trigger": True,
            "additional_calls_per_forced_split": require_int(sentinel["calls_per_forced_epoch_split"], "epoch split calls", 0),
        },
        "accounting": {
            "primary_gross_token_formula": "input_tokens + output_tokens",
            "cached_input_tokens": "component_of_input_tokens_not_added_again",
            "reasoning_output_tokens": "component_of_output_tokens_not_added_again_unless_frozen_provider_semantics_prove_disjoint",
            "subscription_quota": "separate_ledger_when_telemetry_available",
            "monetary_cost": "only_actual_billing_or_official_versioned_rate_table",
        },
        "advancement_rule": "Every later phase and width extension is conditional on its prospective promotion and economics gate.",
    }


def compile_canary_budget(catalog: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    counts = catalog["counts"]
    advertised = require_int(counts["advertised_configuration_cells"], "advertised cells", 1)
    sol = require_int(counts["sol_owner_configuration_cells"], "Sol cells", 1)
    cfg = design["administrative_canaries"]
    require(cfg.get("retry_policy") == "none", "administrative canary retry policy must be none")
    require(set(cfg.get("roles", [])) == set(ROLES), "administrative canary roles must cover owner, coordinator, executor")
    require(cfg.get("calls_per_cell_per_role") == 1, "administrative calls per cell per role must be one")
    roles = [
        {"role": "owner", "eligible_cells": sol, "calls_per_cell": 1, "call_ceiling": sol},
        {"role": "executor", "eligible_cells": advertised, "calls_per_cell": 1, "call_ceiling": advertised},
        {"role": "coordinator", "eligible_cells": advertised, "calls_per_cell": 1, "call_ceiling": advertised},
    ]
    return {
        "schema": f"{SCHEMA_PREFIX}/administrative-canary-budget-proposal@0.2",
        "status": PROPOSAL_STATUS,
        "provider_calls_authorized": False,
        "scientific_observations_minted": 0,
        "benchmark_tasks_defined": False,
        "catalog_projection_canonical_sha256": sha256(canonical(catalog)),
        "roles": roles,
        "maximum_provider_calls_if_separately_authorized": sum(item["call_ceiling"] for item in roles),
        "retry_policy": "none",
        "stopping_rules": [
            "A failed transport blocks that cell in every not-yet-tested role.",
            "A completed role failure blocks only that role unless the receipt proves a shared transport defect.",
            "No automatic replacement, repair, or effort substitution is permitted.",
        ],
        "evidence_rule": "Every attempted call is charged to quota and preserved, but no canary is a scientific benchmark observation.",
        "activation_sequence": [
            "deterministic_catalog_mapping",
            "separately_authorized_administrative_role_canaries",
            "freeze_candidate_from_passing_cells",
            "separately_authorized_atomic_screening",
        ],
        "synthetic_packet_status": "not_authored_by_this_proposal",
    }


def gross_token_load(usage: dict[str, Any]) -> int:
    input_tokens = require_int(usage.get("input_tokens"), "input_tokens", 0)
    output_tokens = require_int(usage.get("output_tokens"), "output_tokens", 0)
    cached = require_int(usage.get("cached_input_tokens", 0), "cached_input_tokens", 0)
    reasoning = require_int(usage.get("reasoning_output_tokens", 0), "reasoning_output_tokens", 0)
    require(cached <= input_tokens, "cached input exceeds input tokens")
    require(reasoning <= output_tokens, "reasoning output exceeds output tokens")
    return input_tokens + output_tokens


def verify_generated(catalog: dict[str, Any], design: dict[str, Any], budget: dict[str, Any], canary: dict[str, Any]) -> dict[str, Any]:
    expected_budget = compile_budget(catalog, design)
    expected_canary = compile_canary_budget(catalog, design)
    budget_match = canonical(budget) == canonical(expected_budget)
    canary_match = canonical(canary) == canonical(expected_canary)
    return {
        "schema": f"{SCHEMA_PREFIX}/offline-verification@0.2",
        "status": PROPOSAL_STATUS,
        "catalog_projection_valid": catalog.get("schema") == f"{SCHEMA_PREFIX}/catalog-projection@0.2",
        "budget_exact_match": budget_match,
        "canary_budget_exact_match": canary_match,
        "compiler_sha256": sha256(Path(__file__).read_bytes()),
        "catalog_projection_canonical_sha256": sha256(canonical(catalog)),
        "design_canonical_sha256": sha256(canonical(design)),
        "call_budget_canonical_sha256": sha256(canonical(budget)),
        "administrative_canary_budget_canonical_sha256": sha256(canonical(canary)),
        "provider_calls": 0,
        "scientific_observations": 0,
        "all_pass": budget_match and canary_match,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    compile_all = sub.add_parser("compile-all")
    compile_all.add_argument("--catalog", type=Path, required=True)
    compile_all.add_argument("--display", type=Path, required=True)
    compile_all.add_argument("--design", type=Path, required=True)
    compile_all.add_argument("--out", type=Path, required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--catalog", type=Path, required=True)
    verify.add_argument("--design", type=Path, required=True)
    verify.add_argument("--budget", type=Path, required=True)
    verify.add_argument("--canary-budget", type=Path, required=True)
    verify.add_argument("--receipt", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "compile-all":
            if args.out.exists():
                require(args.out.is_dir() and not any(args.out.iterdir()), f"refusing to overwrite: {args.out}")
            raw_catalog, catalog_data = read_json(args.catalog)
            _, display_data = read_json(args.display)
            _, design = read_json(args.design)
            projection = compile_catalog(raw_catalog, catalog_data, display_data)
            budget = compile_budget(projection, design)
            canary = compile_canary_budget(projection, design)
            args.out.mkdir(parents=True, exist_ok=True)
            write_new(args.out / "catalog_projection_v0_2.json", projection)
            write_new(args.out / "call_budget_proposal_v0_2.json", budget)
            write_new(args.out / "administrative_canary_budget_proposal_v0_2.json", canary)
            receipt = verify_generated(projection, design, budget, canary)
            write_new(args.out / "offline_verification_receipt_v0_2.json", receipt)
            print(canonical(receipt).decode("utf-8"), end="")
            return 0

        _, catalog = read_json(args.catalog)
        _, design = read_json(args.design)
        _, budget = read_json(args.budget)
        _, canary = read_json(args.canary_budget)
        receipt = verify_generated(catalog, design, budget, canary)
        if args.receipt:
            write_new(args.receipt, receipt)
        print(canonical(receipt).decode("utf-8"), end="")
        return 0 if receipt["all_pass"] else 1
    except ProposalError as exc:
        print(f"SOL_ROOT_PROPOSAL_REFUSED: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
