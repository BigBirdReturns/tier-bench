"""Run exactly two unscored v2.2 administrative canaries through production invoke."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_v2 as controller

def git_init(root: Path) -> None:
    controller.run(["git", "init", "-q"], root)
    controller.run(["git", "config", "user.name", "Luna v2.2 Canary"], root)
    controller.run(["git", "config", "user.email", "canary@example.invalid"], root)
    controller.run(["git", "add", "."], root)
    result = controller.run(["git", "commit", "-qm", "canary baseline"], root)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))

def run(output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="luna-v22-canaries-") as temp:
        root = Path(temp); full = root / "full_repo"; full.mkdir(); (full / "value.txt").write_text("0\n", encoding="utf-8"); git_init(full)
        packet = {"task_id":"admin_value_canary","task_packet":{"task_text":"Change value.txt from 0 to 1.","allowed_files":["value.txt"]},"instruction":"Change value.txt from 0 to 1."}
        canary1_dir = root / "canary_1_full_agent"
        call1 = controller.invoke(canary1_dir / "call", full, "gpt-5.6-luna", "high", "workspace-write", "full_agent", packet, "full_agent.schema.json")
        parent1 = controller.git(["rev-parse", "HEAD"], full).stdout.decode().strip()
        validation1 = controller.candidate_check(full, {"value.txt"}, parent1, controller.PREFERRED_PYTHON, ["text"])
        controller.write(canary1_dir / "controller_receipt.json", controller.canon({"interface":"LUNA_FULL_AGENT_CANARY","call":call1,"validation":validation1,"parent_git_head":parent1,"diff_sha256":validation1.get("patch_sha256"),"state_sha256":validation1.get("state_sha256")}))

        planner = root / "planner_repo"; planner.mkdir(); (planner / "src").mkdir(); (planner / "src" / "ledger_stage.py").write_text("# synthetic parser\n", encoding="utf-8"); (planner / "src" / "solution.py").write_text("# synthetic rollup\n", encoding="utf-8"); git_init(planner)
        packet2 = {"task_id":"admin_two_hand_canary","task_packet":{"task_text":"Synthetic parser-to-rollup task. HAND 1 prepares src/ledger_stage.py and HAND 2 completes src/solution.py.","allowed_files":["src/ledger_stage.py","src/solution.py"]},"visible_state_capsule":controller.state_capsule(planner),"public_validator_catalog":[{"id":"synthetic","command":"controller-owned","scope":["src/ledger_stage.py","src/solution.py"]}],"remaining_budget":{"planner_calls":1,"spark_calls":1}}
        canary2_dir = root / "canary_2_initial_planner"
        call2 = controller.invoke(canary2_dir / "call", planner, "gpt-5.6-luna", "high", "read-only", "planner", packet2, "planner_initial.schema.json")
        anchor = crate = None; validation2 = {"accepted":False}
        if call2.get("final_json") is not None and not call2.get("instance_errors"):
            try:
                anchor, crate = controller.validate_planner(call2["final_json"], "hand_1")
                anchor_sha = controller.sha_bytes(controller.canon(anchor)); crate_envelope = controller.controller_crate(crate, controller.tree_state(planner), anchor_sha, "admin-canary", "planner_initial.schema.json")
                validation2 = {"accepted":True,"anchor_sha256":anchor_sha,"crate_sha256":controller.sha_bytes(controller.canon(crate_envelope)),"parent_state_sha256":controller.tree_state(planner),"schema_sha256":controller.sha(controller.SCHEMAS / "planner_initial.schema.json"),"prompt_sha256":controller.sha(canary2_dir / "call" / "prompt.txt")}
            except controller.ControllerError as exc:
                validation2 = {"accepted":False,"error":exc.receipt()}
        controller.write(canary2_dir / "controller_receipt.json", controller.canon({"interface":"LUNA_INITIAL_PLANNER_CANARY","call":call2,"validation":validation2,"anchor":anchor,"crate":crate}))
        artifact_root = output.parent / "canaries"
        artifact_root.mkdir(parents=True, exist_ok=True)
        for source, name in ((canary1_dir, "canary_1_full_agent"), (canary2_dir, "canary_2_initial_planner")):
            destination = artifact_root / name
            if destination.exists():
                raise RuntimeError(f"canary artifact destination already exists: {destination}")
            import shutil
            shutil.copytree(source, destination)
        result = {"schema":"luna-sol-anchor-replication/live-canaries@2.2","protocol_revision":"2.2","call_count":2,"all_pass":bool(validation1.get("accepted") and validation2.get("accepted")),"canaries":[{"id":"CANARY_1_LUNA_FULL_AGENT","passed":bool(validation1.get("accepted")),"receipt":"canaries/canary_1_full_agent/controller_receipt.json"},{"id":"CANARY_2_LUNA_INITIAL_PLANNER","passed":bool(validation2.get("accepted")),"receipt":"canaries/canary_2_initial_planner/controller_receipt.json"}],"controller_python":{"path":str(controller.PREFERRED_PYTHON),"sha256":controller.sha(controller.PREFERRED_PYTHON)}}
        controller.write(output, controller.canon(result))
        return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("output", type=Path)
    value = run(parser.parse_args().output); print(json.dumps(value, indent=2)); raise SystemExit(0 if value["all_pass"] else 1)
