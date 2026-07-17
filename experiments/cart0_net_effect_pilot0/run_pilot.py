#!/usr/bin/env python3
"""Six-call synthetic CART0 repository-context net-effect pilot."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RUNNER_PATH = ROOT.parent / "luna_sol_anchor_replication_v2" / "run_v2.py"
spec = importlib.util.spec_from_file_location("cart0_net_effect_runner", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

PLANNER_MODEL = "gpt-5.6-luna"
PLANNER_EFFORT = "high"
HAND_MODEL = "gpt-5.3-codex-spark"
HAND_EFFORT = "low"
MAX_CALLS = 6
MAX_REPO_BYTES = 32768

TASK = """# Synthetic incident-window task

Implement `select_events` in `src/windowing.py` and `summarize` in
`src/summary.py`. The normative rules are split across `docs/rules/`. Do not
edit the task, rules, validator, authority card, or package initializer. The
exact acceptance command is recorded at `.cart0/500.100.VALIDATOR.md`.
"""

TEMPORAL = """# Temporal selection

An event is in the requested window exactly when `start <= timestamp < end`.
Deduplication happens before filtering: for each string `id`, retain the row
with the greatest integer `revision`; tied revisions retain the later source
row. If that winning row has status `cancelled`, the id contributes nothing.
Do not mutate the input. Output is sorted by `(timestamp, id)`.
"""

NORMALIZATION = """# Normalized event contract

Each selected event is a new object with exactly: `id`, `service`,
`timestamp`, `impact`, `suppressed`, `revision`, and `source_index`. Convert
`impact` and `revision` to integers. Missing `suppressed` means false.
"""

AGGREGATION = """# Summary contract

