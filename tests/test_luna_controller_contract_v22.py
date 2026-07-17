from experiments.luna_sol_anchor_replication_v2.scripts.controller_contract_gate import run_gate

def test_luna_controller_contract_v22(tmp_path):
    receipt = run_gate(tmp_path / "controller_contract_gate.json")
    assert receipt["all_pass"], receipt
