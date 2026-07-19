# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# Gate: passes real escalate.py AND kills >=1 source mutation. Mutation score: 7/8
# Pins CURRENT behavior, not intended spec. Review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
#!/usr/bin/env python3

import math

from escalate import breadth_map, classify


def test_classify_boundaries_and_stability():
    assert classify(1.0, clear_thresh=1.0, wall_thresh=0.0) == "clears"
    assert classify(0.0, clear_thresh=1.0, wall_thresh=0.0) == "wall"
    assert classify(0.5, clear_thresh=1.0, wall_thresh=0.0) == "unstable"
    assert classify(0.5, clear_thresh=0.6, wall_thresh=0.2) == "unstable"
    assert classify(0.2, clear_thresh=0.6, wall_thresh=0.2) == "wall"


def test_breadth_map_min_tier_for_clear_task():
    rows = [
        {"task_id": "t_clear", "tier": "cheap", "outcome": "pass"},
        {"task_id": "t_clear", "tier": "mid", "outcome": "pass"},
    ]
    tiers = ["cheap", "mid", "frontier", "max"]
    cost = {"cheap": 1.0, "mid": 2.0, "frontier": 3.0, "max": 10.0}

    result = breadth_map(rows, tiers, cost)
    task = result["tasks"]["t_clear"]

    assert task["min_sufficient_tier"] == "cheap"
    assert task["cost_at_min"] == 1.0
    assert task["cost_if_max_everywhere"] == 10.0
    assert task["waste_avoided"] == 9.0
    assert task["measured"] == {"cheap": "1/1", "mid": "1/1"}
    assert result["baseline_cost_usd"] == 1.0
    assert result["naive_max_everywhere_usd"] == 10.0
    assert result["saved_vs_naive_usd"] == 9.0
    assert result["escalations"] == []
    assert result["unjustified_escalations"] == []


def test_breadth_map_escalation_evidence_and_unjustified_path():
    rows = [
        {"task_id": "t_justified", "tier": "cheap", "outcome": "fail"},
        {"task_id": "t_justified", "tier": "mid", "outcome": "pass"},
        {"task_id": "t_unstable", "tier": "cheap", "outcome": "pass"},
        {"task_id": "t_unstable", "tier": "cheap", "outcome": "fail"},
        {"task_id": "t_unstable", "tier": "mid", "outcome": "fail"},
    ]
    tiers = ["cheap", "mid", "frontier", "max"]
    cost = {"cheap": 5.0, "mid": 6.0, "frontier": 7.0, "max": 20.0}

    result = breadth_map(rows, tiers, cost)
    escalations = result["escalations"]
    unjustified = result["unjustified_escalations"]

    assert len(escalations) == 2
    assert escalations[0] == {
        "task_id": "t_justified",
        "from": "cheap",
        "to": "mid",
        "evidence": "0/1 at cheap (wall) -> 1/1 at mid (clears)",
        "justified": True,
    }
    assert escalations[1]["task_id"] == "t_unstable"
    assert escalations[1]["from"] == "cheap"
    assert escalations[1]["to"] == "mid"
    assert escalations[1]["justified"] is False
    assert "1/2 at cheap is UNSTABLE" in escalations[1]["evidence"]
    assert "run more trials before escalating" in escalations[1]["evidence"]

    assert len(unjustified) == 1
    assert unjustified[0] == escalations[1]

    t_justified = result["tasks"]["t_justified"]
    t_unstable = result["tasks"]["t_unstable"]
    assert t_justified["min_sufficient_tier"] == "mid"
    assert t_unstable["min_sufficient_tier"] == "UNSOLVED at every measured tier"
    assert math.isnan(t_unstable["cost_at_min"])
    assert t_unstable["waste_avoided"] == 0.0

    assert result["baseline_cost_usd"] == 6.0
    assert result["naive_max_everywhere_usd"] == 40.0
    assert result["saved_vs_naive_usd"] == 34.0


def test_breadth_map_empty_input_and_missing_task_fields():
    result = breadth_map([], ["cheap", "mid", "max"], {"cheap": 1.0, "mid": 2.0, "max": 3.0})

    assert result["tasks"] == {}
    assert result["escalations"] == []
    assert result["unjustified_escalations"] == []
    assert result["baseline_cost_usd"] == 0.0
    assert result["naive_max_everywhere_usd"] == 0.0
    assert result["saved_vs_naive_usd"] == 0.0

    try:
        breadth_map([{"tier": "cheap", "outcome": "pass"}], ["cheap", "mid"], {"cheap": 1.0})
        raise AssertionError("Expected KeyError for missing task_id")
    except KeyError:
        pass


def test_breadth_map_missing_top_cost_defaults_to_zero():
    rows = [
        {"task_id": "t_missing_cost", "tier": "max", "outcome": "pass"},
    ]
    tiers = ["cheap", "mid", "frontier", "max"]
    cost = {"cheap": 2.0, "mid": 3.0, "frontier": 4.0}

    result = breadth_map(rows, tiers, cost)
    task = result["tasks"]["t_missing_cost"]

    assert task["min_sufficient_tier"] == "max"
    assert task["cost_at_min"] == 0.0
    assert task["cost_if_max_everywhere"] == 0.0
    assert task["waste_avoided"] == 0.0
    assert task["measured"] == {"max": "1/1"}
    assert result["baseline_cost_usd"] == 0.0
    assert result["naive_max_everywhere_usd"] == 0.0
    assert result["saved_vs_naive_usd"] == 0.0


def main() -> None:
    test_classify_boundaries_and_stability()
    test_breadth_map_min_tier_for_clear_task()
    test_breadth_map_escalation_evidence_and_unjustified_path()
    test_breadth_map_empty_input_and_missing_task_fields()
    test_breadth_map_missing_top_cost_defaults_to_zero()
    print("OK")


if __name__ == "__main__":
    main()
