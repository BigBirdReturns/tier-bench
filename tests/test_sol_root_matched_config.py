"""Model-free regression tests for the Sol-root proposal compiler."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sol_root_matched_config"
sys.path.insert(0, str(EXPERIMENT))

from compile_proposal import (  # noqa: E402
    ProposalError,
    canonical,
    compile_budget,
    compile_canary_budget,
    compile_catalog,
    gross_token_load,
    verify_generated,
)


def inputs() -> tuple[bytes, dict, dict, dict]:
    catalog_path = EXPERIMENT / "fixtures" / "model_catalog_fixture_v0_2.json"
    raw = catalog_path.read_bytes()
    catalog = json.loads(raw)
    display = json.loads((EXPERIMENT / "display_inventory_v0_2.json").read_text(encoding="utf-8"))
    design = json.loads((EXPERIMENT / "design_proposal_v0_2.json").read_text(encoding="utf-8"))
    return raw, catalog, display, design


def expect_refusal(callback) -> None:
    try:
        callback()
    except ProposalError:
        return
    raise AssertionError("expected ProposalError")


def component_calls(budget: dict, phase: str, name: str) -> int:
    matches = [item for item in budget["phases"][phase]["components"] if item["name"] == name]
    assert len(matches) == 1
    return matches[0]["call_ceiling"]


def main() -> int:
    raw, raw_catalog, display, design = inputs()
    checks = 0

    projection = compile_catalog(raw, raw_catalog, display)
    assert projection["counts"] == {
        "visible_families": 7,
        "advertised_configuration_cells": 58,
        "sol_owner_configuration_cells": 12,
        "role_admissible_cells": 0,
        "role_admissible_cells_by_role": {"owner": 0, "coordinator": 0, "executor": 0},
    }
    assert projection["display_mapping"]["family_name_alignment"] is True
    assert projection["display_mapping"]["invocation_equivalence_proven"] is False
    assert all(cell["role_status"] == {"owner": "unverified", "coordinator": "unverified", "executor": "unverified"}
               for cell in projection["cells"])
    checks += 1

    assert "codex-auto-review" not in {item["slug"] for item in projection["families"]}
    checks += 1

    bad_display = copy.deepcopy(display)
    bad_display["labels"][0]["label"] = "5.4"
    mismatch = compile_catalog(raw, raw_catalog, bad_display)
    assert mismatch["display_mapping"]["family_name_alignment"] is False
    checks += 1

    duplicate_effort = copy.deepcopy(raw_catalog)
    duplicate_effort["models"][0]["supported_reasoning_levels"].append({"effort": "low"})
    expect_refusal(lambda: compile_catalog(canonical(duplicate_effort), duplicate_effort, display))
    checks += 1

    budget = compile_budget(projection, design)
    assert budget["phases"]["atomic_screening"]["call_ceiling"] == 424
    assert budget["phases"]["frozen_plan_topology"]["call_ceiling"] == 606
    assert budget["phases"]["fresh_end_to_end"]["call_ceiling"] == 1596
    assert budget["phases"]["holdout_8_16"]["call_ceiling"] == 1440
    assert budget["phases"]["holdout_16_32"]["call_ceiling"] == 2304
    assert budget["phases"]["phase_boundary_sentinels"]["call_ceiling"] == 48
    assert budget["scheduled_call_ceilings"] == {"holdout_8_16": 4114, "holdout_16_32": 4978}
    checks += 1

    assert component_calls(budget, "fresh_end_to_end", "direct_a_width_extension") == 624
    assert component_calls(budget, "fresh_end_to_end", "coordinator_c_width_extension") == 162
    assert budget["promotion_caps"]["direct_cells_for_width_extension"] == 2
    assert budget["promotion_caps"]["coordinator_pairs_for_width_extension"] == 1
    checks += 1

    repair = budget["conditional_repair"]
    assert repair["fresh_end_to_end_hand_calls"] == 1155
    assert repair["holdout_8_16_hand_calls"] == 960
    assert repair["holdout_16_32_hand_calls"] == 1824
    assert repair["absolute_call_ceiling_8_16"] == 6229
    assert repair["absolute_call_ceiling_16_32"] == 7957
    checks += 1

    baseline = budget["baseline_call_rule"]
    assert baseline == {
        "minimum_owner_calls": 1,
        "owner_call_ceiling": 2,
        "continuation": "controller_triggered_only",
        "unused_opportunities_are_not_charged": True,
    }
    checks += 1

    assert budget["accounting"]["primary_gross_token_formula"] == "input_tokens + output_tokens"
    assert gross_token_load({"input_tokens": 181612, "cached_input_tokens": 140544,
                             "output_tokens": 4086, "reasoning_output_tokens": 673}) == 185698
    checks += 1

    expect_refusal(lambda: gross_token_load({"input_tokens": 10, "cached_input_tokens": 11,
                                             "output_tokens": 2, "reasoning_output_tokens": 1}))
    expect_refusal(lambda: gross_token_load({"input_tokens": 10, "cached_input_tokens": 1,
                                             "output_tokens": 2, "reasoning_output_tokens": 3}))
    checks += 1

    canary = compile_canary_budget(projection, design)
    assert canary["maximum_provider_calls_if_separately_authorized"] == 128
    assert {item["role"]: item["call_ceiling"] for item in canary["roles"]} == {
        "owner": 12, "executor": 58, "coordinator": 58,
    }
    assert canary["provider_calls_authorized"] is False
    assert canary["scientific_observations_minted"] == 0
    checks += 1

    receipt = verify_generated(projection, design, budget, canary)
    assert receipt["all_pass"] is True and receipt["provider_calls"] == 0
    tampered = copy.deepcopy(budget)
    tampered["scheduled_call_ceilings"]["holdout_8_16"] -= 1
    assert verify_generated(projection, design, tampered, canary)["all_pass"] is False
    checks += 1

    sparse_projection = copy.deepcopy(projection)
    sparse_projection["cells"][0]["role_status"] = {"owner": "passed", "coordinator": "passed", "executor": "passed"}
    sparse_design = copy.deepcopy(design)
    sparse_design["catalog_cell_basis"] = "role_admissible"
    sparse = compile_budget(sparse_projection, sparse_design)
    assert sparse["inputs"]["eligible_role_cells"] == {"owner": 1, "executor": 1, "coordinator": 1}
    assert sparse["effective_promotion_caps"]["hands_after_gate"] == 1
    assert sparse["effective_promotion_caps"]["coordinator_pairs_for_width_extension"] == 1
    assert sparse["phases"]["atomic_screening"]["call_ceiling"] == 30
    checks += 1

    assert budget["scientific_schedule_frozen"] is False
    assert budget["benchmark_tasks_defined"] is False
    assert budget["phases"]["phase_boundary_sentinels"]["measurement_epochs_created"] == 0
    checks += 1

    admissible_projection = copy.deepcopy(projection)
    for cell in admissible_projection["cells"]:
        if cell["model"] == "gpt-5.6-sol" and cell["effort"] in {"low", "medium", "high"} and cell["speed"] == "standard":
            cell["role_status"]["owner"] = "passed"
    for cell in admissible_projection["cells"][:12]:
        cell["role_status"]["executor"] = "passed"
    for cell in admissible_projection["cells"][:6]:
        cell["role_status"]["coordinator"] = "passed"
    admissible_design = copy.deepcopy(design)
    admissible_design["catalog_cell_basis"] = "role_admissible"
    reduced = compile_budget(admissible_projection, admissible_design)
    assert reduced["inputs"]["eligible_role_cells"] == {"owner": 3, "executor": 12, "coordinator": 6}
    assert reduced["phases"]["atomic_screening"]["call_ceiling"] < 424
    checks += 1

    parent = Path(tempfile.mkdtemp(prefix="sol-root-proposal-test-"))
    try:
        out = parent / "compiled"
        command = [
            sys.executable, str(EXPERIMENT / "compile_proposal.py"), "compile-all",
            "--catalog", str(EXPERIMENT / "fixtures" / "model_catalog_fixture_v0_2.json"),
            "--display", str(EXPERIMENT / "display_inventory_v0_2.json"),
            "--design", str(EXPERIMENT / "design_proposal_v0_2.json"),
            "--out", str(out),
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr + completed.stdout
        generated_receipt = json.loads((out / "offline_verification_receipt_v0_2.json").read_text(encoding="utf-8"))
        assert generated_receipt["all_pass"] is True
        refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert refused.returncode == 2 and "refusing to overwrite" in refused.stderr
        verify_command = [
            sys.executable, str(EXPERIMENT / "compile_proposal.py"), "verify",
            "--catalog", str(out / "catalog_projection_v0_2.json"),
            "--design", str(EXPERIMENT / "design_proposal_v0_2.json"),
            "--budget", str(out / "call_budget_proposal_v0_2.json"),
            "--canary-budget", str(out / "administrative_canary_budget_proposal_v0_2.json"),
        ]
        verified = subprocess.run(verify_command, cwd=ROOT, capture_output=True, text=True)
        assert verified.returncode == 0, verified.stderr + verified.stdout
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    checks += 1

    print(f"OK - {checks} Sol-root proposal checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