Group normalized events by service. Return `services`, sorted by service, and
`total_actionable_impact`. Each service object has exactly `service`,
`event_count`, `actionable_count`, and `actionable_impact`. Suppressed events
count in `event_count` but not in actionable count or impact.
"""

WINDOW_STUB = '''def select_events(events, start, end):
    """Return normalized, deduplicated events in the half-open window."""
    raise NotImplementedError
'''

SUMMARY_STUB = '''def summarize(events):
    """Return sorted per-service actionable incident totals."""
    raise NotImplementedError
'''

REFERENCE_WINDOW = '''def select_events(events, start, end):
    winners = {}
    for source_index, raw in enumerate(events):
        revision = int(raw["revision"])
        current = winners.get(str(raw["id"]))
        if current is None or (revision, source_index) >= (current[0], current[1]):
            winners[str(raw["id"])] = (revision, source_index, raw)
    selected = []
    for event_id, (revision, source_index, raw) in winners.items():
        timestamp = int(raw["timestamp"])
        if raw["status"] == "cancelled" or not (start <= timestamp < end):
            continue
        selected.append({"id": event_id, "service": str(raw["service"]), "timestamp": timestamp, "impact": int(raw["impact"]), "suppressed": bool(raw.get("suppressed", False)), "revision": revision, "source_index": source_index})
    return sorted(selected, key=lambda item: (item["timestamp"], item["id"]))
'''

REFERENCE_SUMMARY = '''def summarize(events):
    grouped = {}
    for event in events:
        bucket = grouped.setdefault(event["service"], {"service": event["service"], "event_count": 0, "actionable_count": 0, "actionable_impact": 0})
        bucket["event_count"] += 1
        if not event["suppressed"]:
            bucket["actionable_count"] += 1
            bucket["actionable_impact"] += event["impact"]
    services = [grouped[name] for name in sorted(grouped)]
    return {"services": services, "total_actionable_impact": sum(item["actionable_impact"] for item in services)}
'''

VERIFY = '''import copy
from src.summary import summarize
from src.windowing import select_events

events = [
    {"id":"old-cancel","service":"api","timestamp":10,"impact":9,"status":"active","revision":1},
    {"id":"old-cancel","service":"api","timestamp":11,"impact":9,"status":"cancelled","revision":2},
    {"id":"tie","service":"worker","timestamp":15,"impact":"3","status":"active","revision":2},
    {"id":"tie","service":"worker","timestamp":14,"impact":"5","status":"active","revision":2,"suppressed":True},
    {"id":"left","service":"api","timestamp":10,"impact":4,"status":"active","revision":1},
    {"id":"right","service":"api","timestamp":20,"impact":100,"status":"active","revision":1},
    {"id":"mid","service":"api","timestamp":12,"impact":7,"status":"active","revision":1},
]
before = copy.deepcopy(events)
selected = select_events(events, 10, 20)
assert events == before
assert selected == [
    {"id":"left","service":"api","timestamp":10,"impact":4,"suppressed":False,"revision":1,"source_index":4},
    {"id":"mid","service":"api","timestamp":12,"impact":7,"suppressed":False,"revision":1,"source_index":6},
    {"id":"tie","service":"worker","timestamp":14,"impact":5,"suppressed":True,"revision":2,"source_index":3},
]
assert summarize(selected) == {"services":[
    {"service":"api","event_count":2,"actionable_count":2,"actionable_impact":11},
    {"service":"worker","event_count":1,"actionable_count":0,"actionable_impact":0},
],"total_actionable_impact":11}
assert select_events([], 0, 1) == []
assert summarize([]) == {"services":[],"total_actionable_impact":0}
print("VISIBLE_OK")
'''


def repo_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file() and ".git" not in path.parts)


def init_subject(path: Path) -> None:
    validator = runner.powershell_command([str(runner.PREFERRED_PYTHON), "verify.py"])
    files = {
        "TASK.md": TASK,
        "docs/rules/100.temporal.md": TEMPORAL,
        "docs/rules/110.normalization.md": NORMALIZATION,
        "docs/rules/120.aggregation.md": AGGREGATION,
        "src/__init__.py": "",
        "src/windowing.py": WINDOW_STUB,
        "src/summary.py": SUMMARY_STUB,
        "verify.py": VERIFY,
        ".cart0/000.000.INDEX.md": """# 000.000 INDEX\n\n- Authority: `.cart0/000.100.AUTHORITY.md`\n- Task: `.cart0/010.100.TASK.md`\n- Repository map: `.cart0/020.100.REPOSITORY.md`\n- Work graph: `.cart0/300.100.WORK_GRAPH.md`\n- Active crate: `.cart0/300.200.CRATE_001.md`\n- Validator: `.cart0/500.100.VALIDATOR.md`\n- Decisions: `.cart0/600.100.DECISIONS.md`\n- Receipt slot: `.cart0/700.100.RECEIPT.md`\n""",
        ".cart0/000.100.AUTHORITY.md": """# 000.100 AUTHORITY\n\nSynthetic pilot only. Never edit TASK.md, docs/rules, verify.py, this authority card, the index, or src/__init__.py. Planning hands may edit only 020.100, 300.100, 300.200, 600.100, and 700.100. Implementation hands may edit only src/windowing.py and src/summary.py.\n""",
        ".cart0/010.100.TASK.md": "# 010.100 TASK\n\nNormative task: `TASK.md`. Normative rules: `docs/rules/*.md`.\n",
        ".cart0/020.100.REPOSITORY.md": "# 020.100 REPOSITORY\n\nSTATUS: UNPLANNED\n",
        ".cart0/300.100.WORK_GRAPH.md": "# 300.100 WORK GRAPH\n\nSTATUS: UNPLANNED\n",
        ".cart0/300.200.CRATE_001.md": "# 300.200 CRATE 001\n\nSTATUS: UNPLANNED\n",
        ".cart0/500.100.VALIDATOR.md": f"# 500.100 VALIDATOR\n\nExact acceptance command:\n\n```powershell\n{validator}\n```\n",
        ".cart0/600.100.DECISIONS.md": "# 600.100 DECISIONS\n\nSTATUS: UNPLANNED\n",
        ".cart0/700.100.RECEIPT.md": "# 700.100 RECEIPT\n\nSTATUS: EMPTY\n",
    }
    for relative, content in files.items():
        runner.write(path / relative, content)
    for command in (["init", "-q"], ["config", "user.name", "CART0 pilot controller"], ["config", "user.email", "pilot@example.invalid"], ["add", "."], ["commit", "-qm", "synthetic repository baseline"]):
        result = runner.git(command, path)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))


