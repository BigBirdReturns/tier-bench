from experiments.luna_sol_anchor_replication_v2.scripts.task_visible_consistency_gate import evaluate


def test_luna_task_visible_contract_is_consistent() -> None:
    receipt = evaluate()
    assert receipt["all_pass"], receipt
    assert receipt["protocol_revision"] == "2.2.2"
    assert {item["name"] for item in receipt["tests"]} >= {
        "reference_passes_visible",
        "reference_passes_hidden",
        "equivalent_passes_visible",
        "equivalent_passes_hidden",
        "old_no_relief_fails_visible",
        "old_no_relief_fails_hidden",
        "minimal_fee_waiver_witness",
        "task_packet_unchanged",
        "hidden_grader_unchanged",
    }
