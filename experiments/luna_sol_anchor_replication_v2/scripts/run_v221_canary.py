#!/usr/bin/env python3
"""Run only the replacement initial-planner administrative canary."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "run_v2.py"
spec = importlib.util.spec_from_file_location("luna_run_v221_canary", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def git_init(root: Path) -> None:
    for command in (("git", "init", "-q"), ("git", "config", "user.name", "Luna v2.2.1 Canary"), ("git", "config", "user.email", "canary@example.invalid")):
        result = runner.run(list(command), root)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
    runner.run(["git", "add", "."], root)
    result = runner.run(["git", "commit", "-qm", "canary baseline"], root)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))


def run(output: Path) -> dict[str, object]:
    if not runner.CLI.is_file():
        raise SystemExit(f"missing pinned CLI: {runner.CLI}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    canary_dir = output / "canary_2_initial_planner"; call_dir = canary_dir / "call"
    planner = output / "planner_repo"; (planner / "src").mkdir(parents=True)
    (planner / "src" / "ledger_stage.py").write_text("# synthetic parser\n", encoding="utf-8")
    (planner / "src" / "solution.py").write_text("# synthetic rollup\n", encoding="utf-8")
    git_init(planner)
    packet = {
        "task_id": "admin_two_hand_canary",
        "task_packet": {"task_text": "Synthetic parser-to-rollup task. HAND 1 prepares src/ledger_stage.py and HAND 2 completes src/solution.py.", "allowed_files": ["src/ledger_stage.py", "src/solution.py"]},
        "visible_state_capsule": runner.state_capsule(planner),
        "public_validator_catalog": [{"id": "synthetic", "command": "controller-owned", "scope": ["src/ledger_stage.py", "src/solution.py"]}],
        "remaining_budget": {"planner_calls": 1, "spark_calls": 1},
    }
    call = runner.invoke(call_dir, planner, "gpt-5.6-luna", "high", "read-only", "planner_initial", packet, "planner_initial.schema.json")
    anchor = None; crate = None; validation: dict[str, object] = {"accepted": False}
    if call.get("exit_code") == 0 and call.get("final_json") is not None and call.get("schema_valid") and not call.get("role_violations"):
        try:
            anchor, crate = runner.validate_planner(call["final_json"], "hand_1")
            anchor_sha = runner.sha_bytes(runner.canon(anchor))
            crate_envelope = runner.controller_crate(crate, runner.tree_state(planner), anchor_sha, "admin-canary-v221", "planner_initial.schema.json", "planner_initial_base.txt")
            validation = {"accepted": True, "anchor_sha256": anchor_sha, "crate_sha256": runner.sha_bytes(runner.canon(crate_envelope)), "parent_state_sha256": runner.tree_state(planner), "schema_sha256": runner.sha(runner.SCHEMAS / "planner_initial.schema.json"), "prompt_sha256": runner.sha(call_dir / "prompt.txt"), "role_violations": []}
        except runner.ControllerError as exc:
            validation = {"accepted": False, "error": exc.receipt()}
    receipt = {"schema": "luna-sol-anchor-replication/live-canary@2.2.1", "protocol_revision": "2.2.1", "all_pass": bool(validation.get("accepted")), "call_count": 1, "canary": {"id": "CANARY_2_INITIAL_PLANNER_REPLACEMENT", "passed": bool(validation.get("accepted")), "receipt": "canary_2_initial_planner/controller_receipt.json"}, "call": call, "validation": validation, "anchor": anchor, "crate": crate}
    runner.write(canary_dir / "controller_receipt.json", runner.canon(receipt))
    runner.write(output / "admin_canary_v221.json", runner.canon(receipt))
    return receipt


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_v221_canary.py OUTPUT_DIR")
    result = run(Path(sys.argv[1]))
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["all_pass"] else 1)