def call_prompt(role: str) -> bytes:
    common = "Use the local repository as the durable context address space. Start at `.cart0/000.000.INDEX.md`, follow its pointers, obey `.cart0/000.100.AUTHORITY.md`, and run the exact validator before claiming completion."
    if role == "planner_alone":
        detail = "You are the sole gpt-5.6-luna planner and implementer. You may update the authorized planning cards and must implement the task yourself. Do not delegate or create child calls."
    elif role == "planning_hand":
        detail = "You are a bounded gpt-5.6-luna planning hand. Inspect the repository and replace every UNPLANNED/EMPTY planning card with a precise repository map, one-node work graph, bounded CRATE_001, decisions, and a handoff receipt. The crate must authorize exactly src/windowing.py and src/summary.py, cite the task/rule/validator addresses, and include the exact validator command. Do not edit source code or execute the implementation."
    elif role == "spark_hand":
        detail = "You are the fresh gpt-5.3-codex-spark implementation hand. Retrieve the task through the index and execute only `.cart0/300.200.CRATE_001.md`. Edit only its authorized source paths. Do not edit CART0 cards."
    else:
        raise ValueError(role)
    return f"{common}\n\n{detail}\n".encode()


class PilotController:
    def __init__(self, output: Path):
        self.output = output
        self.calls: list[dict[str, Any]] = []
        self.cli_identity = runner.require_cli_identity()

    def invoke(self, call_dir: Path, cwd: Path, model: str, effort: str, role: str) -> dict[str, Any]:
        if len(self.calls) >= MAX_CALLS:
            raise RuntimeError("six-call ceiling reached")
        call_dir.mkdir(parents=True, exist_ok=False)
        prompt = call_prompt(role)
        prompt_path = call_dir / "prompt.txt"; runner.write(prompt_path, prompt)
        final_path = call_dir / "final_response.txt"
        command = runner.spark_execution_command(cwd, final_path, model, effort)
        runner.require_spark_execution_surface(command)
        dispatch = {"call_index": len(self.calls) + 1, "role": role, "model": model, "effort": effort, "cwd": str(cwd), "command": command, "prompt_sha256": runner.sha(prompt_path), "cli_identity": self.cli_identity, "surface": "app_inherited", "free_form": True, "output_schema": None}
        runner.write(call_dir / "dispatch.json", runner.canon(dispatch))
        started = time.time()
        try:
            result = subprocess.run(command, cwd=cwd, input=prompt, capture_output=True, timeout=900)
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, exc.stdout or b"", exc.stderr or b"")
            timed_out = True
        runner.write(call_dir / "events.jsonl", result.stdout)
        runner.write(call_dir / "stderr.txt", result.stderr)
        final_bytes = final_path.read_bytes() if final_path.is_file() else b""
        receipt = {"completed_at": runner.now(), "duration_seconds": round(time.time() - started, 3), "exit_code": result.returncode, "timed_out": timed_out, "stdout_sha256": runner.sha(call_dir / "events.jsonl"), "stderr_sha256": runner.sha(call_dir / "stderr.txt"), "final_response_sha256": runner.sha_bytes(final_bytes), "usage": runner.extract_usage(result.stdout), "administrative_error": runner.extract_remote_error(result.stdout), **dispatch}
        runner.write(call_dir / "completion.json", runner.canon(receipt))
        self.calls.append(receipt)
        return receipt


def validator(subject: Path) -> dict[str, Any]:
    command = [str(runner.PREFERRED_PYTHON), "verify.py"]
    result = runner.run(command, subject, 120)
    return {"command": command, "shell_command": runner.powershell_command(command), "returncode": result.returncode, "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace"), "passed": result.returncode == 0}


def preserve_patch(subject: Path, evidence: Path) -> tuple[list[str], list[str], bytes]:
    changed = runner.status_paths(subject)
    patch = runner.git(["diff", "--binary", "--no-ext-diff"], subject)
    if patch.returncode:
        raise RuntimeError(patch.stderr.decode(errors="replace"))
    runner.write(evidence / "candidate.patch", patch.stdout)
    return changed, [], patch.stdout


PLANNING_PATHS = {".cart0/020.100.REPOSITORY.md", ".cart0/300.100.WORK_GRAPH.md", ".cart0/300.200.CRATE_001.md", ".cart0/600.100.DECISIONS.md", ".cart0/700.100.RECEIPT.md"}
SOURCE_PATHS = {"src/windowing.py", "src/summary.py"}


