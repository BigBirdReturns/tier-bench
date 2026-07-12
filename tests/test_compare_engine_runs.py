#!/usr/bin/env python3
"""Cross-engine comparison tests; independence is a checked relation."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import compare_engine_runs as compare  # noqa: E402


def _pair():
    left = json.loads((REPO / "data/orchestration/arc_c_almanac_v1.json").read_text())
    right = copy.deepcopy(left)
    right["run_id"] = "arc_c_almanac_claude_v1"
    right["engine"] = {"engine_id": "claude_fable_5", "model": "claude-fable-5",
                       "lineage": "anthropic", "surface": "claude-subscription",
                       "role": "independent_solver"}
    right["pairing"]["peer_engine_id"] = left["engine"]["engine_id"]
    right["pairing"]["peer_lineage"] = left["engine"]["lineage"]
    left["pairing"]["peer_engine_id"] = right["engine"]["engine_id"]
    left["pairing"]["peer_lineage"] = right["engine"]["lineage"]
    for run in (left, right):
        run["status"] = "sealed"
        run["measurement_claim"] = True
        run["pairing"]["state"] = "independent_run_sealed"
        run["burden"]["closure_decision"] = "sealed"
        for decision in run["decisions"]:
            decision.update({"state": "cleared", "action": "seal", "route_to": "floor",
                             "escalation_from": None, "abstained": False})
    return left, right


def test_different_lineages_with_same_contract_are_comparable():
    left, right = _pair()
    result = compare.compare_runs(left, right)
    assert result["status"] == "comparable"
    assert result["agreement"] == {"tasks": 3, "agree": 3, "rate": 1.0}


def test_decision_disagreement_is_reported_not_merged():
    left, right = _pair()
    right["decisions"][0].update({"state": "wall", "action": "abstain", "route_to": None,
                                  "escalation_from": "effort_max", "abstained": True})
    result = compare.compare_runs(left, right)
    assert result["status"] == "comparable"
    assert result["agreement"]["agree"] == 2
    assert result["tasks"][0]["agreement"] is False


def test_same_lineage_is_not_independent_evidence():
    left, right = _pair()
    right["engine"]["lineage"] = left["engine"]["lineage"]
    assert compare.compare_runs(left, right)["status"] == "invalid_pair"


def test_peer_exposure_marks_pair_contaminated():
    left, right = _pair()
    right["pairing"]["independent_before_exchange"] = False
    assert compare.compare_runs(left, right)["status"] == "contaminated"


def test_contract_drift_is_incomparable():
    left, right = _pair()
    right["pairing"]["source_commit"] = "0" * 40
    result = compare.compare_runs(left, right)
    assert result["status"] == "incomparable"
    assert "source_commit differs" in result["reasons"]


def test_unsealed_peer_stays_unpaired():
    left, right = _pair()
    right["status"] = "running"
    assert compare.compare_runs(left, right)["status"] == "unpaired"


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test(); print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1; print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
