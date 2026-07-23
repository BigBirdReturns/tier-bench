#!/usr/bin/env python3
"""Prepare, dispatch, grade, compare, and verify CART0-BOUND-1.

Provider output is never printed.  The four preregistered calls are written to
disk before any candidate is graded or compared.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.cart0_anchor import (  # noqa: E402
    build as build_anchor,
    canonical_json,
    full_context_prompt,
    metrics,
    resurface,
    sha256 as bytes_sha256,
    verify as verify_anchor,
)
from scripts.export_solver_packet import export_packet, packet_digest  # noqa: E402
from scripts.grade_solver_packet import grade as grade_packet  # noqa: E402


PREREG = ROOT / "experiments" / "cart0_bound_1" / "preregistration.json"
PROFILE_ROOT = ROOT / "experiments" / "cart0_bound_1" / "profile"
SPEC = PROFILE_ROOT / "task_state.json"
CATALOG = PROFILE_ROOT / "cards.json"
PROFILE = PROFILE_ROOT / "transition_profile.json"
BOUNDARY = "subject_dispatch"
TASK_DESCRIPTOR = "Solve the frozen hidden-free task packet appended below; return only the complete target file."
TASK_SEPARATOR = b"\n\n===== FROZEN TASK PACKET PROMPT (IDENTICAL ACROSS ARMS) =====\n"
COORDINATOR_ID = "codex-sol-driver-019f628b-cb07-7d92-8092-067d7e175baa"


class Bound1Error(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Bound1Error(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Bound1Error(f"JSON object required: {path}")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise Bound1Error(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def write_new(path: Path, raw: bytes) -> None:
    if path.exists():
        raise Bound1Error(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".writing")
    if tmp.exists():
        raise Bound1Error(f"temporary output already exists: {tmp}")
    with tmp.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def write_json_new(path: Path, value: Any) -> None:
    write_new(path, canonical_json(value))


def require_frozen_inputs(prereg: dict[str, Any]) -> None:
    if prereg.get("schema") != "tier-bench/cart0-bound-1-preregistration@1":
        raise Bound1Error("unexpected preregistration schema")
    for task in prereg["tasks"]:
        for key in ("manifest", "hidden_grader"):
            path = ROOT / task[f"{key}_path"]
            if file_sha256(path) != task[f"{key}_sha256"]:
                raise Bound1Error(f"frozen {key} drifted: {path}")
    for name, expected in prereg["frozen_tools"].items():
        path = ROOT / "scripts" / name
        if file_sha256(path) != expected:
            raise Bound1Error(f"frozen tool drifted: {path}")
    if git("diff-index", "--quiet", "HEAD", "--") != "":
        raise Bound1Error("tracked worktree differs from HEAD")


def all_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def write_sums(root: Path, name: str) -> None:
    target = root / name
    rows = []
    for path in all_files(root):
        if path == target:
            continue
        rows.append(f"{file_sha256(path)}  {path.relative_to(root).as_posix()}\n")
    write_new(target, "".join(rows).encode("utf-8"))


def verify_sums(root: Path, name: str) -> int:
    sums = root / name
    if not sums.is_file():
        raise Bound1Error(f"missing checksum manifest: {sums}")
    count = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        expected, rel = line.split("  ", 1)
        path = root / rel
        if not path.is_file() or file_sha256(path) != expected:
            raise Bound1Error(f"checksum mismatch: {rel}")
        count += 1
    return count


def prepare(run: Path) -> dict[str, Any]:
    prereg = read_json(PREREG)
    require_frozen_inputs(prereg)
    if run.exists():
        raise Bound1Error(f"run directory already exists: {run}")
    building = run.with_name(run.name + ".building")
    if building.exists():
        raise Bound1Error(f"temporary run directory exists: {building}")
    source_commit = git("rev-parse", "HEAD")
    try:
        building.mkdir(parents=True)
        packets: dict[str, Any] = {}
        for task in prereg["tasks"]:
            task_id = task["task_id"]
            packet_root = building / "packets" / task_id
            solver = packet_root / "solver"
            receipt_path = packet_root / "coordinator_receipt.json"
            receipt = export_packet(ROOT / task["manifest_path"], solver, receipt_path, ROOT)
            packets[task_id] = {
                "solver_path": solver.relative_to(building).as_posix(),
                "coordinator_receipt_path": receipt_path.relative_to(building).as_posix(),
                "packet_sha256": receipt["packet_sha256"],
                "task_prompt_sha256": file_sha256(solver / "PROMPT.md"),
            }

        bundle = building / "cart0_bundle"
        build_anchor(ROOT, SPEC, CATALOG, PROFILE, bundle, BOUNDARY, 256)
        spec, _, anchor_receipt, _, _ = verify_anchor(ROOT, bundle)
        full = full_context_prompt(ROOT, spec, BOUNDARY, TASK_DESCRIPTOR)
        compact = resurface(ROOT, bundle, BOUNDARY, TASK_DESCRIPTOR, None)
        write_new(building / "contexts" / "A_full.txt", full)
        write_new(building / "contexts" / "B_cart0.txt", compact)

        entries = []
        contexts = {"A_full": full, "B_cart0": compact}
        for cell in prereg["dispatch_order"]:
            task_id, arm = cell.split("/", 1)
            solver = building / packets[task_id]["solver_path"]
            task_prompt = (solver / "PROMPT.md").read_bytes()
            prompt = contexts[arm] + TASK_SEPARATOR + task_prompt
            prompt_path = building / "prompts" / task_id / arm / "prompt.txt"
            write_new(prompt_path, prompt)
            entries.append({
                "cell": cell,
                "task_id": task_id,
                "arm": arm,
                "prompt_path": prompt_path.relative_to(building).as_posix(),
                "prompt_sha256": bytes_sha256(prompt),
                "prompt_metrics": metrics(prompt),
                "task_prompt_sha256": bytes_sha256(task_prompt),
                "packet_sha256": packets[task_id]["packet_sha256"],
            })

        manifest = {
            "schema": "tier-bench/cart0-bound-1-input-manifest@1",
            "experiment_id": "CART0-BOUND-1",
            "source_commit": source_commit,
            "preregistration_sha256": file_sha256(PREREG),
            "profile_sha256": file_sha256(PROFILE),
            "spec_sha256": file_sha256(SPEC),
            "catalog_sha256": file_sha256(CATALOG),
            "anchor_receipt_sha256": file_sha256(bundle / "receipt.json"),
            "anchor_metrics": anchor_receipt["anchor_metrics"],
            "active_anchor_plus_cards_metrics": anchor_receipt["active_anchor_plus_cards_metrics"],
            "context_metrics": {arm: metrics(raw) for arm, raw in contexts.items()},
            "packets": packets,
            "dispatch_order": prereg["dispatch_order"],
            "entries": entries,
            "model": prereg["constants"],
            "provider_calls": 0,
        }
        write_json_new(building / "input_manifest.json", manifest)
        write_sums(building, "SHA256SUMS.inputs")
        building.replace(run)
        return manifest
    except Exception:
        if building.exists():
            shutil.rmtree(building, ignore_errors=True)
        raise


def provider_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if (upper in {"CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION"}
                or (upper.startswith("CLAUDE_CODE_") and upper.endswith("_SESSION_ID"))):
            env.pop(key, None)
    return env


def command_for(prereg: dict[str, Any]) -> list[str]:
    const = prereg["constants"]
    executable = shutil.which("claude")
    if executable is None:
        raise Bound1Error("claude executable is unavailable")
    return [
        executable,
        "--safe-mode",
        "--no-session-persistence",
        "--no-chrome",
        "--disable-slash-commands",
        "--permission-mode", "dontAsk",
        "--tools", "",
        "--model", const["model"],
        "--effort", const["effort"],
        "--max-budget-usd", str(const["max_budget_usd_per_call"]),
        "--output-format", "json",
        "--prompt-suggestions", "false",
        "--system-prompt", const["system_prompt"],
        "-p",
    ]


def normalized_events(payload: dict[str, Any]) -> bytes:
    session_id = payload.get("session_id")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return canonical_json({"type": "thread.started", "thread_id": session_id}) + canonical_json(
        {"type": "turn.completed", "usage": usage}
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dispatch(run: Path) -> dict[str, Any]:
    prereg = read_json(PREREG)
    require_frozen_inputs(prereg)
    verify_sums(run, "SHA256SUMS.inputs")
    manifest = read_json(run / "input_manifest.json")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str((run / "input_manifest.json").relative_to(ROOT))],
        cwd=ROOT, capture_output=True,
    )
    if tracked.returncode:
        raise Bound1Error("generated inputs must be committed before dispatch")
    outputs = run / "provider_outputs"
    if outputs.exists():
        raise Bound1Error("provider output directory already exists; retries are forbidden")
    outputs.mkdir()
    command = command_for(prereg)
    rows = []
    total_reported_cost = 0.0
    for entry in manifest["entries"]:
        cell = entry["cell"]
        task_id, arm = entry["task_id"], entry["arm"]
        prompt_path = run / entry["prompt_path"]
        if file_sha256(prompt_path) != entry["prompt_sha256"]:
            raise Bound1Error(f"prompt drifted before dispatch: {cell}")
        cell_dir = outputs / task_id / arm
        cell_dir.mkdir(parents=True)
        started_at = utc_now()
        started = time.perf_counter_ns()
        timed_out = False
        try:
            with prompt_path.open("rb") as prompt_handle:
                result = subprocess.run(
                    command,
                    cwd=run / manifest["packets"][task_id]["solver_path"],
                    stdin=prompt_handle,
                    capture_output=True,
                    env=provider_env(),
                    timeout=600,
                )
            returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
        duration_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
        write_new(cell_dir / "raw_provider.json", stdout)
        write_new(cell_dir / "stderr.txt", stderr)
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        candidate = payload.get("result") if isinstance(payload, dict) else None
        candidate_sha = None
        if isinstance(candidate, str) and candidate:
            candidate_raw = candidate.encode("utf-8")
            write_new(cell_dir / "candidate.py", candidate_raw)
            candidate_sha = bytes_sha256(candidate_raw)
        events = normalized_events(payload if isinstance(payload, dict) else {})
        write_new(cell_dir / "events.jsonl", events)
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        reported_cost = payload.get("total_cost_usd") if isinstance(payload, dict) else None
        if isinstance(reported_cost, (int, float)):
            total_reported_cost += float(reported_cost)
        receipt = {
            "schema": "tier-bench/cart0-bound-1-provider-receipt@1",
            "cell": cell,
            "task_id": task_id,
            "arm": arm,
            "prompt_sha256": entry["prompt_sha256"],
            "prompt_metrics": entry["prompt_metrics"],
            "command_argv": command[1:],
            "model_requested": prereg["constants"]["model"],
            "effort": prereg["constants"]["effort"],
            "session_id": payload.get("session_id") if isinstance(payload, dict) else None,
            "started_at": started_at,
            "completed_at": utc_now(),
            "duration_ms": duration_ms,
            "returncode": returncode,
            "timed_out": timed_out,
            "is_error": payload.get("is_error") if isinstance(payload, dict) else None,
            "stop_reason": payload.get("stop_reason") if isinstance(payload, dict) else None,
            "raw_provider_sha256": file_sha256(cell_dir / "raw_provider.json"),
            "stderr_sha256": file_sha256(cell_dir / "stderr.txt"),
            "candidate_sha256": candidate_sha,
            "events_sha256": file_sha256(cell_dir / "events.jsonl"),
            "usage": usage,
            "model_usage": payload.get("modelUsage", {}) if isinstance(payload, dict) else {},
            "provider_reported_cost_usd": reported_cost,
            "cost_basis": "subscription-derived",
            "retry_count": 0,
        }
        write_json_new(cell_dir / "provider_receipt.json", receipt)
        rows.append({
            "cell": cell,
            "provider_receipt_path": (cell_dir / "provider_receipt.json").relative_to(run).as_posix(),
            "provider_receipt_sha256": file_sha256(cell_dir / "provider_receipt.json"),
            "candidate_present": candidate_sha is not None,
            "session_id": receipt["session_id"],
        })
        print(json.dumps({"sealed": cell, "candidate_present": candidate_sha is not None,
                          "returncode": returncode}), flush=True)
    sessions = [row["session_id"] for row in rows]
    result = {
        "schema": "tier-bench/cart0-bound-1-dispatch-manifest@1",
        "input_manifest_sha256": file_sha256(run / "input_manifest.json"),
        "dispatch_order": [row["cell"] for row in rows],
        "rows": rows,
        "fresh_unique_sessions": None not in sessions and len(set(sessions)) == len(sessions),
        "provider_reported_cost_usd_total": round(total_reported_cost, 9),
        "cost_basis": "subscription-derived",
        "retries": 0,
        "responses_disclosed_between_calls": False,
    }
    write_json_new(run / "dispatch_manifest.json", result)
    write_sums(outputs, "SHA256SUMS.provider")
    return result


def grade(run: Path) -> dict[str, Any]:
    verify_sums(run, "SHA256SUMS.inputs")
    verify_sums(run / "provider_outputs", "SHA256SUMS.provider")
    manifest = read_json(run / "input_manifest.json")
    grades_root = run / "grades"
    if grades_root.exists():
        raise Bound1Error("grades already exist")
    rows = []
    for entry in manifest["entries"]:
        task_id, arm = entry["task_id"], entry["arm"]
        cell_dir = run / "provider_outputs" / task_id / arm
        candidate = cell_dir / "candidate.py"
        if not candidate.is_file():
            rows.append({"cell": entry["cell"], "outcome": "partial", "reason": "missing candidate"})
            continue
        packet = run / manifest["packets"][task_id]["solver_path"]
        receipt = run / manifest["packets"][task_id]["coordinator_receipt_path"]
        out = grades_root / task_id / arm
        sealed_candidate = run / "sealed_candidates" / task_id / arm / "input.py"
        result = grade_packet(
            receipt, packet, candidate, out, COORDINATOR_ID,
            cell_dir / "events.jsonl", ROOT, 30.0, sealed_candidate,
        )
        rows.append({
            "cell": entry["cell"],
            "outcome": result["outcome"],
            "grade_receipt_path": (out / "grade-receipt.json").relative_to(run).as_posix(),
            "grade_receipt_sha256": file_sha256(out / "grade-receipt.json"),
        })
        print(json.dumps({"graded": entry["cell"], "outcome": result["outcome"]}), flush=True)
    result = {
        "schema": "tier-bench/cart0-bound-1-grade-manifest@1",
        "coordinator_id": COORDINATOR_ID,
        "hidden_grader_runs_per_candidate": 2,
        "rows": rows,
    }
    write_json_new(run / "grade_manifest.json", result)
    write_sums(grades_root, "SHA256SUMS.grades")
    write_sums(run / "sealed_candidates", "SHA256SUMS.candidates")
    return result


def token_usage(receipt: dict[str, Any]) -> dict[str, int]:
    usage = receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}
    clean = {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
    }
    clean["provider_total_input_tokens"] = (
        clean["input_tokens"] + clean["cache_read_input_tokens"]
        + clean["cache_creation_input_tokens"]
    )
    return clean


def comparison_value(run: Path) -> dict[str, Any]:
    prereg = read_json(PREREG)
    manifest = read_json(run / "input_manifest.json")
    entries = {(row["task_id"], row["arm"]): row for row in manifest["entries"]}
    tasks = []
    reductions = []
    both_pass = True
    for task in prereg["tasks"]:
        task_id = task["task_id"]
        arms = {}
        for arm in ("A_full", "B_cart0"):
            provider_path = run / "provider_outputs" / task_id / arm / "provider_receipt.json"
            provider = read_json(provider_path)
            grade_path = run / "grades" / task_id / arm / "grade-receipt.json"
            grade_receipt = read_json(grade_path) if grade_path.is_file() else {"outcome": "partial"}
            arms[arm] = {
                "hidden_grade_outcome": grade_receipt["outcome"],
                "candidate_sha256": provider.get("candidate_sha256"),
                "prompt_metrics": entries[(task_id, arm)]["prompt_metrics"],
                "usage": token_usage(provider),
                "duration_ms": provider["duration_ms"],
                "provider_reported_cost_usd": provider.get("provider_reported_cost_usd"),
                "session_id": provider.get("session_id"),
            }
        a_tokens = arms["A_full"]["usage"]["provider_total_input_tokens"]
        b_tokens = arms["B_cart0"]["usage"]["provider_total_input_tokens"]
        reduction = None if a_tokens <= 0 else round(1 - b_tokens / a_tokens, 6)
        reductions.append(reduction)
        pair_pass = (arms["A_full"]["hidden_grade_outcome"] == "pass"
                     and arms["B_cart0"]["hidden_grade_outcome"] == "pass")
        both_pass = both_pass and pair_pass
        tasks.append({
            "task_id": task_id,
            "knot_type": task["knot_type"],
            "arms": arms,
            "both_arms_pass": pair_pass,
            "provider_total_input_reduction_fraction": reduction,
            "prompt_payload_reduction_fraction": round(
                1 - arms["B_cart0"]["prompt_metrics"]["utf8_bytes"]
                / arms["A_full"]["prompt_metrics"]["utf8_bytes"], 6
            ),
        })
    threshold_met = all(value is not None and value >= 0.25 for value in reductions)
    return {
        "schema": "tier-bench/cart0-bound-1-comparison@1",
        "experiment_id": "CART0-BOUND-1",
        "task_count": 2,
        "tasks": tasks,
        "both_arms_pass_both_tasks": both_pass,
        "provider_input_reduction_at_least_25_percent_each_task": threshold_met,
        "operational_narrow_win": both_pass and threshold_met,
        "operational_narrow_win_rule": prereg["operational_narrow_win_rule"],
        "claim_boundary": "Two-task B1 fidelity and provider telemetry only; no aggregate benchmark, B2 causality, portability, billing-savings, production-custody, or context-window claim.",
    }


def compare(run: Path) -> dict[str, Any]:
    if (run / "comparison.json").exists():
        raise Bound1Error("comparison already exists")
    value = comparison_value(run)
    write_json_new(run / "comparison.json", value)
    write_sums(run, "SHA256SUMS.complete")
    return value


def verify(run: Path) -> dict[str, Any]:
    inputs = verify_sums(run, "SHA256SUMS.inputs")
    provider = verify_sums(run / "provider_outputs", "SHA256SUMS.provider")
    grades = verify_sums(run / "grades", "SHA256SUMS.grades")
    candidates = verify_sums(run / "sealed_candidates", "SHA256SUMS.candidates")
    manifest = read_json(run / "input_manifest.json")
    dispatch_manifest = read_json(run / "dispatch_manifest.json")
    if dispatch_manifest["dispatch_order"] != manifest["dispatch_order"]:
        raise Bound1Error("dispatch order drifted")
    if not dispatch_manifest["fresh_unique_sessions"] or dispatch_manifest["retries"] != 0:
        raise Bound1Error("fresh-session or no-retry invariant failed")
    for entry in manifest["entries"]:
        task_id, arm = entry["task_id"], entry["arm"]
        cell = run / "provider_outputs" / task_id / arm
        receipt = read_json(cell / "provider_receipt.json")
        if receipt["prompt_sha256"] != entry["prompt_sha256"]:
            raise Bound1Error(f"prompt receipt mismatch: {entry['cell']}")
        if receipt["raw_provider_sha256"] != file_sha256(cell / "raw_provider.json"):
            raise Bound1Error(f"raw provider receipt mismatch: {entry['cell']}")
        candidate = cell / "candidate.py"
        if receipt["candidate_sha256"] != file_sha256(candidate):
            raise Bound1Error(f"candidate receipt mismatch: {entry['cell']}")
        grade_receipt = read_json(run / "grades" / task_id / arm / "grade-receipt.json")
        if grade_receipt["raw_response_sha256"] != file_sha256(candidate):
            raise Bound1Error(f"grade candidate mismatch: {entry['cell']}")
    expected = comparison_value(run)
    actual = read_json(run / "comparison.json")
    if canonical_json(expected) != canonical_json(actual):
        raise Bound1Error("comparison does not reproduce")
    complete = verify_sums(run, "SHA256SUMS.complete")
    return {
        "verified": True,
        "input_files": inputs,
        "provider_files": provider,
        "grade_files": grades,
        "candidate_files": candidates,
        "complete_manifest_entries": complete,
        "comparison_sha256": file_sha256(run / "comparison.json"),
        "operational_narrow_win": actual["operational_narrow_win"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "dispatch", "grade", "compare", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    functions = {"prepare": prepare, "dispatch": dispatch, "grade": grade,
                 "compare": compare, "verify": verify}
    try:
        result = functions[args.command](run)
    except Exception as exc:
        print(f"CART0_BOUND_1_REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
