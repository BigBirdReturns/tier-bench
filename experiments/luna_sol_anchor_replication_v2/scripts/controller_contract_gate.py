"""Deterministic zero-inference gate for the Luna v2.2 production controller."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNNER_PATH = ROOT / "run_v2.py"
spec = importlib.util.spec_from_file_location("luna_run_v22", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
CONSISTENCY_PATH = HERE / "task_visible_consistency_gate.py"
consistency_spec = importlib.util.spec_from_file_location("luna_task_visible_consistency_v222", CONSISTENCY_PATH)
assert consistency_spec and consistency_spec.loader
consistency = importlib.util.module_from_spec(consistency_spec)
consistency_spec.loader.exec_module(consistency)

STAGE = '''
import json, sys
raw=json.load(open(sys.argv[1])); out=[]
for i,r in enumerate(raw["records"]):
    p=int(r.get("priority",0)); out.append({"id":str(r["id"]),"account":str(r["account"]),"period":int(r["period"]),"kind":r["kind"],"amount_cents":int(r["amount_cents"]),"status":r["status"],"priority":p,"eligible":r["status"] in {"open","settled"} and int(r["period"]) <= int(raw["cutoff_period"]),"fee_relief_eligible":r["kind"] == "waiver" and p >= 2,"source_index":i})
json.dump({"schema":1,"cutoff_period":int(raw["cutoff_period"]),"records":out},open(sys.argv[2],"w"),sort_keys=True)
'''
SOLUTION = '''
import json,sys
from collections import defaultdict
n=json.load(open(sys.argv[1])); g=defaultdict(lambda:{"invoice":0,"credit":0,"fee":0,"relief":0,"count":0})
for r in n["records"]:
    if not r["eligible"]: continue
    b=g[r["account"]]; b["count"]+=1
    if r["kind"]=="invoice": b["invoice"]+=r["amount_cents"]
    elif r["kind"]=="credit": b["credit"]-=r["amount_cents"]
    elif r["kind"]=="fee": b["fee"]+=r["amount_cents"]
    elif r["fee_relief_eligible"]: b["relief"]+=r["amount_cents"]
a=[]
for k in sorted(g):
    b=g[k]; adj=max(0,b["fee"]-b["relief"]); a.append({"account":k,"invoice_cents":b["invoice"],"credit_cents":b["credit"],"fee_cents":b["fee"],"relief_cents":b["relief"],"adjusted_fee_cents":adj,"due_cents":b["invoice"]+b["credit"]+adj,"record_count":b["count"]})
print(json.dumps({"accounts":a,"grand_total_cents":sum(x["due_cents"] for x in a)},sort_keys=True))
'''

def packet_from_prompt(prompt: bytes) -> dict[str, Any]:
    text = prompt.decode()
    start = text.index("INPUT_PACKET_JSON_BEGIN") + len("INPUT_PACKET_JSON_BEGIN")
    end = text.index("INPUT_PACKET_JSON_END")
    return json.loads(text[start:end].strip())

def fixture_executor(mode: str):
    def execute(command: list[str], cwd: Path, prompt: bytes, final_path: Path) -> subprocess.CompletedProcess[bytes]:
        schema = Path(command[command.index("--output-schema") + 1]).name
        payload: dict[str, Any]
        if schema == "full_agent.schema.json":
            if mode == "full_valid":
                (cwd / "src/ledger_stage.py").write_text(STAGE, encoding="utf-8")
                (cwd / "src/solution.py").write_text(SOLUTION, encoding="utf-8")
            elif mode == "full_out_of_scope":
                (cwd / "README.md").write_text("out of scope", encoding="utf-8")
            payload = {"summary":"bounded fixture", "files_inspected_claimed":[], "files_changed_claimed":[], "commands_claimed":[], "unresolved_blockers":["python unavailable"]}
        elif schema == "planner_initial.schema.json":
            if mode == "planner_null":
                payload = {"action":"spawn_hand_1", "anchor_state":None, "work_graph":[], "crate":None, "decision_record":[]}
            else:
                payload = {"action":"spawn_hand_1", "anchor_state":{"objective":"preserve durable progress","invariants":["bounded"],"decisions":["split stages"],"open_risks":[],"stop_condition":"validator passes"},"work_graph":[{"node_id":"hand_1","objective":"normalize input","depends_on":[]},{"node_id":"hand_2","objective":"roll up result","depends_on":["hand_1"]}],"crate":{"crate_id":"fixture-hand-1","objective":"implement normalization","allowed_paths":["src/ledger_stage.py"],"forbidden_paths":["src/solution.py"],"dependencies":[],"visible_context_refs":["task"],"validator_ids":["stage"],"command_budget":4,"wall_time_seconds":60,"stop_condition":"stage passes"},"decision_record":["two dependent hands"]}
        elif schema == "planner_continuation.schema.json":
            payload = {"action":"spawn_hand_2", "anchor_state":{"objective":"finish bounded rollup","invariants":["preserve HAND 1"],"decisions":["edit solution"],"open_risks":[],"stop_condition":"visible validator passes"},"crate":{"crate_id":"fixture-hand-2","objective":"implement rollup","allowed_paths":["src/solution.py"],"forbidden_paths":["src/ledger_stage.py"],"dependencies":["hand_1"],"visible_context_refs":["accepted_hand_1"],"validator_ids":["visible"],"command_budget":4,"wall_time_seconds":60,"stop_condition":"visible validator passes"}}
        elif schema == "spark.schema.json":
            packet = packet_from_prompt(prompt); crate = packet["hand_crate"]
            if "src/ledger_stage.py" in crate["allowed_paths"]:
                (cwd / "src/ledger_stage.py").write_text(STAGE, encoding="utf-8")
                if mode == "spark_out_of_scope":
                    (cwd / "src/solution.py").write_text(SOLUTION, encoding="utf-8")
            else:
                (cwd / "src/solution.py").write_text(SOLUTION, encoding="utf-8")
            payload = {"crate_id":crate["crate_id"],"summary":"fixture execution","files_inspected_claimed":[],"files_changed_claimed":[],"commands_claimed":[],"unresolved_blockers":["runtime unavailable"]}
        else:
            raise AssertionError(schema)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, b"", b"")
    return execute

def run_gate(output: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="luna-v22-contract-") as temp:
        root = Path(temp); packet = {"task_id":"derived_ledger_rollup_v2"}
        def check(name: str, passed: bool, detail: str = "") -> None:
            checks.append({"name":name,"code_path":"experiments/luna_sol_anchor_replication_v2/run_v2.py","result":"PASS" if passed else "FAIL","detail":detail})
        cli_identity = runner.require_cli_identity()
        check(
            "pinned_cli_identity_matches_authorized_surface",
            cli_identity == {
                "path": str(runner.CLI),
                "sha256": runner.CLI_SHA256,
                "version": runner.CLI_VERSION,
                "execution_chain": [{"path": str(runner.CLI), "sha256": runner.CLI_SHA256, "version": runner.CLI_VERSION}],
            },
            json.dumps(cli_identity, sort_keys=True),
        )
        missing_cli = root / "missing-codex.exe"
        try:
            runner.require_cli_identity(path=missing_cli, expected_path=missing_cli, version_text=runner.CLI_VERSION)
            missing_refused = False
        except runner.ControllerError as exc:
            missing_refused = exc.code == "CLI_MISSING"
        check("missing_cli_refused_before_dispatch", missing_refused)
        mismatched_cli = root / "mismatched-codex.exe"
        mismatched_cli.write_bytes(b"not the authorized executable\n")
        try:
            runner.require_cli_identity(path=mismatched_cli, expected_path=mismatched_cli, version_text=runner.CLI_VERSION)
            mismatch_refused = False
        except runner.ControllerError as exc:
            mismatch_refused = exc.code == "CLI_HASH_MISMATCH"
        check("hash_mismatched_cli_refused_before_dispatch", mismatch_refused)
        full = runner.run_full(root / "full", "trial-001", "full_valid", "fixture", "low", 0, packet, fixture_executor("full_valid"))
        check("full_agent_diff_admitted_despite_advisory_blocker", bool(full.get("candidate") and full["call"]["final_json"]["unresolved_blockers"]), json.dumps(full.get("validation"), sort_keys=True))
        nodiff = runner.run_full(root / "nodiff", "trial-001", "full_nodiff", "fixture", "low", 0, packet, fixture_executor("full_nodiff"))
        check("full_agent_no_diff_typed_disposition", nodiff["validation"].get("disposition") == "NO_CANDIDATE_NO_DIFF")
        outscope = runner.run_full(root / "outscope", "trial-001", "full_outscope", "fixture", "low", 0, packet, fixture_executor("full_out_of_scope"))
        check("full_agent_out_of_scope_rejected", outscope["validation"].get("disposition") == "REJECTED_PATH_VIOLATION")
        planner_subject = root / "planner_subject"; runner.initialize_subject(planner_subject)
        planner = runner.invoke(root / "planner", planner_subject, "fixture", "low", "read-only", "planner_initial", packet, "planner_initial.schema.json", fixture_executor("planner_null"))
        check("v21_null_anchor_rejected_by_schema", bool(planner["instance_errors"]))
        chain = runner.run_chain(root / "chain", "trial-001", 0, False, packet, fixture_executor("chain"))
        check("valid_initial_planner_and_spark_hand1_admitted", chain.get("accepted_hand_1", {}).get("visible_validators", {}).get("stage", {}).get("passed", False))
        correct = chain.get("candidate")
        chain_no_anchor = runner.run_chain(root / "chain", "trial-001", 0, True, packet, fixture_executor("chain"))
        fork_a = root / "chain" / "trial-001" / "luna_spark_correct_anchor" / "continuation_base"
        fork_n = root / "chain" / "trial-001" / "luna_spark_no_anchor" / "continuation_base"
        check("accepted_hand1_cloned_to_independent_forks", fork_a.is_dir() and fork_n.is_dir() and runner.tree_state(fork_a) == runner.tree_state(fork_n))
        check("correct_and_no_anchor_continuations_use_production_parser", chain.get("planner_continuation", {}).get("schema_valid") and chain_no_anchor.get("planner_continuation", {}).get("schema_valid"))
        check("valid_hand2_applied_independently", bool(correct and chain_no_anchor.get("candidate")), json.dumps({"correct":chain,"no_anchor":chain_no_anchor}, sort_keys=True, default=str))
        grade = runner.grade_candidate(full.get("candidate"), root / "full" / "trial-001" / "full_valid")
        check("external_hidden_grader_typed_grade", grade.get("outcome") in {"pass", "fail"}, json.dumps(grade, sort_keys=True))
        failed = runner.run_chain(root / "failed", "trial-002", 0, False, packet, fixture_executor("planner_null"))
        forks = list((root / "failed" / "trial-002").glob("luna_spark_*")) if (root / "failed" / "trial-002").exists() else []
        check("failed_prelude_emits_typed_disposition_without_forks", failed.get("disposition") == "NOT_RUN_PRELUDE_PLANNER_REJECTED" and not forks, json.dumps(failed, sort_keys=True, default=str))
        shared_failure = root / "shared_failure"
        first_failure = runner.run_chain(shared_failure, "trial-003", 0, False, packet, fixture_executor("spark_out_of_scope"))
        second_failure = runner.run_chain(shared_failure, "trial-003", 0, True, packet, fixture_executor("spark_out_of_scope"))
        planner_calls = list((shared_failure / "trial-003" / "split_prelude").glob("planner_initial/call/dispatch.json"))
        check("shared_failed_prelude_is_reused_without_controller_exception", first_failure.get("disposition") == "PRELUDE_HAND1_PATH_VIOLATION" and second_failure.get("disposition") == "PRELUDE_HAND1_PATH_VIOLATION" and second_failure.get("error", {}).get("code") == "PRELUDE_HAND1_PATH_VIOLATION" and len(planner_calls) == 1, json.dumps({"first": first_failure, "second": second_failure}, sort_keys=True, default=str))
        try:
            runner.create_fork(root / "chain" / "trial-001" / "split_prelude" / "accepted_state", fork_a)
            idempotent = False
        except runner.ControllerError as exc:
            idempotent = exc.code == "FORK_DESTINATION_EXISTS"
        check("fork_setup_is_idempotent_and_non_aliasing", idempotent and fork_a.resolve() != (root / "chain" / "trial-001" / "split_prelude" / "accepted_state").resolve())
        receipts = list((root / "chain").rglob("final_receipt.json"))
        receipt_schema = json.loads((runner.SCHEMAS / "final_receipt.schema.json").read_text(encoding="utf-8"))
        check("production_final_receipts_validate", bool(receipts) and all(not runner.validate_instance(json.loads(p.read_text()), receipt_schema) for p in receipts))
        dispatches = list(root.rglob("dispatch.json"))
        config_ok = bool(dispatches) and all("features.multi_agent=false" in json.loads(path.read_text(encoding="utf-8"))["command"] and "agents.max_depth=1" in json.loads(path.read_text(encoding="utf-8"))["command"] and "agents.max_threads=1" in json.loads(path.read_text(encoding="utf-8"))["command"] and "agents.max_depth=0" not in json.loads(path.read_text(encoding="utf-8"))["command"] for path in dispatches)
        check("production_command_vectors_disable_subagents_with_valid_depth", config_ok)
    fresh_consistency = consistency.evaluate()
    saved_consistency_path = runner.TASK / "oracle_self_test_v222.json"
    saved_consistency = json.loads(saved_consistency_path.read_text(encoding="utf-8"))
    check("fresh_task_visible_consistency_matches_sealed_receipt", fresh_consistency == saved_consistency and fresh_consistency.get("all_pass"), json.dumps(fresh_consistency, sort_keys=True))
    partial = runner.build_comparison([{"trial":"replicate_001","arm":"SOL_FULL","hidden_outcome":"NOT_RUN_NO_CANDIDATE","candidate":False,"disposition":"NO_CANDIDATE_NO_DIFF","error":None}])
    check("incomplete_collection_suppresses_capability_verdicts", partial["disposition"] == "PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT" and not partial["comparison_rules_applied"] and partial["sol_replication_verdict"] is None and partial["anchor_mechanism_verdict"] is None, json.dumps(partial, sort_keys=True))
    def complete_comparison_table(correct: list[str], no_anchor: list[str], sol: list[str] | None = None) -> list[dict[str, Any]]:
        sol = sol or ["pass", "pass", "pass"]
        result: list[dict[str, Any]] = []
        for index in range(3):
            trial = f"replicate_{index + 1:03d}"
            outcomes = {
                "SOL_FULL": sol[index],
                "LUNA_FULL": "pass",
                "LUNA_SPARK_CORRECT_ANCHOR": correct[index],
                "LUNA_SPARK_NO_ANCHOR": no_anchor[index],
            }
            for arm, hidden in outcomes.items():
                result.append({"trial":trial,"arm":arm,"hidden_outcome":hidden,"candidate":True,"disposition":"CANDIDATE_ADMITTED","error":None})
        return result
    complete_table = complete_comparison_table(["pass", "pass", "pass"], ["fail", "fail", "fail"])
    complete = runner.build_comparison(complete_table)
    check("complete_collection_matches_preregistered_anchor_signal", complete["disposition"] == "COMPLETE" and complete["comparison_rules_applied"] and complete["sol_replication_verdict"] == "SOL_LEVEL_REPLICATED_ON_FROZEN_TASK" and complete["anchor_mechanism_verdict"] == "ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK", json.dumps(complete, sort_keys=True))
    two_to_one = runner.build_comparison(complete_comparison_table(["pass", "pass", "fail"], ["fail", "fail", "pass"]))
    check("two_correct_passes_one_no_anchor_pass_with_two_favored_pairs_signals", two_to_one["anchor_mechanism_verdict"] == "ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK" and two_to_one["counts"]["paired_trials_favor_correct_anchor"] == 2, json.dumps(two_to_one, sort_keys=True))
    equal = runner.build_comparison(complete_comparison_table(["pass", "pass", "fail"], ["pass", "fail", "pass"]))
    check("equal_pass_counts_do_not_signal", equal["counts"]["correct_anchor_pass"] == equal["counts"]["no_anchor_pass"] and equal["anchor_mechanism_verdict"] == "NO_ANCHOR_MECHANISM_IDENTIFIED", json.dumps(equal, sort_keys=True))
    one_favored = runner.build_comparison(complete_comparison_table(["pass", "fail", "fail"], ["fail", "fail", "fail"]))
    check("fewer_than_two_favored_pairs_do_not_signal", one_favored["counts"]["correct_anchor_pass"] > one_favored["counts"]["no_anchor_pass"] and one_favored["counts"]["paired_trials_favor_correct_anchor"] == 1 and one_favored["anchor_mechanism_verdict"] == "NO_ANCHOR_MECHANISM_IDENTIFIED", json.dumps(one_favored, sort_keys=True))
    duplicate = complete_table[:-1] + [complete_table[0]]
    duplicate_result = runner.build_comparison(duplicate)
    check("duplicate_or_missing_pair_suppresses_capability_verdicts", duplicate_result["disposition"] == "PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT" and not duplicate_result["comparison_rules_applied"] and duplicate_result["anchor_mechanism_verdict"] is None, json.dumps(duplicate_result, sort_keys=True))
    sol_regression = runner.build_comparison(complete_comparison_table(["pass", "pass", "pass"], ["fail", "fail", "fail"], ["pass", "pass", "fail"]))
    check("sol_replication_expression_remains_unchanged", sol_regression["sol_replication_verdict"] == "TASK_NON_INFORMATIVE_FOR_SOL_REPLICATION" and sol_regression["anchor_mechanism_verdict"] == "ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK", json.dumps(sol_regression, sort_keys=True))
    result = {"schema":"luna-sol-anchor-replication/controller-contract-gate@2.2.2","protocol_revision":"2.2.2","code_paths":["require_cli_identity","run_full","run_chain","apply_hand","create_fork","grade_candidate","seal_final_receipt","extract_remote_error","build_comparison"],"cli_identity":cli_identity,"hashes":{"runner_sha256":runner.sha(RUNNER_PATH),"schema_hashes":{p.name:runner.sha(p) for p in runner.SCHEMAS.glob("*.json")},"prompt_hashes":{p.name:runner.sha(p) for p in runner.PROMPTS.glob("*.txt")},"task_packet_sha256":runner.sha(runner.TASK / "task_packet.json"),"hidden_grader_sha256":runner.sha(runner.PRIVATE / "hidden_grader.py"),"visible_bundle_sha256":fresh_consistency["build"]["visible_bundle_sha256"],"task_visible_consistency_receipt_sha256":runner.sha(saved_consistency_path)},"tests":checks,"all_pass":all(x["result"] == "PASS" for x in checks)}
    runner.write(output, runner.canon(result))
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("output", type=Path)
    value = run_gate(parser.parse_args().output); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["all_pass"] else 1)