def write_planning_fixture(subject: Path) -> None:
    exact = runner.powershell_command([str(runner.PREFERRED_PYTHON), "verify.py"])
    runner.write(subject / ".cart0/020.100.REPOSITORY.md", "# 020.100 REPOSITORY\n\nSources: src/windowing.py, src/summary.py. Rules and task are pointer-addressed.\n")
    runner.write(subject / ".cart0/300.100.WORK_GRAPH.md", "# 300.100 WORK GRAPH\n\nOne node: 300.200.CRATE_001.\n")
    runner.write(subject / ".cart0/300.200.CRATE_001.md", f"# 300.200 CRATE 001\n\nAllowed: src/windowing.py, src/summary.py\nPointers: .cart0/010.100.TASK.md, .cart0/500.100.VALIDATOR.md\nValidator: {exact}\n")
    runner.write(subject / ".cart0/600.100.DECISIONS.md", "# 600.100 DECISIONS\n\nDeduplicate before temporal filtering; aggregate normalized output.\n")
    runner.write(subject / ".cart0/700.100.RECEIPT.md", "# 700.100 RECEIPT\n\nBounded one-crate handoff prepared.\n")


def context_gate(subject: Path, evidence: Path) -> dict[str, Any]:
    changed = runner.status_paths(subject)
    unexpected = sorted(set(changed) - PLANNING_PATHS)
    crate = (subject / ".cart0/300.200.CRATE_001.md").read_text(encoding="utf-8")
    graph = (subject / ".cart0/300.100.WORK_GRAPH.md").read_text(encoding="utf-8")
    total = repo_bytes(subject)
    required = ["src/windowing.py", "src/summary.py", ".cart0/010.100.TASK.md", ".cart0/500.100.VALIDATOR.md", str(runner.PREFERRED_PYTHON), "verify.py"]
    passed = not unexpected and bool(changed) and "UNPLANNED" not in crate + graph and all(value in crate for value in required) and total <= MAX_REPO_BYTES
    patch = runner.git(["diff", "--binary", "--no-ext-diff"], subject)
    runner.write(evidence / "planning.patch", patch.stdout)
    receipt = {"passed": passed, "changed": changed, "unexpected": unexpected, "repo_bytes": total, "max_repo_bytes": MAX_REPO_BYTES, "required_crate_strings": required, "planning_patch_sha256": runner.sha_bytes(patch.stdout)}
    runner.write(evidence / "context_gate.json", runner.canon(receipt))
    return receipt


def final_gate(subject: Path, evidence: Path, allowed: set[str], call: dict[str, Any]) -> dict[str, Any]:
    changed, _, patch = preserve_patch(subject, evidence)
    unexpected = sorted(set(changed) - allowed)
    check = validator(subject) if changed and not unexpected else {"passed": False, "skipped": True}
    passed = call["exit_code"] == 0 and bool(changed) and not unexpected and check.get("passed", False)
    receipt = {"passed": passed, "disposition": "SYNTHETIC_TASK_PASS" if passed else "SYNTHETIC_TASK_FAIL", "changed": changed, "unexpected": unexpected, "validator": check, "patch_sha256": runner.sha_bytes(patch), "final_state_sha256": runner.tree_state(subject), "repo_bytes": repo_bytes(subject), "call_exit_code": call["exit_code"], "call_prompt_sha256": call["prompt_sha256"], "cli_identity": call["cli_identity"], "capability_evidence": False}
    runner.write(evidence / "final_receipt.json", runner.canon(receipt))
    return receipt


def run_planner_alone(controller: PilotController, case: Path, subject: Path) -> dict[str, Any]:
    evidence = case / "planner_alone"; evidence.mkdir(parents=True)
    call = controller.invoke(evidence / "call", subject, PLANNER_MODEL, PLANNER_EFFORT, "planner_alone")
    receipt = final_gate(subject, evidence, SOURCE_PATHS | PLANNING_PATHS, call)
    return {"arm": "PLANNER_ALONE", "calls": 1, "administrative_valid": call["exit_code"] == 0 and call.get("administrative_error") is None, "call": call, "final": receipt}


