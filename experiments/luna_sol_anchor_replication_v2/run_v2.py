#!/usr/bin/env python3
"""Execute, seal, grade, and report the frozen Luna/Sol v2 episode."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
TASK = ROOT / "task"
VISIBLE = TASK / "subject_bundle"
PRIVATE = TASK / "private"
PROMPTS = ROOT / "prompts"
SCHEMAS = PROMPTS / "schemas"
CLI = Path(r"C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\3135b80b111fd431\codex.exe")
EXPERIMENT_TAG = "LUNA_SOL_ANCHOR_REPLICATION_V2"

def canon(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())

def write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode() if isinstance(data, str) else data
    path.write_bytes(raw.replace(b"\r\n", b"\n"))

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run(cmd: list[str], cwd: Path, timeout: int = 120, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, cwd=cwd, input=input_bytes, capture_output=True, timeout=timeout)

def git(cmd: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    return run(["git", *cmd], cwd, timeout)

def tree_state(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return h.hexdigest()

def files_manifest(root: Path) -> list[dict[str, str]]:
    return [{"path": p.relative_to(root).as_posix(), "sha256": sha(p)} for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.parts]

def initialize_subject(destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(VISIBLE, destination)
    result = git(["init", "-q"], destination)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    for key, value in [("user.name", "Luna Sol Replication Controller"), ("user.email", "controller@example.invalid")]:
        git(["config", key, value], destination)
    git(["add", "."], destination)
    result = git(["commit", "-qm", "subject bundle freeze"], destination)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))

def status_paths(root: Path) -> list[str]:
    result = git(["status", "--porcelain=v1", "--untracked-files=all"], root)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    paths = []
    for line in result.stdout.decode().splitlines():
        if not line:
            continue
        value = line[3:] if len(line) > 3 else ""
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(value.replace("\\", "/"))
    return paths

def visible_check(root: Path) -> dict[str, Any]:
    result = run([sys.executable, "run_visible.py"], root, 120)
    return {"command": [sys.executable, "run_visible.py"], "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "passed": result.returncode == 0}

def candidate_check(root: Path, allowed: set[str]) -> dict[str, Any]:
    changed = status_paths(root)
    unexpected = sorted(set(changed) - allowed)
    visible = visible_check(root)
    return {"changed": changed, "unexpected": unexpected, "visible": visible, "accepted": not unexpected and visible["passed"]}

def public_catalog() -> list[dict[str, Any]]:
    return [{"id": "stage", "command": "python src/ledger_stage.py <input> <normalized>", "scope": ["src/ledger_stage.py", "data/normalized_ledger.json"]}, {"id": "visible", "command": "python run_visible.py", "scope": ["src/ledger_stage.py", "src/solution.py", "data/normalized_ledger.json"]}]

def task_packet() -> dict[str, Any]:
    return json.loads((TASK / "task_packet.json").read_text(encoding="utf-8"))

def state_capsule(root: Path) -> dict[str, Any]:
    return {"state_sha256": tree_state(root), "files": files_manifest(root), "status_paths": status_paths(root)}

def extract_usage(stdout: bytes) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for line in stdout.decode(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
        if event.get("type") == "event_msg" and (event.get("payload") or {}).get("type") == "token_count":
            usage = ((event.get("payload") or {}).get("info") or {}).get("total_token_usage") or usage
    return usage

def has_role_violation(stdout: bytes) -> list[str]:
    violations = []
    for line in stdout.decode(errors="replace").splitlines():
        try: event = json.loads(line)
        except json.JSONDecodeError: continue
        blob = json.dumps(event, sort_keys=True).lower()
        if "subagent" in blob or "spawn_agent" in blob or "mcp" in blob:
            violations.append("forbidden agent or MCP event")
    return sorted(set(violations))

def invoke(call_dir: Path, cwd: Path, model: str, effort: str, sandbox: str, base_name: str, packet: dict[str, Any], schema_name: str) -> dict[str, Any]:
    call_dir.mkdir(parents=True, exist_ok=True)
    base = (PROMPTS / f"{base_name}_base.txt").read_bytes()
    packet_bytes = canon(packet)
    prompt = base + b"\nINPUT_PACKET_JSON_BEGIN\n" + packet_bytes + b"INPUT_PACKET_JSON_END\n"
    prompt_path = call_dir / "prompt.txt"; write(prompt_path, prompt)
    schema_path = SCHEMAS / schema_name
    final_path = call_dir / "final.json"
    command = [str(CLI), "exec", "--model", model, "--sandbox", sandbox, "--ephemeral", "--json", "--output-last-message", str(final_path), "--output-schema", str(schema_path), "--config", f'model_reasoning_effort="{effort}"', "--config", 'model_reasoning_summary="none"', "--config", "model_supports_reasoning_summaries=false", "--config", 'web_search="disabled"', "--config", "sandbox_workspace_write.network_access=false", "--config", "agents.max_depth=0", "--config", "agents.max_threads=1", "--config", 'history.persistence="none"', "--config", "hide_agent_reasoning=true", "--config", 'approval_policy="never"', "-C", str(cwd), "-"]
    dispatch = {"started_at": now(), "model": model, "effort": effort, "sandbox": sandbox, "cwd": str(cwd), "command": command, "prompt_sha256": sha(prompt_path), "schema_sha256": sha(schema_path), "schema": schema_name}
    write(call_dir / "dispatch.json", canon(dispatch))
    started = time.time()
    try:
        result = subprocess.run(command, cwd=cwd, input=prompt, capture_output=True, timeout=900)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(command, 124, exc.stdout or b"", exc.stderr or b"")
        timed_out = True
    write(call_dir / "events.jsonl", result.stdout)
    write(call_dir / "stderr.txt", result.stderr)
    final_bytes = final_path.read_bytes() if final_path.is_file() else b""
    if not final_bytes:
        for line in result.stdout.splitlines()[::-1]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") in {"message", "assistant_message"} and event.get("text"):
                final_bytes = str(event["text"]).encode(); break
    if final_bytes:
        write(call_dir / "final_response.txt", final_bytes)
    receipt = {"completed_at": now(), "duration_seconds": round(time.time() - started, 3), "exit_code": result.returncode, "timed_out": timed_out, "stdout_sha256": sha(call_dir / "events.jsonl"), "stderr_sha256": sha(call_dir / "stderr.txt"), "final_response_sha256": sha_bytes(final_bytes), "usage": extract_usage(result.stdout), "role_violations": has_role_violation(result.stdout), "final_present": bool(final_bytes)}
    write(call_dir / "completion.json", canon(receipt))
    try: receipt["final_json"] = json.loads(final_bytes.decode())
    except Exception: receipt["final_json"] = None
    return receipt

def require_keys(value: Any, keys: list[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} keys invalid: {sorted(value) if isinstance(value, dict) else type(value)}")

def validate_full(response: dict[str, Any]) -> None:
    required = ["status", "summary", "files_inspected", "files_changed", "commands", "visible_validators", "unresolved_blockers", "final_state_claim"]
    require_keys(response, required, "full response")
    if response["status"] != "completed" or response["unresolved_blockers"]:
        raise ValueError("full agent did not complete")

def validate_crate(crate: dict[str, Any], parent_state: str, task_id: str, trial_id: str) -> None:
    required = ["crate_id", "task_id", "trial_id", "parent_state_sha256", "anchor_sha256", "objective", "allowed_paths", "forbidden_paths", "dependencies", "visible_context_refs", "validator_ids", "command_budget", "wall_time_seconds", "required_receipt_schema_sha256", "stop_condition"]
    require_keys(crate, required, "crate")
    if crate["task_id"] != task_id or crate["trial_id"] != trial_id or crate["parent_state_sha256"] != parent_state:
        raise ValueError("crate lineage mismatch")
    if not set(crate["allowed_paths"]).issubset({"src/ledger_stage.py", "src/solution.py", "data/normalized_ledger.json"}):
        raise ValueError("crate path scope escaped")

def validate_anchor(anchor: dict[str, Any], task_id: str, trial_id: str) -> None:
    required = ["parent_anchor_sha256", "task_id", "trial_id", "objective", "invariants", "decisions", "accepted_state", "work_graph", "open_risks", "remaining_budget", "stop_condition"]
    require_keys(anchor, required, "anchor")
    if anchor["task_id"] != task_id or anchor["trial_id"] != trial_id:
        raise ValueError("anchor lineage mismatch")

def validate_planner(response: dict[str, Any], parent_state: str, task_id: str, trial_id: str, initial: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    required = ["action", "anchor_patch", "work_graph", "crate", "decision_record", "remaining_budget", "stop_reason"]
    require_keys(response, required, "planner response")
    if response["action"] != "spawn" or not response["anchor_patch"] or not response["crate"]:
        raise ValueError("planner did not spawn")
    anchor = response["anchor_patch"]; crate = response["crate"]
    validate_anchor(anchor, task_id, trial_id)
    validate_crate(crate, parent_state, task_id, trial_id)
    if initial and anchor["parent_anchor_sha256"] is not None:
        raise ValueError("initial anchor parent must be null")
    return anchor, crate

def validate_spark(response: dict[str, Any], parent_state: str, crate: dict[str, Any]) -> None:
    required = ["status", "crate_id", "parent_state_sha256", "files_inspected", "files_changed", "commands", "visible_validators", "evidence", "unresolved_blockers", "patch_sha256", "resulting_state_sha256", "summary"]
    require_keys(response, required, "spark response")
    if response["status"] != "completed" or response["crate_id"] != crate["crate_id"] or response["parent_state_sha256"] != parent_state:
        raise ValueError("spark lineage/status mismatch")
    if response["unresolved_blockers"]:
        raise ValueError("spark reported blocker")

def run_full(run_dir: Path, trial: str, arm: str, model: str, effort: str, order: int, packet: dict[str, Any]) -> dict[str, Any]:
    subject = run_dir / trial / arm / "subject"; initialize_subject(subject)
    call = invoke(run_dir / trial / arm / "call", subject, model, effort, "workspace-write", "full_agent", packet, "full_agent.schema.json")
    outcome = {"call": call}
    if call["final_json"] is not None:
        try: validate_full(call["final_json"]); outcome["validation"] = candidate_check(subject, {"src/ledger_stage.py", "src/solution.py", "data/normalized_ledger.json"})
        except Exception as exc: outcome["validation"] = {"accepted": False, "error": str(exc), "changed": status_paths(subject)}
    else: outcome["validation"] = {"accepted": False, "error": "no final JSON", "changed": status_paths(subject)}
    outcome["candidate"] = str(subject) if outcome["validation"].get("accepted") else None
    write(run_dir / trial / arm / "outcome.json", canon(outcome))
    return outcome

def copy_state(source: Path, destination: Path) -> None:
    if destination.exists(): raise FileExistsError(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git"))
    initialize_git = git(["init", "-q"], destination)
    if initialize_git.returncode: raise RuntimeError(initialize_git.stderr.decode(errors="replace"))
    for key, value in [("user.name", "Luna Sol Replication Controller"), ("user.email", "controller@example.invalid")]: git(["config", key, value], destination)
    git(["add", "."], destination); result = git(["commit", "-qm", "accepted state"], destination)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace"))

def apply_hand(base: Path, work: Path, destination: Path, allowed: set[str], call_outcome: dict[str, Any]) -> dict[str, Any]:
    response = call_outcome.get("final_json")
    if not response: raise ValueError("missing Spark receipt")
    validate_spark(response, tree_state(base), call_outcome["crate"])
    changed = status_paths(work); unexpected = sorted(set(changed) - allowed)
    if unexpected: raise ValueError(f"changed paths outside crate: {unexpected}")
    patch = git(["diff", "--binary", "--no-ext-diff"], work)
    if patch.returncode: raise RuntimeError(patch.stderr.decode(errors="replace"))
    if response["patch_sha256"] is not None and response["patch_sha256"] != sha_bytes(patch.stdout): raise ValueError("Spark patch hash mismatch")
    copy_state(base, destination)
    if patch.stdout:
        result = run(["git", "apply", "--binary", "-"], destination, input_bytes=patch.stdout)
        if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace"))
    for relative in [p for p in changed if p == "data/normalized_ledger.json"]:
        source_file = work / relative; target_file = destination / relative
        target_file.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source_file, target_file)
    return {"patch_sha256": sha_bytes(patch.stdout), "resulting_state_sha256": tree_state(destination), "changed": changed, "response": response}

def run_hand(run_dir: Path, trial: str, arm: str, phase: str, model: str, effort: str, sandbox: str, subject: Path, crate: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    packet = dict(packet); packet["hand_crate"] = crate
    call = invoke(run_dir / trial / arm / phase / "call", subject, model, effort, sandbox, "spark", packet, "spark.schema.json")
    call["crate"] = crate
    write(run_dir / trial / arm / phase / "outcome.json", canon(call))
    return call

def run_chain(run_dir: Path, trial: str, order: int, no_anchor: bool, packet_base: dict[str, Any]) -> dict[str, Any]:
    arm = "luna_spark_no_anchor" if no_anchor else "luna_spark_correct_anchor"
    prelude = run_dir / trial / "split_prelude"; base = prelude / "base"; initialize_subject(base)
    initial_packet = {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(base), "public_validator_catalog": public_catalog(), "remaining_budget": {"planner_calls": 3, "spark_calls": 3}}
    first = invoke(prelude / "planner_initial" / "call", base, "gpt-5.6-luna", "high", "read-only", "planner", initial_packet, "planner.schema.json")
    result: dict[str, Any] = {"planner_initial": first}
    try:
        anchor, crate1 = validate_planner(first["final_json"], tree_state(base), "derived_ledger_rollup_v2", trial, True)
        hand1_work = prelude / "spark_hand_1" / "work"; copy_state(base, hand1_work)
        hand1 = run_hand(run_dir, trial, "split_prelude", "spark_hand_1", "gpt-5.3-codex-spark", "low", "workspace-write", hand1_work, crate1, {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(hand1_work), "public_validator_catalog": public_catalog()})
        result["spark_hand_1"] = hand1
        accepted1 = prelude / "accepted_state"; result["accepted_hand_1"] = apply_hand(base, hand1_work, accepted1, {"src/ledger_stage.py", "data/normalized_ledger.json"}, hand1)
        fork = run_dir / trial / arm; continuation_packet = {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(accepted1), "accepted_hand_1_receipt": hand1["final_json"], "public_validator_catalog": public_catalog(), "remaining_budget": {"planner_calls": 2, "spark_calls": 2}}
        if not no_anchor: continuation_packet["current_anchor"] = anchor
        cont = invoke(fork / "planner_continuation" / "call", accepted1, "gpt-5.6-luna", "high", "read-only", "planner", continuation_packet, "planner.schema.json")
        result["planner_continuation"] = cont
        anchor2, crate2 = validate_planner(cont["final_json"], tree_state(accepted1), "derived_ledger_rollup_v2", trial, False)
        hand2_work = fork / "spark_hand_2" / "work"; copy_state(accepted1, hand2_work)
        hand2 = run_hand(run_dir, trial, arm, "spark_hand_2", "gpt-5.3-codex-spark", "low", "workspace-write", hand2_work, crate2, {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(hand2_work), "accepted_hand_1_receipt": hand1["final_json"], "public_validator_catalog": public_catalog()})
        result["spark_hand_2"] = hand2
        final = fork / "final_candidate"; result["final"] = apply_hand(accepted1, hand2_work, final, {"src/solution.py", "data/normalized_ledger.json"}, hand2)
        check = candidate_check(final, {"src/ledger_stage.py", "src/solution.py", "data/normalized_ledger.json"}); result["validation"] = check; result["candidate"] = str(final) if check["accepted"] else None
    except Exception as exc:
        result["error"] = str(exc); result["candidate"] = None
    write(run_dir / trial / arm / "outcome.json", canon(result))
    return result

def grade_candidate(candidate: str | None, out_dir: Path) -> dict[str, Any]:
    if not candidate: return {"outcome": "NOT_RUN_NO_CANDIDATE"}
    source = Path(candidate)
    sealed_state = tree_state(source)
    grading_copy = out_dir / "external_grading_copy"
    shutil.copytree(source, grading_copy, ignore=shutil.ignore_patterns(".git"))
    result = run([sys.executable, str(PRIVATE / "hidden_grader.py"), str(grading_copy)], ROOT, 180)
    receipt = {"outcome": "pass" if result.returncode == 0 else "fail", "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "candidate_state_sha256": sealed_state, "candidate_state_sha256_after": tree_state(source), "grading_copy_state_sha256": tree_state(grading_copy)}
    if receipt["candidate_state_sha256"] != receipt["candidate_state_sha256_after"]:
        raise RuntimeError("hidden grading mutated sealed candidate")
    write(out_dir / "hidden_grade.json", canon(receipt)); return receipt

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--suite-commit", required=True); parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    if not CLI.is_file(): raise SystemExit("missing pinned CLI")
    if not (TASK / "oracle_self_test.json").is_file(): raise SystemExit("oracle self-test receipt missing")
    oracle = json.loads((TASK / "oracle_self_test.json").read_text());
    if oracle.get("tests", {}).get("mutants") != "all_fail": raise SystemExit("oracle self-test did not pass")
    if args.run_root is None: args.run_root = ROOT / "run" / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = args.run_root.resolve(); run_dir.mkdir(parents=True, exist_ok=False)
    models = json.loads(subprocess.run([str(CLI), "debug", "models"], capture_output=True, check=True).stdout)
    model_catalog_bytes = canon(models)
    task_hash = sha(TASK / "task_packet.json"); seed = sha_bytes((args.suite_commit + task_hash + EXPERIMENT_TAG).encode()); rng = random.Random(int(seed[:16], 16))
    schedule = {"seed": seed, "replicates": []}
    for i in range(1, 4): schedule["replicates"].append({"trial_id": f"replicate_{i:03d}", "full_order": ["SOL_FULL", "LUNA_FULL"] if rng.randrange(2) == 0 else ["LUNA_FULL", "SOL_FULL"], "fork_order": ["LUNA_SPARK_CORRECT_ANCHOR", "LUNA_SPARK_NO_ANCHOR"] if rng.randrange(2) == 0 else ["LUNA_SPARK_NO_ANCHOR", "LUNA_SPARK_CORRECT_ANCHOR"]})
    write(run_dir / "schedule.json", canon(schedule)); write(run_dir / "model_catalog.json", model_catalog_bytes)
    manifest = {"schema": "luna-sol-anchor-replication/run-manifest@2", "created_at": now(), "suite_commit": args.suite_commit, "branch": "codex/luna-sol-anchor-replication-v2", "cli_path": str(CLI), "cli_sha256": sha(CLI), "cli_version": subprocess.run([str(CLI), "--version"], capture_output=True, check=True).stdout.decode().strip(), "model_catalog_sha256": sha(run_dir / "model_catalog.json"), "task_packet_sha256": task_hash, "hidden_grader_sha256": sha(PRIVATE / "hidden_grader.py"), "visible_bundle_sha256": json.loads((TASK / "oracle_self_test.json").read_text())["build"]["visible_bundle_sha256"], "prompt_hashes": {p.name: sha(p) for p in PROMPTS.glob("*.txt")}, "schema_hashes": {p.name: sha(p) for p in SCHEMAS.glob("*.json")}, "k": 3, "schedule_seed": seed, "frozen": True, "stopping_rules": json.loads((TASK / "preregistration.json").read_text())["stopping_rules"]}
    write(run_dir / "manifest.json", canon(manifest))
    packet_full = {"task_id": "derived_ledger_rollup_v2", "task_packet": task_packet(), "public_validator_catalog": public_catalog(), "instruction": "Complete the visible task in this isolated repository."}
    arms: dict[str, Any] = {}
    for item in schedule["replicates"]:
        trial = item["trial_id"]; arms[trial] = {}
        for arm in item["full_order"]:
            model = "gpt-5.6-sol" if arm == "SOL_FULL" else "gpt-5.6-luna"
            arms[trial][arm] = run_full(run_dir, trial, arm.lower(), model, "high", 0, packet_full)
        for arm in item["fork_order"]:
            no_anchor = arm == "LUNA_SPARK_NO_ANCHOR"; arms[trial][arm] = run_chain(run_dir, trial, 0, no_anchor, packet_full)
    for trial, trial_arms in arms.items():
        for arm, outcome in trial_arms.items():
            grade_dir = run_dir / trial / arm
            outcome["hidden_grade"] = grade_candidate(outcome.get("candidate"), grade_dir)
    table = []
    for trial, trial_arms in arms.items():
        for arm, outcome in trial_arms.items(): table.append({"trial": trial, "arm": arm, "hidden_outcome": outcome.get("hidden_grade", {}).get("outcome"), "candidate": bool(outcome.get("candidate")), "error": outcome.get("error")})
    sol = [x for x in table if x["arm"] == "SOL_FULL" and x["hidden_outcome"] == "pass"]
    anchor = [x for x in table if x["arm"] == "LUNA_SPARK_CORRECT_ANCHOR" and x["hidden_outcome"] == "pass"]
    no_anchor = [x for x in table if x["arm"] == "LUNA_SPARK_NO_ANCHOR" and x["hidden_outcome"] == "pass"]
    comparison = {"schema": "luna-sol-anchor-replication/comparison@2", "table": table, "sol_replication_verdict": "SOL_LEVEL_REPLICATED_ON_FROZEN_TASK" if len(sol) == 3 and len(anchor) == 3 else "TASK_NON_INFORMATIVE_FOR_SOL_REPLICATION" if len(sol) != 3 else "NOT_REPLICATED", "anchor_mechanism_verdict": "ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK" if len(anchor) > len(no_anchor) and sum(1 for a, n in zip(sorted(anchor, key=lambda x:x["trial"]), sorted(no_anchor, key=lambda x:x["trial"])) if a["hidden_outcome"] == "pass" and n["hidden_outcome"] != "pass") >= 2 else "NO_ANCHOR_MECHANISM_IDENTIFIED", "counts": {"sol_full_pass": len(sol), "correct_anchor_pass": len(anchor), "no_anchor_pass": len(no_anchor)}}
    write(run_dir / "comparison.json", canon(comparison))
    report = "# Luna/Sol Anchor Replication v2\n\n" + f"suite_commit: `{args.suite_commit}`\nexperiment_run: `{run_dir.name}`\n\n" + "| Replicate | Arm | Hidden outcome | Candidate |\n|---|---|---|---|\n" + "\n".join(f"| {x['trial']} | {x['arm']} | {x['hidden_outcome']} | {x['candidate']} |" for x in table) + "\n\n" + f"Sol replication verdict: **{comparison['sol_replication_verdict']}**\n\nAnchor mechanism verdict: **{comparison['anchor_mechanism_verdict']}**\n\nNarrow claim: this report supports only the preregistered behavior on `derived_ledger_rollup_v2` with the sealed custody records in this run.\n"
    write(run_dir / "report.md", report); write(run_dir / "collection_receipt.json", canon({"schema": "luna-sol-anchor-replication/collection@2", "completed_at": now(), "manifest_sha256": sha(run_dir / "manifest.json"), "schedule_sha256": sha(run_dir / "schedule.json"), "comparison_sha256": sha(run_dir / "comparison.json"), "report_sha256": sha(run_dir / "report.md"), "calls": sum(1 for _ in run_dir.rglob("dispatch.json"))}))
    print(json.dumps({"run_root": str(run_dir), "comparison": comparison}, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
