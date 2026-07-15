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
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(ROOT.parents[1] / "scripts"))
from validate_strict_output_schemas import validate_instance, validate_schema  # noqa: E402
TASK = ROOT / "task"
VISIBLE = TASK / "subject_bundle"
PRIVATE = TASK / "private"
PROMPTS = ROOT / "prompts"
SCHEMAS = PROMPTS / "schemas"
CLI = Path(r"C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\3135b80b111fd431\codex.exe")
PREFERRED_PYTHON = Path(r"C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
EXPERIMENT_TAG = "LUNA_SOL_ANCHOR_REPLICATION_V2"

class ControllerError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str, path: str | None = None):
        self.code, self.stage, self.message, self.path = code, stage, message, path
        super().__init__(message)

    def receipt(self) -> dict[str, Any]:
        value = {"code": self.code, "stage": self.stage, "message": self.message}
        if self.path is not None:
            value["path"] = self.path
        return value

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

def visible_check(root: Path, interpreter: Path = PREFERRED_PYTHON) -> dict[str, Any]:
    if not interpreter.is_file():
        raise ControllerError("VISIBLE_VALIDATOR_INTERPRETER_MISSING", "visible_validation", "controller-owned Python interpreter is unavailable", str(interpreter))
    result = run([str(interpreter), "run_visible.py"], root, 120)
    return {"command": [str(interpreter), "run_visible.py"], "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "passed": result.returncode == 0}

def stage_check(root: Path, interpreter: Path = PREFERRED_PYTHON) -> dict[str, Any]:
    if not interpreter.is_file():
        raise ControllerError("VISIBLE_VALIDATOR_INTERPRETER_MISSING", "visible_validation", "controller-owned Python interpreter is unavailable", str(interpreter))
    with tempfile.TemporaryDirectory(prefix="luna-stage-check-") as temp:
        output = Path(temp) / "normalized.json"
        result = run([str(interpreter), "src/ledger_stage.py", "data/sample_ledger.json", str(output)], root, 120)
        return {"command": [str(interpreter), "src/ledger_stage.py", "data/sample_ledger.json", str(output)], "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "passed": result.returncode == 0 and output.is_file()}

def text_check(root: Path) -> dict[str, Any]:
    value = root / "value.txt"
    passed = value.is_file() and value.read_text(encoding="utf-8") == "1\n"
    return {"command": ["controller-text-validator", "value.txt == 1"], "returncode": 0 if passed else 1, "stdout": "TEXT_OK\n" if passed else "", "stderr": "" if passed else "value.txt was not exactly 1", "passed": passed}

def candidate_check(root: Path, allowed: set[str], parent_state: str | None = None, interpreter: Path = PREFERRED_PYTHON, validator_ids: list[str] | None = None) -> dict[str, Any]:
    changed = status_paths(root)
    unexpected = sorted(set(changed) - allowed)
    patch = git(["diff", "--binary", "--no-ext-diff", "--no-color"], root)
    if patch.returncode:
        raise ControllerError("PATCH_DERIVATION_FAILED", "patch_derivation", patch.stderr.decode(errors="replace"))
    result: dict[str, Any] = {"changed": changed, "unexpected": unexpected, "patch_sha256": sha_bytes(patch.stdout), "state_sha256": tree_state(root), "parent_state_sha256": parent_state}
    if not changed:
        result.update({"disposition": "NO_CANDIDATE_NO_DIFF", "accepted": False})
        return result
    if unexpected:
        result.update({"disposition": "REJECTED_PATH_VIOLATION", "accepted": False})
        return result
    validators = validator_ids or ["visible"]
    result["visible_validators"] = {name: (stage_check(root, interpreter) if name == "stage" else text_check(root) if name == "text" else visible_check(root, interpreter)) for name in validators}
    result["accepted"] = all(item["passed"] for item in result["visible_validators"].values())
    result["disposition"] = "CANDIDATE_ADMITTED" if result["accepted"] else "REJECTED_VISIBLE_VALIDATOR_FAILURE"
    return result

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

Executor = Callable[[list[str], Path, bytes, Path], subprocess.CompletedProcess[bytes]]

def invoke(call_dir: Path, cwd: Path, model: str, effort: str, sandbox: str, base_name: str, packet: dict[str, Any], schema_name: str, executor: Executor | None = None) -> dict[str, Any]:
    call_dir.mkdir(parents=True, exist_ok=True)
    base = (PROMPTS / f"{base_name}_base.txt").read_bytes()
    packet_bytes = canon(packet)
    prompt = base + b"\nINPUT_PACKET_JSON_BEGIN\n" + packet_bytes + b"INPUT_PACKET_JSON_END\n"
    prompt_path = call_dir / "prompt.txt"; write(prompt_path, prompt)
    schema_path = SCHEMAS / schema_name
    final_path = call_dir / "final.json"
    command = [str(CLI), "exec", "--model", model, "--sandbox", sandbox, "--ephemeral", "--json", "--output-last-message", str(final_path), "--output-schema", str(schema_path), "--config", f'model_reasoning_effort="{effort}"', "--config", 'model_reasoning_summary="none"', "--config", "model_supports_reasoning_summaries=false", "--config", 'web_search="disabled"', "--config", "sandbox_workspace_write.network_access=false", "--config", "agents.max_depth=1", "--config", "agents.max_threads=1", "--config", 'history.persistence="none"', "--config", "hide_agent_reasoning=true", "--config", 'approval_policy="never"', "-C", str(cwd), "-"]
    dispatch = {"started_at": now(), "model": model, "effort": effort, "sandbox": sandbox, "cwd": str(cwd), "command": command, "prompt_sha256": sha(prompt_path), "schema_sha256": sha(schema_path), "schema": schema_name}
    write(call_dir / "dispatch.json", canon(dispatch))
    started = time.time()
    try:
        result = executor(command, cwd, prompt, final_path) if executor else subprocess.run(command, cwd=cwd, input=prompt, capture_output=True, timeout=900)
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
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    receipt["schema_errors"] = validate_schema(schema_doc, str(schema_path))
    receipt["instance_errors"] = validate_instance(receipt["final_json"], schema_doc) if receipt["final_json"] is not None else ["no final JSON"]
    receipt["schema_valid"] = not receipt["schema_errors"] and not receipt["instance_errors"]
    return receipt

def require_keys(value: Any, keys: list[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} keys invalid: {sorted(value) if isinstance(value, dict) else type(value)}")

def validate_full(response: dict[str, Any]) -> None:
    require_keys(response, ["summary", "files_inspected_claimed", "files_changed_claimed", "commands_claimed", "unresolved_blockers"], "full advisory report")

def validate_crate(crate: dict[str, Any], phase: str) -> None:
    require_keys(crate, ["crate_id", "objective", "allowed_paths", "forbidden_paths", "dependencies", "visible_context_refs", "validator_ids", "command_budget", "wall_time_seconds", "stop_condition"], f"{phase} crate")
    allowed = set(crate["allowed_paths"])
    forbidden = set(crate["forbidden_paths"])
    if phase == "hand_1" and (not allowed or not allowed.issubset({"src/ledger_stage.py"}) or "src/solution.py" not in forbidden):
        raise ControllerError("PRELUDE_HAND1_CRATE_INVALID", "planner_validation", "HAND 1 must be restricted to the normalization module and forbid src/solution.py")
    if phase == "hand_2" and (allowed != {"src/solution.py"} or "src/ledger_stage.py" not in forbidden):
        raise ControllerError("CONTINUATION_HAND2_CRATE_INVALID", "planner_validation", "HAND 2 must be restricted to src/solution.py and forbid the HAND 1 module")

def validate_anchor(anchor: dict[str, Any], phase: str) -> None:
    require_keys(anchor, ["objective", "invariants", "decisions", "open_risks", "stop_condition"], f"{phase} anchor")

def validate_planner(response: dict[str, Any], phase: str) -> tuple[dict[str, Any], dict[str, Any]]:
    action = "spawn_hand_1" if phase == "hand_1" else "spawn_hand_2"
    require_keys(response, ["action", "anchor_state", "work_graph", "crate", "decision_record"], "planner response") if phase == "hand_1" else require_keys(response, ["action", "anchor_state", "crate"], "planner response")
    if response["action"] != action or not response["anchor_state"] or not response["crate"]:
        raise ControllerError("PLANNER_SCHEMA_POLICY_REJECTED", "planner_validation", f"planner did not return {action} with non-null anchor and crate")
    if phase == "hand_1" and (len(response["work_graph"]) != 2 or response["work_graph"][0]["node_id"] == response["work_graph"][1]["node_id"]):
        raise ControllerError("PRELUDE_PLANNER_WORK_GRAPH_INVALID", "planner_validation", "initial planner must define exactly two distinct hand nodes")
    validate_anchor(response["anchor_state"], phase)
    validate_crate(response["crate"], phase)
    return response["anchor_state"], response["crate"]

def validate_spark(response: dict[str, Any], parent_state: str, crate: dict[str, Any]) -> None:
    require_keys(response, ["crate_id", "summary", "files_inspected_claimed", "files_changed_claimed", "commands_claimed", "unresolved_blockers"], "spark advisory report")
    if response["crate_id"] != crate["crate_id"]:
        raise ControllerError("SPARK_CRATE_ECHO_MISMATCH", "spark_report_validation", "Spark crate id echo did not match controller crate")

def run_full(run_dir: Path, trial: str, arm: str, model: str, effort: str, order: int, packet: dict[str, Any], executor: Executor | None = None, interpreter: Path = PREFERRED_PYTHON) -> dict[str, Any]:
    subject = run_dir / trial / arm / "subject"; initialize_subject(subject)
    parent_state = tree_state(subject)
    call = invoke(run_dir / trial / arm / "call", subject, model, effort, "workspace-write", "full_agent", packet, "full_agent.schema.json", executor)
    outcome = {"call": call}
    try:
        if call["final_json"] is None:
            raise ControllerError("ADVISORY_REPORT_MISSING", "advisory_report_validation", "no final advisory report JSON")
        validate_full(call["final_json"])
        outcome["validation"] = candidate_check(subject, {"src/ledger_stage.py", "src/solution.py", "data/normalized_ledger.json"}, parent_state, interpreter)
        if outcome["validation"].get("accepted"):
            outcome["candidate"] = str(subject)
        else:
            outcome["candidate"] = None
    except ControllerError as exc:
        outcome["validation"] = {"accepted": False, "disposition": "REJECTED_CONTROLLER_ERROR", "error": exc.receipt(), "changed": status_paths(subject)}
        outcome["candidate"] = None
    except Exception as exc:
        outcome["validation"] = {"accepted": False, "disposition": "REJECTED_CONTROLLER_ERROR", "error": {"code": "CONTROLLER_VALIDATION_ERROR", "stage": "candidate_admission", "message": str(exc)}, "changed": status_paths(subject)}
        outcome["candidate"] = None
    seal_final_receipt(run_dir, trial, arm, outcome)
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

def apply_hand(base: Path, work: Path, destination: Path, allowed: set[str], call_outcome: dict[str, Any], interpreter: Path = PREFERRED_PYTHON) -> dict[str, Any]:
    response = call_outcome.get("final_json")
    if not response:
        raise ControllerError("SPARK_ADVISORY_REPORT_MISSING", "spark_report_validation", "no final Spark advisory report JSON")
    validate_spark(response, tree_state(base), call_outcome["crate"])
    admission = candidate_check(work, allowed, tree_state(base), interpreter, ["stage"] if allowed == {"src/ledger_stage.py"} else ["visible"])
    if admission.get("disposition") == "NO_CANDIDATE_NO_DIFF":
        raise ControllerError("PRELUDE_HAND1_NO_DIFF" if allowed == {"src/ledger_stage.py"} else "HAND2_NO_DIFF", "candidate_admission", "Spark produced no in-scope diff")
    if admission.get("unexpected"):
        raise ControllerError("PRELUDE_HAND1_PATH_VIOLATION" if allowed == {"src/ledger_stage.py"} else "HAND2_PATH_VIOLATION", "path_bounds", "Spark changed paths outside its crate", ",".join(admission["unexpected"]))
    if not admission.get("accepted"):
        raise ControllerError("PRELUDE_HAND1_VISIBLE_VALIDATOR_FAILURE" if allowed == {"src/ledger_stage.py"} else "HAND2_VISIBLE_VALIDATOR_FAILURE", "visible_validation", "controller-owned visible validator failed")
    patch = git(["diff", "--binary", "--no-ext-diff"], work)
    if patch.returncode: raise RuntimeError(patch.stderr.decode(errors="replace"))
    copy_state(base, destination)
    if patch.stdout:
        result = run(["git", "apply", "--binary", "-"], destination, input_bytes=patch.stdout)
        if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace"))
    for relative in [p for p in admission["changed"] if p == "data/normalized_ledger.json"]:
        source_file = work / relative; target_file = destination / relative
        target_file.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source_file, target_file)
    return {"patch_sha256": sha_bytes(patch.stdout), "resulting_state_sha256": tree_state(destination), "changed": admission["changed"], "visible_validators": admission["visible_validators"], "response": response}

def run_hand(run_dir: Path, trial: str, arm: str, phase: str, model: str, effort: str, sandbox: str, subject: Path, crate: dict[str, Any], packet: dict[str, Any], executor: Executor | None = None) -> dict[str, Any]:
    packet = dict(packet); packet["hand_crate"] = crate
    call = invoke(run_dir / trial / arm / phase / "call", subject, model, effort, sandbox, "spark", packet, "spark.schema.json", executor)
    call["crate"] = crate
    write(run_dir / trial / arm / phase / "outcome.json", canon(call))
    return call

def controller_crate(crate: dict[str, Any], parent_state: str, anchor_sha: str, trial: str, schema_name: str) -> dict[str, Any]:
    value = dict(crate)
    value.update({"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "parent_state_sha256": parent_state, "anchor_sha256": anchor_sha, "required_receipt_schema_sha256": sha(SCHEMAS / "spark.schema.json"), "schema_sha256": sha(SCHEMAS / schema_name), "prompt_sha256": sha(PROMPTS / "planner_base.txt")})
    return value

def create_fork(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ControllerError("FORK_DESTINATION_EXISTS", "fork_creation", "fork destination already exists; refusing reuse or overwrite", str(destination))
    if destination.resolve() == source.resolve():
        raise ControllerError("FORK_SOURCE_EQUALS_DESTINATION", "fork_creation", "fork source and destination must be distinct")
    copy_state(source, destination)

def seal_final_receipt(run_dir: Path, trial: str, arm: str, outcome: dict[str, Any]) -> dict[str, Any]:
    validation = outcome.get("validation") or outcome.get("final") or {}
    receipt = {"trial": trial, "arm": arm, "candidate": outcome.get("candidate"), "disposition": outcome.get("disposition") or validation.get("disposition") or ("CANDIDATE_ADMITTED" if outcome.get("candidate") else "NOT_RUN_NO_CANDIDATE"), "patch_sha256": validation.get("patch_sha256"), "state_sha256": validation.get("state_sha256") or validation.get("resulting_state_sha256"), "hidden_grade": (outcome.get("hidden_grade") or {}).get("outcome", "NOT_RUN")}
    write(run_dir / trial / arm / "final_receipt.json", canon(receipt))
    return receipt

def run_chain(run_dir: Path, trial: str, order: int, no_anchor: bool, packet_base: dict[str, Any], executor: Executor | None = None, interpreter: Path = PREFERRED_PYTHON) -> dict[str, Any]:
    arm = "luna_spark_no_anchor" if no_anchor else "luna_spark_correct_anchor"
    prelude = run_dir / trial / "split_prelude"; base = prelude / "base"
    reuse = (prelude / "accepted_state").is_dir()
    result: dict[str, Any] = {"prelude_reused": reuse}
    try:
        if not reuse:
            initialize_subject(base)
            initial_packet = {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(base), "public_validator_catalog": public_catalog(), "remaining_budget": {"planner_calls": 3, "spark_calls": 3}}
            first = invoke(prelude / "planner_initial" / "call", base, "gpt-5.6-luna", "high", "read-only", "planner", initial_packet, "planner_initial.schema.json", executor)
            result["planner_initial"] = first
            if first["final_json"] is None or first["instance_errors"]:
                raise ControllerError("NOT_RUN_PRELUDE_PLANNER_REJECTED", "planner_validation", "initial planner report failed schema or was absent")
            anchor, crate1_semantic = validate_planner(first["final_json"], "hand_1")
            anchor_sha = sha_bytes(canon(anchor)); crate1 = controller_crate(crate1_semantic, tree_state(base), anchor_sha, trial, "planner_initial.schema.json")
            write(prelude / "anchor.json", canon({"anchor_state": anchor, "anchor_sha256": anchor_sha, "crate_sha256": sha_bytes(canon(crate1))}))
            hand1_work = prelude / "spark_hand_1" / "work"; copy_state(base, hand1_work)
            hand1 = run_hand(run_dir, trial, "split_prelude", "spark_hand_1", "gpt-5.3-codex-spark", "low", "workspace-write", hand1_work, crate1, {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(hand1_work), "hand_crate": crate1, "public_validator_catalog": public_catalog()}, executor)
            result["spark_hand_1"] = hand1
            accepted1 = prelude / "accepted_state"; result["accepted_hand_1"] = apply_hand(base, hand1_work, accepted1, {"src/ledger_stage.py"}, hand1, interpreter)
        else:
            accepted1 = prelude / "accepted_state"
            saved = json.loads((prelude / "anchor.json").read_text(encoding="utf-8")); anchor, anchor_sha = saved["anchor_state"], saved["anchor_sha256"]
            hand1 = json.loads((prelude / "spark_hand_1" / "outcome.json").read_text(encoding="utf-8"))
        fork = run_dir / trial / arm; fork_base = fork / "continuation_base"; create_fork(accepted1, fork_base)
        continuation_packet = {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(fork_base), "accepted_hand_1_receipt": hand1.get("final_json"), "public_validator_catalog": public_catalog(), "remaining_budget": {"planner_calls": 2, "spark_calls": 2}}
        if not no_anchor: continuation_packet["current_anchor"] = anchor
        cont = invoke(fork / "planner_continuation" / "call", fork_base, "gpt-5.6-luna", "high", "read-only", "planner", continuation_packet, "planner_continuation.schema.json", executor)
        result["planner_continuation"] = cont
        if cont["final_json"] is None or cont["instance_errors"]:
            raise ControllerError("CONTINUATION_PLANNER_REJECTED", "continuation_validation", "continuation planner report failed schema or was absent")
        anchor2, crate2_semantic = validate_planner(cont["final_json"], "hand_2")
        crate2 = controller_crate(crate2_semantic, tree_state(fork_base), sha_bytes(canon(anchor2)), trial, "planner_continuation.schema.json")
        hand2_work = fork / "spark_hand_2" / "work"; copy_state(fork_base, hand2_work)
        hand2 = run_hand(run_dir, trial, arm, "spark_hand_2", "gpt-5.3-codex-spark", "low", "workspace-write", hand2_work, crate2, {"task_id": "derived_ledger_rollup_v2", "trial_id": trial, "task_packet": task_packet(), "visible_state_capsule": state_capsule(hand2_work), "accepted_hand_1_receipt": hand1.get("final_json"), "hand_crate": crate2, "public_validator_catalog": public_catalog()}, executor)
        result["spark_hand_2"] = hand2
        final = fork / "final_candidate"; result["final"] = apply_hand(fork_base, hand2_work, final, {"src/solution.py"}, hand2, interpreter)
        check = candidate_check(final, {"src/ledger_stage.py", "src/solution.py"}, tree_state(fork_base), interpreter); result["validation"] = check; result["candidate"] = str(final) if check["accepted"] else None
    except ControllerError as exc:
        if exc.code == "NOT_RUN_PRELUDE_PLANNER_REJECTED" or exc.stage == "planner_validation": disposition = "NOT_RUN_PRELUDE_PLANNER_REJECTED"
        elif exc.code in {"PRELUDE_HAND1_NO_DIFF", "PRELUDE_HAND1_PATH_VIOLATION", "PRELUDE_HAND1_VISIBLE_VALIDATOR_FAILURE"}: disposition = exc.code
        else: disposition = "NOT_RUN_PRELUDE_ADMINISTRATIVE_FAILURE" if not (prelude / "accepted_state").is_dir() else "REJECTED_CONTROLLER_ERROR"
        result.update({"disposition": disposition, "error": exc.receipt(), "candidate": None})
    except Exception as exc:
        result.update({"disposition": "NOT_RUN_PRELUDE_ADMINISTRATIVE_FAILURE" if not (prelude / "accepted_state").is_dir() else "REJECTED_CONTROLLER_ERROR", "error": {"code": "CONTROLLER_EXCEPTION", "stage": "split_state_machine", "message": str(exc)}, "candidate": None})
    evidence_arm = arm if (prelude / "accepted_state").is_dir() else "split_prelude"
    seal_final_receipt(run_dir, trial, evidence_arm, result)
    write(run_dir / trial / evidence_arm / "outcome.json", canon(result))
    return result

def grade_candidate(candidate: str | None, out_dir: Path) -> dict[str, Any]:
    if not candidate: return {"outcome": "NOT_RUN_NO_CANDIDATE"}
    source = Path(candidate)
    sealed_state = tree_state(source)
    grading_copy = out_dir / "external_grading_copy"
    shutil.copytree(source, grading_copy, ignore=shutil.ignore_patterns(".git"))
    result = run([str(PREFERRED_PYTHON), str(PRIVATE / "hidden_grader.py"), str(grading_copy)], ROOT, 180)
    receipt = {"outcome": "pass" if result.returncode == 0 else "fail", "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "candidate_state_sha256": sealed_state, "candidate_state_sha256_after": tree_state(source), "grading_copy_state_sha256": tree_state(grading_copy)}
    if receipt["candidate_state_sha256"] != receipt["candidate_state_sha256_after"]:
        raise RuntimeError("hidden grading mutated sealed candidate")
    write(out_dir / "hidden_grade.json", canon(receipt)); return receipt

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--suite-commit", required=True); parser.add_argument("--run-root", type=Path)
    parser.add_argument("--prior-partial-run", type=Path, required=True); parser.add_argument("--schedule-source", type=Path, required=True)
    parser.add_argument("--preflight-receipt", type=Path, required=True); parser.add_argument("--contract-gate", type=Path, required=True); parser.add_argument("--canary-receipt", type=Path, required=True)
    args = parser.parse_args()
    if not CLI.is_file(): raise SystemExit("missing pinned CLI")
    if not (TASK / "oracle_self_test.json").is_file(): raise SystemExit("oracle self-test receipt missing")
    oracle = json.loads((TASK / "oracle_self_test.json").read_text());
    if oracle.get("tests", {}).get("mutants") != "all_fail": raise SystemExit("oracle self-test did not pass")
    schema_paths = sorted(SCHEMAS.glob("*.json"))
    schema_errors = {str(path): validate_schema(json.loads(path.read_text(encoding="utf-8")), str(path)) for path in schema_paths}
    if any(schema_errors.values()): raise SystemExit(json.dumps({"schema_errors": schema_errors}, sort_keys=True))
    if not PREFERRED_PYTHON.is_file(): raise SystemExit("preferred controller Python interpreter missing")
    preflight = json.loads(args.preflight_receipt.read_text(encoding="utf-8"))
    if not preflight.get("schema_valid") or preflight.get("exit_code") != 0:
        raise SystemExit("administrative schema preflight did not pass")
    contract_gate = json.loads(args.contract_gate.read_text(encoding="utf-8"))
    if not contract_gate.get("all_pass"):
        raise SystemExit("zero-inference controller contract gate did not pass")
    canary = json.loads(args.canary_receipt.read_text(encoding="utf-8"))
    if not canary.get("all_pass") or canary.get("call_count") != 2:
        raise SystemExit("two-call administrative canary did not pass")
    if args.run_root is None: args.run_root = ROOT / "run" / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = args.run_root.resolve(); run_dir.mkdir(parents=True, exist_ok=False)
    models = json.loads(subprocess.run([str(CLI), "debug", "models"], capture_output=True, check=True).stdout)
    model_catalog_bytes = canon(models)
    task_hash = sha(TASK / "task_packet.json"); seed = sha_bytes((args.suite_commit + task_hash + EXPERIMENT_TAG).encode()); rng = random.Random(int(seed[:16], 16))
    prior_schedule = args.schedule_source.resolve()
    schedule = json.loads(prior_schedule.read_text(encoding="utf-8"))
    if (run_dir / "schedule.json").exists(): raise SystemExit("new run schedule path already exists")
    write(run_dir / "schedule.json", canon(schedule)); write(run_dir / "model_catalog.json", model_catalog_bytes)
    manifest = {"schema": "luna-sol-anchor-replication/run-manifest@2.2", "protocol_revision": "2.2", "created_at": now(), "suite_commit": args.suite_commit, "branch": "codex/luna-sol-anchor-replication-v2", "cli_path": str(CLI), "cli_sha256": sha(CLI), "cli_version": subprocess.run([str(CLI), "--version"], capture_output=True, check=True).stdout.decode().strip(), "controller_python": {"path": str(PREFERRED_PYTHON), "version": subprocess.run([str(PREFERRED_PYTHON), "--version"], capture_output=True, check=True).stdout.decode().strip(), "sha256": sha(PREFERRED_PYTHON)}, "model_catalog_sha256": sha(run_dir / "model_catalog.json"), "task_version": "derived_ledger_rollup_v2", "task_packet_sha256": task_hash, "hidden_grader_sha256": sha(PRIVATE / "hidden_grader.py"), "visible_bundle_sha256": json.loads((TASK / "oracle_self_test.json").read_text())["build"]["visible_bundle_sha256"], "prompt_hashes": {p.name: sha(p) for p in PROMPTS.glob("*.txt")}, "schema_hashes": {p.name: sha(p) for p in SCHEMAS.glob("*.json")}, "k": 3, "schedule_seed": schedule["seed"], "schedule_source_sha256": sha(prior_schedule), "frozen": True, "prior_run_2_0": "run_20260715T205630Z", "prior_run_2_1": "run_20260715T212046Z", "prior_2_1_disposition": "PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT", "prior_2_1_benchmark_calls": 9, "prior_2_1_candidates": 0, "prior_2_1_hidden_grades": 0, "prior_partial_run": args.prior_partial_run.name, "prior_subject_outputs_admitted": 0, "prior_candidates_admitted": 0, "prior_grades_admitted": 0, "administrative_preflight_sha256": sha(args.preflight_receipt), "controller_contract_gate_sha256": sha(args.contract_gate), "live_canary_sha256": sha(args.canary_receipt), "cli_compatibility": {"requested_agents_max_depth": 0, "used_agents_max_depth": 1, "reason": "pinned CLI rejects zero; max_threads=1 and exact prompts disable subagent use"}, "stopping_rules": json.loads((TASK / "preregistration.json").read_text())["stopping_rules"]}
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
            arm_dir = arm.lower() if arm.endswith("_FULL") else ("luna_spark_no_anchor" if arm == "LUNA_SPARK_NO_ANCHOR" else "luna_spark_correct_anchor")
            grade_dir = run_dir / trial / arm_dir
            outcome["hidden_grade"] = grade_candidate(outcome.get("candidate"), grade_dir)
            seal_final_receipt(run_dir, trial, arm_dir, outcome)
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
