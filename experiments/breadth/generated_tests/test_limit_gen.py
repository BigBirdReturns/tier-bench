# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# Gate: passes real limit.py AND kills >=1 source mutation. Mutation score: 3/6
# Pins CURRENT behavior, not intended spec. Review before trusting.
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from limit import budget_status, decision_packet, UNSOLVED


def test_budget_status_empty_inputs():
    rows = []
    got = budget_status(rows)

    assert got == {
        "spent_usd": 0.0,
        "calls": 0,
        "quota_usd": None,
        "quota_calls": None,
        "frac_used": 0.0,
        "remaining_usd": None,
        "approaching": False,
        "exhausted": False,
    }


def test_budget_status_mixed_cost_rows_and_rounding():
    rows = [
        {"cost_usd": 0.1},
        {"cost_usd": "0.25"},
        {"cost_usd": None},
        {"cost_usd": 0},
    ]

    got = budget_status(rows, quota_usd=1.0, quota_calls=8, warn_frac=0.5)

    assert got["spent_usd"] == 0.35
    assert got["calls"] == 4
    assert got["frac_used"] == 0.5
    assert got["remaining_usd"] == 0.65
    assert got["approaching"] is True
    assert got["exhausted"] is False
    assert got["quota_usd"] == 1.0
    assert got["quota_calls"] == 8


def test_budget_status_approaching_and_exhausted_thresholds():
    near = budget_status([{"cost_usd": 4.0}], quota_usd=5.0)
    assert near["frac_used"] == 0.8
    assert near["approaching"] is True
    assert near["exhausted"] is False

    over = budget_status([{"cost_usd": 11.0}], quota_usd=10.0)
    assert over["frac_used"] == 1.1
    assert over["approaching"] is True
    assert over["exhausted"] is True
    assert over["remaining_usd"] == -1.0


def test_budget_status_call_quota_only_when_currency_quota_absent_or_zero():
    only_calls = budget_status([{}, {}, {}, {}], quota_usd=0.0, quota_calls=5, warn_frac=0.8)
    assert only_calls["frac_used"] == 0.8
    assert only_calls["approaching"] is True
    assert only_calls["exhausted"] is False
    assert only_calls["remaining_usd"] is None


def test_budget_status_invalid_cost_raises_value_error():
    try:
        budget_status([{"cost_usd": "not-a-number"}])
    except ValueError as e:
        assert "could not convert string to float" in str(e)
    else:
        assert False, "invalid cost strings must raise ValueError"


def test_decision_packet_complete_map_no_unmapped():
    breadth = {
        "tasks": {
            "a": {"min_sufficient_tier": "UNSOLVED-0", "measured": {"rung": 1}},
            "b": {"min_sufficient_tier": "CLEAR", "measured": {"rung": 2}},
        }
    }
    budget = budget_status([{"cost_usd": 0.4}], quota_usd=1.0)
    packet = decision_packet(breadth, ["a", "b"], budget, top_rung="rung", est_usd_per_task=2.0)

    assert packet["recommendation"] == "DO NOT ESCALATE"
    assert packet["mapped_tasks"] == 2
    assert packet["unmapped_residual"] == []
    assert packet["projected_finish_usd"] == 0.0
    assert packet["capability_ceilings"]["tasks"] == ["a"]
    assert packet["capability_ceilings"]["note"].startswith("access does NOT help these")


def test_decision_packet_residual_within_remaining_quota():
    breadth = {"tasks": {"a": {}}}
    budget = budget_status([{"cost_usd": 0.9}], quota_usd=1.0)  # approaching=True at 0.9
    packet = decision_packet(breadth, ["a", "b", "c"], budget, top_rung="rung", est_usd_per_task=0.03)

    assert packet["recommendation"] == "DO NOT ESCALATE (yet)"
    assert packet["unmapped_residual"] == ["b", "c"]
    assert packet["projected_finish_usd"] == 0.06
    assert "still fits remaining" in packet["why"]


def test_decision_packet_residual_exceeds_remaining_quota():
    breadth = {"tasks": {"a": {}}}
    budget = budget_status([{"cost_usd": 0.9}], quota_usd=1.0)  # remaining=0.1
    packet = decision_packet(breadth, ["a", "b", "c", "d"], budget, top_rung="rung", est_usd_per_task=0.04)

    assert packet["recommendation"] == "ESCALATE ACCESS"
    assert packet["unmapped_residual"] == ["b", "c", "d"]
    assert packet["projected_finish_usd"] == 0.12
    assert packet["why"].startswith("3 task(s) still unmapped and finishing them (~$0.12)")


def test_decision_packet_requires_budget_fields():
    try:
        decision_packet({"tasks": {"a": {}}}, ["a", "b"], {}, top_rung="rung", est_usd_per_task=1.0)
    except KeyError as e:
        assert str(e) == "'approaching'"
    else:
        assert False, "missing budget keys should raise KeyError"


def test_unsolved_constant_is_public_marker():
    assert UNSOLVED == "UNSOLVED"


def main():
    test_budget_status_empty_inputs()
    test_budget_status_mixed_cost_rows_and_rounding()
    test_budget_status_approaching_and_exhausted_thresholds()
    test_budget_status_call_quota_only_when_currency_quota_absent_or_zero()
    test_budget_status_invalid_cost_raises_value_error()
    test_decision_packet_complete_map_no_unmapped()
    test_decision_packet_residual_within_remaining_quota()
    test_decision_packet_residual_exceeds_remaining_quota()
    test_decision_packet_requires_budget_fields()
    test_unsolved_constant_is_public_marker()
    print("OK")


if __name__ == "__main__":
    main()
