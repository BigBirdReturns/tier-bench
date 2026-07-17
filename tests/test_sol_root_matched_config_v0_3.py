"""Model-free regressions for the additive Sol-root v0.3 proposal."""

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

from compile_proposal_v0_3 import (  # noqa: E402
    ProposalError,
    compile_acceptance,
    compile_custody,
    compile_schedule,
    verification,
)


def refusal(callback) -> None:
    try:
        callback()
    except ProposalError:
        return
    raise AssertionError("expected ProposalError")


def main() -> int:
    catalog = json.loads((EXPERIMENT / "generated" / "catalog_projection_v0_2.json").read_text(encoding="utf-8"))
    design = json.loads((EXPERIMENT / "design_proposal_v0_3.json").read_text(encoding="utf-8"))
    checks = 0

    schedule = compile_schedule(catalog, design)
    assert schedule["pinned_owner_cell_id"] == "gpt-5.6-sol@high#standard"
    assert schedule["catalog_cells"] == {"owner": 1, "executor": 58, "coordinator_deferred": 58}
    assert {name: phase["call_ceiling"] for name, phase in schedule["phases"].items()} == {
        "atomic_direct": 222,
        "frozen_plan_direct": 849,
        "composition_validation": 134,
        "holdout_direct": 2640,
        "paired_cross_engine_sentinels": 48,
    }
    assert schedule["initial_scientific_call_ceiling"] == 3893
    assert schedule["administrative_canary_ceiling_if_separately_authorized"] == {"initial_owner_executor": 59, "deferred_coordinator": 58}
    assert schedule["deferred_topology_c"]["scientific_call_ceiling"] == 1046
    assert schedule["conditional_repair"] == {"maximum_hand_repairs": 2942, "absolute_initial_call_ceiling": 6835}
    checks += 1

    changed_points = copy.deepcopy(design)
    changed_points["reporting"]["gross_token_ratio_points"] = [0.3, 0.5, 0.7]
    changed_schedule = compile_schedule(catalog, changed_points)
    assert changed_schedule["initial_scientific_call_ceiling"] == schedule["initial_scientific_call_ceiling"]
    assert {name: phase["call_ceiling"] for name, phase in changed_schedule["phases"].items()} == {
        name: phase["call_ceiling"] for name, phase in schedule["phases"].items()
    }
    assert changed_schedule["conditional_repair"] == schedule["conditional_repair"]
    assert schedule["schedule_depends_on_reporting_ratio_points"] is False
    checks += 1

    wrong_owner = copy.deepcopy(design)
    wrong_owner["pinned_owner_cell_id"] = "gpt-5.6-terra@high#standard"
    refusal(lambda: compile_schedule(catalog, wrong_owner))
    screenshot_primary = copy.deepcopy(design)
    screenshot_primary["catalog_authority"]["primary"] = "operator_screenshot"
    refusal(lambda: compile_schedule(catalog, screenshot_primary))
    checks += 1

    acceptance = compile_acceptance(design)
    assert acceptance["sol_state_ownership"] == "workflow_only_not_primary_grade"
    assert acceptance["above_ruler_judgment"]["primary_result_eligible"] is False
    assert "shares_subject_lineage" in acceptance["above_ruler_judgment"]["required_fields"]
    assert acceptance["grader_implementation_authorized"] is False
    checks += 1

    custody = compile_custody()
    assert custody["portable_ref_fields"] == ["repo", "commit", "path", "blob_sha256"]
    assert custody["states"][-2:] == ["custody_closed", "custody_failed"]
    assert custody["pr_authorized"] is False and custody["merge_authorized"] is False
    checks += 1

    cold = json.loads((EXPERIMENT / "cold_verification_receipt_v0_3.claude.json").read_text(encoding="utf-8"))
    closure = json.loads((EXPERIMENT / "custody_closure_receipt_v0_3.json").read_text(encoding="utf-8"))
    transitions = {(item["from"], item["to"]) for item in custody["transitions"]}
    source = closure["source_receipt"]
    assert cold["state"] == source["recorded_state"] == "reachable_verified"
    assert source["canonical_state"] == "cross_engine_verified_unmerged"
    assert ("reachable_unverified", source["canonical_state"]) in transitions
    assert (source["canonical_state"], closure["state"]) in transitions
    assert source["normalization"]["original_receipt_preserved"] is True
    assert source["normalization"]["verification_evidence_changed"] is False
    assert closure["closure"]["merge_commit"] == source["merge_commit"]
    assert closure["closure"]["ci"]["conclusion"] == "success"
    assert closure["provider_calls"] == 0 and closure["scientific_observations"] == 0
    checks += 1

    receipt = verification(catalog, design, schedule, acceptance, custody)
    assert receipt["all_pass"] is True and receipt["provider_calls"] == 0
    tampered = copy.deepcopy(schedule)
    tampered["initial_scientific_call_ceiling"] -= 1
    assert verification(catalog, design, tampered, acceptance, custody)["all_pass"] is False
    checks += 1

    parent = Path(tempfile.mkdtemp(prefix="sol-root-v03-test-"))
    try:
        out = parent / "generated"
        command = [sys.executable, str(EXPERIMENT / "compile_proposal_v0_3.py"), "compile-all",
                   "--catalog", str(EXPERIMENT / "generated" / "catalog_projection_v0_2.json"),
                   "--design", str(EXPERIMENT / "design_proposal_v0_3.json"), "--out", str(out)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr + completed.stdout
        refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert refused.returncode == 2 and "refusing to overwrite" in refused.stderr
        verify = [sys.executable, str(EXPERIMENT / "compile_proposal_v0_3.py"), "verify",
                  "--catalog", str(EXPERIMENT / "generated" / "catalog_projection_v0_2.json"),
                  "--design", str(EXPERIMENT / "design_proposal_v0_3.json"),
                  "--schedule", str(out / "schedule_proposal_v0_3.json"),
                  "--acceptance", str(out / "acceptance_contract_proposal_v0_3.json"),
                  "--custody", str(out / "custody_contract_proposal_v0_3.json")]
        verified = subprocess.run(verify, cwd=ROOT, capture_output=True, text=True)
        assert verified.returncode == 0, verified.stderr + verified.stdout
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    checks += 1

    print(f"OK - {checks} Sol-root v0.3 proposal checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