def run_delegated(controller: PilotController, case: Path, subject: Path) -> dict[str, Any]:
    evidence = case / "planner_to_spark"; evidence.mkdir(parents=True)
    planner_call = controller.invoke(evidence / "planner_call", subject, PLANNER_MODEL, PLANNER_EFFORT, "planning_hand")
    context = context_gate(subject, evidence)
    if planner_call["exit_code"] != 0 or not context["passed"]:
        result = {"arm": "PLANNER_TO_SPARK", "calls": 1, "administrative_valid": planner_call["exit_code"] == 0 and planner_call.get("administrative_error") is None, "planner_call": planner_call, "context_gate": context, "final": {"passed": False, "disposition": "PLANNING_CONTEXT_REJECTED"}}
        runner.write(evidence / "arm_result.json", runner.canon(result)); return result
    runner.git(["add", ".cart0/020.100.REPOSITORY.md", ".cart0/300.100.WORK_GRAPH.md", ".cart0/300.200.CRATE_001.md", ".cart0/600.100.DECISIONS.md", ".cart0/700.100.RECEIPT.md"], subject)
    committed = runner.git(["commit", "-qm", "accept bounded repository context"], subject)
    if committed.returncode:
        raise RuntimeError(committed.stderr.decode(errors="replace"))
    hand_call = controller.invoke(evidence / "hand_call", subject, HAND_MODEL, HAND_EFFORT, "spark_hand")
    final = final_gate(subject, evidence, SOURCE_PATHS, hand_call)
    result = {"arm": "PLANNER_TO_SPARK", "calls": 2, "administrative_valid": all(call["exit_code"] == 0 and call.get("administrative_error") is None for call in (planner_call, hand_call)), "planner_call": planner_call, "context_gate": context, "hand_call": hand_call, "final": final}
    runner.write(evidence / "arm_result.json", runner.canon(result)); return result


def self_test() -> dict[str, Any]:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="cart0-net-effect-selftest-") as temp:
        subject = Path(temp) / "subject"; init_subject(subject)
        initial_bytes = repo_bytes(subject)
        initial = validator(subject)
        runner.write(subject / "src/windowing.py", REFERENCE_WINDOW)
        runner.write(subject / "src/summary.py", REFERENCE_SUMMARY)
        reference = validator(subject)
        changed = runner.status_paths(subject)
        planned = Path(temp) / "planned"; init_subject(planned); write_planning_fixture(planned)
        positive_context = context_gate(planned, Path(temp) / "positive_evidence")
        invalid = Path(temp) / "invalid"; init_subject(invalid); write_planning_fixture(invalid); runner.write(invalid / "TASK.md", "mutated\n")
        negative_context = context_gate(invalid, Path(temp) / "negative_evidence")
        spark_prompt = call_prompt("spark_hand")
        command = runner.spark_execution_command(Path("<SUBJECT>"), Path("<FINAL>"), HAND_MODEL, HAND_EFFORT)
        runner.require_spark_execution_surface(command)
        result = {"schema": "tier-bench/cart0-net-effect-self-test@0", "runner_sha256": runner.sha(Path(__file__).resolve()), "preregistration_sha256": runner.sha(ROOT / "PREREGISTRATION.md"), "initial_validator_fails": not initial["passed"], "reference_validator_passes": reference["passed"], "reference_validator_stdout": reference.get("stdout"), "reference_validator_stderr": reference.get("stderr"), "reference_changed_paths": changed, "initial_repo_bytes": initial_bytes, "under_context_bound": initial_bytes <= MAX_REPO_BYTES, "valid_planning_context_passes": positive_context["passed"], "task_mutation_context_fails": not negative_context["passed"] and "TASK.md" in negative_context["unexpected"], "spark_prompt_uses_repo_pointers_not_task_payload": b".cart0/000.000.INDEX.md" in spark_prompt and TASK.encode() not in spark_prompt, "freeform_command_has_no_output_schema": "--output-schema" not in command, "all_pass": not initial["passed"] and reference["passed"] and changed == ["src/summary.py", "src/windowing.py"] and initial_bytes <= MAX_REPO_BYTES and positive_context["passed"] and not negative_context["passed"] and "TASK.md" in negative_context["unexpected"] and b".cart0/000.000.INDEX.md" in spark_prompt and TASK.encode() not in spark_prompt and "--output-schema" not in command}
        return result


