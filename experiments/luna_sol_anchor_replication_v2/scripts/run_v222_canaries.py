#!/usr/bin/env python3
"""Run the two unscored v2.2.2 Luna/Spark administrative canaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "run_v2.py"
spec = importlib.util.spec_from_file_location("luna_run_v222_canaries", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def git_init(root: Path) -> None:
    for command in (
        ["init", "-q"],
        ["config", "user.name", "Luna v2.2.2 Canary"],
        ["config", "user.email", "canary@example.invalid"],
        ["add", "."],
        ["commit", "-qm", "canary baseline"],
    ):
        result = runner.git(command, root)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))


def planner_canary(output: Path) -> dict[str, object]:
    canary_dir = output / "canary_2_initial_planner"
    subject = canary_dir / "subject"
    (subject / "src").mkdir(parents=True)
    (subject / "src" / "ledger_stage.py").write_text("# synthetic parser\n", encoding="utf-8", newline="\n")
    (subject / "src" / "solution.py").write_text("# synthetic rollup\n", encoding="utf-8", newline="\n")
    git_init(subject)
    packet = {
        "task_id": "admin_two_hand_canary",
        "task_packet": {
            "task_text": "Synthetic parser-to-rollup task. HAND 1 prepares src/ledger_stage.py and HAND 2 completes src/solution.py.",
            "allowed_files": ["src/ledger_stage.py", "src/solution.py"],
        },
        "visible_state_capsule": runner.state_capsule(subject),
        "public_validator_catalog": [{"id": "synthetic", "command": "controller-owned", "scope": ["src/ledger_stage.py", "src/solution.py"]}],
        "remaining_budget": {"planner_calls": 1, "spark_calls": 1},
    }
    call = runner.invoke(canary_dir / "call", subject, "gpt-5.6-luna", "high", "read-only", "planner_initial", packet, "planner_initial.schema.json")
    validation: dict[str, object] = {"accepted": False}
    anchor = crate = None
    if call.get("exit_code") == 0 and call.get("schema_valid") and not call.get("role_violations") and call.get("final_json") is not None:
        try:
            anchor, crate = runner.validate_planner(call["final_json"], "hand_1")
            anchor_sha = runner.sha_bytes(runner.canon(anchor))
            envelope = runner.controller_crate(crate, runner.tree_state(subject), anchor_sha, "admin-canary-v222", "planner_initial.schema.json", "planner_initial_base.txt")
            validation = {
                "accepted": True,
                "anchor_sha256": anchor_sha,
                "crate_sha256": runner.sha_bytes(runner.canon(envelope)),
                "parent_state_sha256": runner.tree_state(subject),
                "schema_sha256": runner.sha(runner.SCHEMAS / "planner_initial.schema.json"),
                "prompt_sha256": runner.sha(canary_dir / "call" / "prompt.txt"),
                "role_violations": [],
            }
        except runner.ControllerError as exc:
            validation = {"accepted": False, "error": exc.receipt()}
    receipt = {"interface": "LUNA_INITIAL_PLANNER_CANARY", "call": call, "validation": validation, "anchor": anchor, "crate": crate}
    runner.write(canary_dir / "controller_receipt.json", runner.canon(receipt))
    return {"id": "CANARY_2_INITIAL_PLANNER_REPLACEMENT", "passed": bool(validation.get("accepted")), "receipt": "canary_2_initial_planner/controller_receipt.json"}


def spark_crate_canary(output: Path) -> dict[str, object]:
    canary_dir = output / "canary_3_spark_crate_scope"
    subject = canary_dir / "subject"
    subject.mkdir(parents=True)
    (subject / "value.txt").write_text("0\n", encoding="utf-8", newline="\n")
    (subject / "forbidden.txt").write_text("preserve\n", encoding="utf-8", newline="\n")
    git_init(subject)
    parent_state = runner.tree_state(subject)
    crate = {
        "crate_id": "admin-canary-v222-spark-crate",
        "objective": "Change value.txt from 0 to 1 and make no other edit.",
        "allowed_paths": ["value.txt"],
        "forbidden_paths": ["forbidden.txt"],
        "dependencies": [],
        "visible_context_refs": ["synthetic_task"],
        "validator_ids": ["text"],
        "command_budget": 4,
        "wall_time_seconds": 60,
        "stop_condition": "value.txt contains exactly 1 followed by a newline",
    }
    envelope = runner.controller_crate(crate, parent_state, runner.sha_bytes(runner.canon({"objective": crate["objective"]})), "admin-canary-v222", "spark.schema.json", "spark_base.txt")
    packet = {
        "task_id": "admin_value_canary",
        "task_packet": {"task_text": "Change value.txt from 0 to 1. Do not edit forbidden.txt.", "allowed_files": ["value.txt"]},
        "visible_state_capsule": runner.state_capsule(subject),
        "hand_crate": envelope,
        "public_validator_catalog": [{"id": "text", "command": "controller-owned exact text check", "scope": ["value.txt"]}],
    }
    call = runner.invoke(canary_dir / "call", subject, "gpt-5.3-codex-spark", "low", "workspace-write", "spark", packet, "spark.schema.json")
    candidate = runner.candidate_check(subject, {"value.txt"}, parent_state, validator_ids=["text"])
    report_ok = bool(
        call.get("exit_code") == 0
        and call.get("schema_valid")
        and not call.get("role_violations")
        and call.get("final_json")
        and call["final_json"].get("crate_id") == envelope["crate_id"]
    )
    passed = bool(report_ok and candidate.get("accepted") and candidate.get("changed") == ["value.txt"] and not candidate.get("unexpected") and (subject / "forbidden.txt").read_text(encoding="utf-8") == "preserve\n")
    receipt = {"interface": "SPARK_CRATE_SCOPE_CANARY", "call": call, "crate": envelope, "candidate_validation": candidate, "report_ok": report_ok, "accepted": passed}
    runner.write(canary_dir / "controller_receipt.json", runner.canon(receipt))
    return {"id": "CANARY_3_SPARK_CRATE_SCOPE", "passed": passed, "receipt": "canary_3_spark_crate_scope/controller_receipt.json"}


def run(output: Path) -> dict[str, object]:
    try:
        cli_identity = runner.require_cli_identity()
    except runner.ControllerError as exc:
        raise SystemExit(json.dumps(exc.receipt(), sort_keys=True)) from exc
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    canaries = [planner_canary(output), spark_crate_canary(output)]
    dispatches = sorted(output.rglob("dispatch.json"))
    dispatch_cli_identities = {
        json.dumps(json.loads(path.read_text(encoding="utf-8")).get("cli_identity"), sort_keys=True)
        for path in dispatches
    }
    expected_cli_identity = json.dumps(cli_identity, sort_keys=True)
    cli_bound = len(dispatches) == 2 and dispatch_cli_identities == {expected_cli_identity}
    receipt = {
        "schema": "luna-sol-anchor-replication/live-canaries@2.2.2",
        "protocol_revision": "2.2.2",
        "call_count": 2,
        "all_pass": all(item["passed"] for item in canaries) and cli_bound,
        "canaries": canaries,
        "models": {"planner": "gpt-5.6-luna", "crate_executor": "gpt-5.3-codex-spark"},
        "cli_identity": cli_identity,
        "dispatch_count": len(dispatches),
        "dispatch_cli_identities": [json.loads(value) for value in sorted(dispatch_cli_identities)],
        "all_dispatches_bind_authorized_cli": cli_bound,
        "capability_evidence": False,
        "controller_python": {"path": str(runner.PREFERRED_PYTHON), "sha256": runner.sha(runner.PREFERRED_PYTHON)},
    }
    runner.write(output / "admin_canary_v222.json", runner.canon(receipt))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    value = run(parser.parse_args().output)
    print(json.dumps(value, indent=2, sort_keys=True))
    raise SystemExit(0 if value["all_pass"] else 1)