def model_freeze() -> dict[str, Any]:
    catalog = json.loads(subprocess.run([str(runner.CLI), "debug", "models"], capture_output=True, check=True, timeout=60).stdout)
    selected = []
    for item in catalog.get("models", []):
        if item.get("slug") in {PLANNER_MODEL, HAND_MODEL}:
            selected.append({"slug": item["slug"], "context_window": item.get("context_window"), "effective_context_window_percent": item.get("effective_context_window_percent"), "supported_reasoning_levels": [level.get("effort") for level in item.get("supported_reasoning_levels", [])], "visibility": item.get("visibility")})
    if {item["slug"] for item in selected} != {PLANNER_MODEL, HAND_MODEL}:
        raise RuntimeError("preregistered model missing from local catalog")
    return {"schema": "tier-bench/cart0-net-effect-model-freeze@0", "created_at": runner.now(), "cli_identity": runner.require_cli_identity(), "models": sorted(selected, key=lambda item: item["slug"]), "max_subject_bytes": MAX_REPO_BYTES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--suite-commit")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        if args.self_test_output:
            if args.self_test_output.exists(): raise SystemExit(f"refusing to overwrite: {args.self_test_output}")
            runner.write(args.self_test_output.resolve(), runner.canon(result))
        print(json.dumps(result, indent=2, sort_keys=True)); return 0 if result["all_pass"] else 1
    if args.output is None or not args.suite_commit:
        raise SystemExit("output and --suite-commit are required")
    head = runner.git(["rev-parse", "HEAD"], REPO)
    observed_head = head.stdout.decode().strip()
    if head.returncode or observed_head != args.suite_commit:
        raise SystemExit(f"suite commit mismatch: requested {args.suite_commit}, observed {observed_head}")
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    controller = PilotController(output)
    freeze = model_freeze(); runner.write(output / "model_freeze.json", runner.canon(freeze))
    cases = []
    for replicate in range(1, 3):
        case = output / f"replicate_{replicate:03d}"; base = case / "base"; init_subject(base)
        alone = case / "planner_alone_subject"; delegated = case / "planner_to_spark_subject"
        runner.copy_state(base, alone); runner.copy_state(base, delegated)
        if runner.tree_state(alone) != runner.tree_state(delegated):
            raise RuntimeError("matched arm baselines differ")
        order = ["PLANNER_ALONE", "PLANNER_TO_SPARK"] if replicate == 1 else ["PLANNER_TO_SPARK", "PLANNER_ALONE"]
        outcomes: dict[str, Any] = {}
        for arm in order:
            outcomes[arm] = run_planner_alone(controller, case, alone) if arm == "PLANNER_ALONE" else run_delegated(controller, case, delegated)
        case_result = {"replicate": replicate, "order": order, "baseline_state_sha256": runner.tree_state(base), "arms": outcomes, "paired_interpretable": all(value.get("administrative_valid", False) for value in outcomes.values())}
        runner.write(case / "case_result.json", runner.canon(case_result)); cases.append(case_result)
    summary = {"schema": "tier-bench/cart0-net-effect-pilot@0", "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "suite_commit": observed_head, "planner": {"model": PLANNER_MODEL, "effort": PLANNER_EFFORT}, "hand": {"model": HAND_MODEL, "effort": HAND_EFFORT}, "replicates": 2, "call_ceiling": MAX_CALLS, "call_count": len(controller.calls), "calls": controller.calls, "cases": cases, "planner_alone_passes": sum(1 for case in cases if case["arms"]["PLANNER_ALONE"]["final"].get("passed")), "planner_to_spark_passes": sum(1 for case in cases if case["arms"]["PLANNER_TO_SPARK"]["final"].get("passed")), "all_baselines_matched": True, "benchmark_calls": 0, "hidden_grades": 0, "capability_evidence": False, "interpretation": "exploratory synthetic mechanism evidence only"}
    runner.write(output / "summary.json", runner.canon(summary))
    print(json.dumps({"output": str(output), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
