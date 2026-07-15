"""Deterministic driver-boundary pilot administration tests; zero model calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tier_runner.pilot import (
    ARMS,
    CLOSEOUT_SCHEMA,
    EVIDENCE_SCHEMA,
    PLAN_SCHEMA,
    RESIDUAL_ORDERS,
    PilotError,
    audit_normalized_payload,
    audit_label,
    canonical_json,
    close_pilot,
    derive_schedule,
    sha256_bytes,
    sha256_file,
    validate_plan,
)
from tier_runner.events import event_hash
import tier_runner.pilot_composition as pilot_composition
from tier_runner.pilot_composition import (
    acceptance_receipt_hash,
    answer_operator_question,
    new_pilot_arm_state,
    record_acceptance,
    record_pilot_call,
    read_state,
    render_next_prompt,
    write_state,
)
from tier_runner.pilot_manifest import load_pilot_composition


PROTOCOL = "076fd1e3d97c22f7c33933c5dee4ff897d7ba4e6"
BACKEND = "b" * 64
BASE = "a" * 40
SEED = bytes(range(32))
UTC = timezone.utc
_FIXTURE_CACHE: dict[bool, Path] = {}


def _write(path: Path, raw: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": path.as_posix(), "sha256": sha256_bytes(raw)}


def _relative_artifact(root: Path, relative: str, raw: bytes) -> dict:
    artifact = _write(root / relative, raw)
    artifact["path"] = relative
    return artifact


def _plan(
    backend_sha: str = BACKEND,
    base_commit: str = BASE,
    profile: dict | None = None,
) -> dict:
    tasks = [
        {
            "task_id": f"real-{index:02d}",
            "base_commit": base_commit,
            "task": f"Make deterministic change {index}",
            "files": [f"src/item_{index}.py"],
            "acceptance_command": f"pytest tests/test_item_{index}.py -q",
            "withheld_audit_sha256": sha256_bytes(canonical_json({"audit": index})),
        }
        for index in range(1, 11)
    ]
    plan = {
        "schema": PLAN_SCHEMA,
        "pilot_id": "axm-core-feasibility-001",
        "protocol_commit": PROTOCOL,
        "backend_manifest_sha256": backend_sha,
        "target_remote": "https://example.invalid/axm-core.git",
        "default_branch": "main",
        "audit_normalization_profile": profile or {"path": "pilot/audit-profile.json", "sha256": "d" * 64},
        "real_billed_tolerance_fraction": 0.01,
        "intervention_log_path": "pilot/interventions.jsonl",
        "follow_up_days": 14,
        "audit_label_seed_commitment_sha256": sha256_bytes(SEED),
        "residual_order_enumeration": list(RESIDUAL_ORDERS),
        "tasks": tasks,
        "schedule": [],
    }
    plan["schedule"] = derive_schedule(tasks, PROTOCOL)
    return plan


def _git(root: Path, *args: str, date: str | None = None) -> str:
    env = None
    if date is not None:
        import os
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
            "GIT_AUTHOR_NAME": "Pilot Fixture", "GIT_AUTHOR_EMAIL": "pilot@example.invalid",
            "GIT_COMMITTER_NAME": "Pilot Fixture", "GIT_COMMITTER_EMAIL": "pilot@example.invalid",
        })
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _commit(root: Path, message: str, date: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message, date=date)
    return _git(root, "rev-parse", "HEAD")


def _empty_commit(root: Path, message: str, date: str) -> str:
    _git(root, "commit", "--allow-empty", "-m", message, date=date)
    return _git(root, "rev-parse", "HEAD")


def _git_bound_artifact(root: Path, relative: str, commit: str, anchor: str) -> dict:
    raw = (root / relative).read_bytes()
    return {
        "path": relative, "sha256": sha256_bytes(raw),
        "git_proof": {
            "commit_oid": commit, "path": relative,
            "blob_oid": _git(root, "rev-parse", f"{commit}:{relative}"),
            "anchor_commit_oid": anchor,
        },
    }


def _call(
    task_id: str,
    arm: str,
    dispatch_sha: str,
    backend_sha: str,
    backend: dict,
    prompt_sha: str,
    *,
    cost_basis: str = "subscription-derived",
) -> dict:
    return {
        "ts": "2026-01-01T00:00:00Z",
        "account": backend["account"],
        "model": backend["model_id"],
        "tier": backend["tier"],
        "task_id": task_id,
        "phase": arm,
        "outcome": "pass",
        "effort": backend["effort"],
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0 if cost_basis != "real-billed" else 0.25,
        "latency_ms": 1,
        "trial": 1,
        "note": cost_basis,
        "extra": {
            "backend_manifest_sha256": backend_sha,
            "backend_surface": backend["surface"],
            "cost_basis": cost_basis,
            "dispatch_receipt_sha256": dispatch_sha,
            "prompt_template_sha256": prompt_sha,
            "runtime_model_id": backend["model_id"],
            "session_id": f"session-{task_id}-{arm}",
            "telemetry_complete": True,
            "tool_versions": {"fixture": "1"},
        },
    }


def _manifest(root: Path, *, real_billed: bool = False) -> tuple[dict, dict, dict]:
    template_names = ["driver-a", "driver-b", "hands", "repair-a", "repair-b", "repair-c", "question", "resume"]
    templates = {}
    for name in template_names:
        markers = "{{TASK}}\n{{FILES}}\n{{ACCEPTANCE}}\n{{BASE_COMMIT}}\n"
        if name == "hands":
            markers += "{{DRIVER_PLAN}}\n"
        elif name.startswith("repair"):
            markers += "{{CANDIDATE_OUTPUT}}\n{{FAILED_ACCEPTANCE_REPORT}}\n"
        elif name == "question":
            markers = "{{TASK_ID}}\n{{QUESTION}}\n{{EVIDENCE_SHA256}}\n"
        elif name == "resume":
            markers += "{{QUESTION}}\n{{ANSWER}}\n{{CANDIDATE_OUTPUT}}\n{{FAILED_ACCEPTANCE_REPORT}}\n"
        raw = f"fixture template {name}\n{markers}".encode()
        relative = f"pilot/templates/{name}.txt"
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(raw)
        templates[name] = {"path": f"templates/{name}.txt", "sha256": sha256_bytes(raw)}
    cheap = {
        "model_id": "cheap-model", "effort": "low", "surface": "fixture",
        "cost_basis": "real-billed" if real_billed else "subscription-derived",
        "account": "pilot-api" if real_billed else "pilot-subscription",
        "tier": "cheap", "adapter": {"command": ["fixture", "{dispatch_receipt}", "{prompt}", "{result}", "{worktree}"]},
    }
    frontier = {
        "model_id": "frontier-model", "effort": "high", "surface": "fixture",
        "cost_basis": "subscription-derived", "account": "pilot-subscription",
        "tier": "frontier", "adapter": {"command": ["fixture", "{dispatch_receipt}", "{prompt}", "{result}", "{worktree}"]},
    }
    manifest = {
        "schema": "tier-bench/pilot-backends@2", "protocol_commit": PROTOCOL,
        "isolation": {"fresh_session_per_call": True, "instruction_files": False, "auto_memory": False, "conversation_carryover": False},
        "tool_versions": {"fixture": "1"}, "acceptance_tool_versions": {"pytest": "1"},
        "prompt_templates": templates,
        "backends": {"frontier": frontier, "cheap": cheap},
        "arms": {
            "arm_a": {"mode": "frontier_driver", "driver": {"backend": "frontier", "prompt_template": "driver-a"}, "hands": {"backend": "cheap", "prompt_template": "hands"}, "repair": {"backend": "frontier", "prompt_template": "repair-a", "max_calls": 1}, "escalations": [], "driver_trace": {"required": True, "path": "driver_traces.jsonl"}},
            "arm_b": {"mode": "cheap_driver", "driver": {"backend": "cheap", "prompt_template": "driver-b"}, "hands": {"backend": "cheap", "prompt_template": "hands"}, "repair": {"backend": "cheap", "prompt_template": "repair-b", "max_calls": 1}, "escalations": []},
            "arm_c": {"mode": "operator_routed", "hands": {"backend": "cheap", "prompt_template": "hands"}, "repair": {"backend": "cheap", "prompt_template": "repair-c", "max_calls": 1}, "escalations": [], "question_route": {"question_template": "question", "resume_prompt_template": "resume", "max_questions": 2}},
        },
    }
    artifact = _relative_artifact(root, "pilot/manifest.json", canonical_json(manifest))
    profile = _relative_artifact(
        root, "pilot/audit-profile.json",
        canonical_json({
            "schema": "tier-bench/tier-pilot-audit-normalization-profile@1",
            "normalizer": "builtin-terminal-state-projection@1",
        }),
    )
    return manifest, artifact, profile


def _compose_run(
    root: Path,
    composition,
    manifest: dict,
    manifest_sha: str,
    task: dict,
    scheduled: dict,
    *,
    route_question: bool = False,
    intervention_id: str = "12345678-1234-4234-8234-123456789abc",
    artifact_variant: str = "",
) -> tuple[dict, datetime]:
    arm = scheduled["arm"]
    prefix = f"artifacts/{task['task_id']}/{arm}{artifact_variant}"
    state_path = root / f"{prefix}/state.jsonl"
    state = new_pilot_arm_state(
        composition, task_id=task["task_id"], task_tier="fixture", arm=arm,
        task=task["task"], files=task["files"],
        acceptance_command=task["acceptance_command"], base_commit=task["base_commit"],
    )
    write_state(state_path, composition, state)
    dispatch_refs = []
    call_refs = []
    provider_refs = []
    ledger_calls = []
    call_ordinal = 0
    question_routed = False
    while state["next_stage"] in {"driver_plan", "hands", "hands_resume"}:
        call_ordinal += 1
        stage = state["next_stage"]
        arm_spec = manifest["arms"][arm]
        if stage == "driver_plan":
            stage_spec = arm_spec["driver"]
        elif stage == "hands_resume":
            stage_spec = {
                "backend": arm_spec["hands"]["backend"],
                "prompt_template": arm_spec["question_route"]["resume_prompt_template"],
            }
        else:
            stage_spec = arm_spec["hands"]
        backend_name = stage_spec["backend"]
        template_name = stage_spec["prompt_template"]
        backend = manifest["backends"][backend_name]
        template_sha = manifest["prompt_templates"][template_name]["sha256"]
        call_id = f"call-{task['task_id']}-{arm}-{call_ordinal}"
        prompt_sha = sha256_bytes(render_next_prompt(composition, state))
        dispatch_payload = {
            "schema": "tier-bench/tier-pilot-dispatch-receipt@1",
            "call_id": call_id, "task_id": task["task_id"], "arm": arm,
            "stage": stage, "attempt": 1, "backend": backend_name,
            "prompt_template": {"name": template_name, "sha256": template_sha},
            "prompt_sha256": prompt_sha, "base_commit": task["base_commit"],
            "task_sha256": sha256_bytes(task["task"].encode()), "files": task["files"],
            "acceptance_sha256": sha256_bytes(task["acceptance_command"].encode()),
            "composition_manifest_sha256": manifest_sha,
        }
        dispatch = _relative_artifact(
            root, f"{prefix}/dispatch-{call_ordinal}.json", canonical_json(dispatch_payload)
        )
        ledger_call = _call(
            task["task_id"], arm, dispatch["sha256"], manifest_sha, backend,
            template_sha, cost_basis=backend["cost_basis"],
        )
        is_question = route_question and arm == "arm_c" and stage == "hands" and not question_routed
        ledger_call["ts"] = (
            "2025-12-31T23:59:59Z" if is_question
            else f"2026-01-01T00:00:{call_ordinal:02d}Z"
        )
        if is_question:
            ledger_call["outcome"] = "partial"
        output_text = (
            "Choose the exact policy interpretation" if is_question
            else "fixture plan" if stage == "driver_plan" else "fixture patch"
        )
        call_payload = {
            "schema": "tier-bench/pilot-call-receipt@1", "call_id": call_id,
            "task_id": task["task_id"], "arm": arm, "stage": stage, "attempt": 1,
            "backend": backend_name,
            "prompt_template": {"name": template_name, "sha256": template_sha},
            "prompt_sha256": prompt_sha, "dispatch_receipt_sha256": dispatch["sha256"],
            "session_id": ledger_call["extra"]["session_id"] + f"-{call_ordinal}",
            "outcome": "question" if is_question else "completed",
            "output": {"kind": "question" if is_question else "plan" if stage == "driver_plan" else "candidate_patch",
                       "text": output_text, "sha256": sha256_bytes(output_text.encode())},
            "ledger_call": ledger_call,
        }
        call_payload["ledger_call"]["extra"]["session_id"] = call_payload["session_id"]
        state = record_pilot_call(composition, state, call_payload)
        write_state(state_path, composition, state)
        call_refs.append(_relative_artifact(
            root, f"{prefix}/call-{call_ordinal}.json", canonical_json(call_payload)
        ))
        provider_raw = _relative_artifact(
            root, f"{prefix}/provider-{call_ordinal}.raw",
            canonical_json({"output": output_text}),
        )
        provider_result = _relative_artifact(
            root, f"{prefix}/provider-{call_ordinal}.json",
            canonical_json({
                "schema": "tier-bench/tier-backend-result@1",
                "calls": [ledger_call],
                "pilot_output": {
                    "outcome": "question" if is_question else "completed",
                    "text": output_text,
                },
                "artifacts": [{
                    "name": "provider_raw", "path": provider_raw["path"],
                    "sha256": provider_raw["sha256"],
                }],
            }),
        )
        provider_refs.append(_relative_artifact(
            root, f"{prefix}/provider-{call_ordinal}-evidence.json",
            canonical_json({
                "schema": "tier-bench/tier-pilot-production-provider-evidence@1",
                "executor_identity": "tier-bench/pilot-production-adapter@1",
                "activation_commit": "a" * 40,
                "activation_sha256": "b" * 64,
                "call_id": call_id,
                "dispatch_receipt_sha256": dispatch["sha256"],
                "provider_result": provider_result,
                "raw_artifacts": [{"name": "provider_raw", **provider_raw}],
            }),
        ))
        dispatch_refs.append(dispatch)
        ledger_calls.append(ledger_call)
        if is_question:
            question_routed = True
            fixed_now = pilot_composition._now
            pilot_composition._now = lambda: "2026-01-01T00:00:05Z"
            try:
                state = answer_operator_question(
                    composition, state, question_id=state["active_question_id"],
                    answer="Use the literal interpretation", intervention_id=intervention_id,
                )
            finally:
                pilot_composition._now = fixed_now
            write_state(state_path, composition, state)
    assert state["next_stage"] == "acceptance"
    candidate = state["calls"][-1]
    acceptance = {
        "schema": "tier-bench/tier-pilot-acceptance-receipt@1", "receipt_sha256": "",
        "task_id": task["task_id"], "arm": arm, "attempt": 1,
        "causal_call_id": candidate["call_id"], "base_commit": task["base_commit"],
        "command": task["acceptance_command"],
        "command_sha256": sha256_bytes(task["acceptance_command"].encode()),
        "candidate_patch_sha256": candidate["output"]["sha256"],
        "candidate_tree_sha256": "e" * 64, "exit_code": 0, "passed": True,
        "report": "fixture acceptance passed", "report_sha256": sha256_bytes(b"fixture acceptance passed"),
        "stdout_sha256": sha256_bytes(b""), "stderr_sha256": sha256_bytes(b""),
        "tool_versions": manifest["acceptance_tool_versions"],
        "recorded_at": "2026-01-01T00:00:30Z",
    }
    acceptance["receipt_sha256"] = acceptance_receipt_hash(acceptance)
    state = record_acceptance(composition, state, acceptance)
    write_state(state_path, composition, state)
    acceptance_ref = _relative_artifact(root, f"{prefix}/acceptance.json", canonical_json(acceptance))
    acceptance_stdout = _relative_artifact(root, f"{prefix}/acceptance.stdout", b"")
    acceptance_stderr = _relative_artifact(root, f"{prefix}/acceptance.stderr", b"")
    candidate_raw = candidate["output"]["text"].encode("utf-8")
    candidate_before = _relative_artifact(root, f"{prefix}/candidate.before.patch", candidate_raw)
    candidate_after = _relative_artifact(root, f"{prefix}/candidate.after.patch", candidate_raw)
    acceptance_report = _relative_artifact(
        root, f"{prefix}/acceptance-report.txt", acceptance["report"].encode("utf-8")
    )
    acceptance_evidence = _relative_artifact(
        root, f"{prefix}/acceptance-evidence.json",
        canonical_json({
            "schema": "tier-bench/tier-pilot-production-acceptance-evidence@1",
            "executor_identity": "tier-bench/pilot-production-adapter@1",
            "activation_commit": "a" * 40,
            "activation_sha256": "b" * 64,
            "receipt_sha256": acceptance["receipt_sha256"], "receipt": acceptance_ref,
            "stdout": acceptance_stdout, "stderr": acceptance_stderr,
            "candidate_before": candidate_before, "candidate_after": candidate_after,
            "report": acceptance_report,
        }),
    )
    state_ref = {"path": f"{prefix}/state.jsonl", "sha256": sha256_file(state_path)}
    ledger = _relative_artifact(
        root, f"{prefix}/ledger.jsonl", b"".join(canonical_json(call) for call in ledger_calls)
    )
    seal_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=scheduled["sequence"])
    question_refs = [
        _relative_artifact(
            root, f"{prefix}/question-{index}.json", canonical_json(receipt)
        )
        for index, receipt in enumerate(state["question_receipts"], 1)
    ]
    driver_trace = None
    if arm == "arm_a":
        driver_trace = _relative_artifact(
            root, f"{prefix}/driver-trace.jsonl",
            b"".join(canonical_json(trace) for trace in state["driver_traces"]),
        )
    run = {
        "task_id": task["task_id"], "arm": arm, "sequence": scheduled["sequence"],
        "position": scheduled["position"], "base_commit": task["base_commit"],
        "sealed_at": seal_time.isoformat().replace("+00:00", "Z"),
        "final_state": "ACCEPTED", "protocol_valid": True,
        "composition_state": state_ref, "call_receipts": call_refs,
        "dispatch_receipts": dispatch_refs, "provider_receipts": provider_refs,
        "acceptance_receipts": [acceptance_evidence], "question_receipts": question_refs,
        "driver_trace": driver_trace, "ledger": ledger,
    }
    seal_payload = {
        "schema": "tier-bench/pilot-arm-seal@1", "task_id": run["task_id"], "arm": arm,
        "base_commit": run["base_commit"], "sequence": run["sequence"], "position": run["position"],
        "sealed_at": run["sealed_at"], "final_state": run["final_state"], "protocol_valid": True,
        "composition_state_sha256": state_ref["sha256"],
        "question_receipt_sha256s": sorted(ref["sha256"] for ref in question_refs),
        "driver_trace_sha256": driver_trace["sha256"] if driver_trace else None,
    }
    run["arm_seal"] = _relative_artifact(root, f"{prefix}/seal.json", canonical_json(seal_payload))
    return run, seal_time


def _audit(
    plan: dict, task_id: str, final_seal: datetime, withheld_audit: dict
) -> dict:
    label_map = {
        arm: audit_label(SEED, plan["pilot_id"], task_id, arm) for arm in ARMS
    }
    scores = sorted(
        [
            {
                "opaque_label": label_map[arm],
                "repository_ci": True,
                "scope_ok": True,
                "operator_accepted": True,
                "escaped_defects": 0,
            }
            for arm in ARMS
        ],
        key=lambda row: row["opaque_label"],
    )
    closes = final_seal + timedelta(days=14)
    return {
        "task_id": task_id,
        "withheld_audit": withheld_audit,
        "final_arm_sealed_at": final_seal.isoformat().replace("+00:00", "Z"),
        "followup_closes_at": closes.isoformat().replace("+00:00", "Z"),
        "scores": scores,
        "scores_sha256": sha256_bytes(canonical_json(scores)),
        "scores_sealed_at": (closes + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "unblinded_at": (closes + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "label_map": label_map,
    }


def _fixture(root: Path, *, real_billed: bool = False) -> tuple[Path, Path, dict, dict]:
    root.mkdir(parents=True, exist_ok=True)
    cached = _FIXTURE_CACHE.get(real_billed)
    if cached is not None and cached.resolve() != root.resolve():
        clone = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "clone", "--quiet", "--shared", str(cached), str(root)],
            capture_output=True, text=True,
        )
        if clone.returncode:
            raise AssertionError(clone.stderr)
        _git(root, "remote", "set-url", "origin", "https://example.invalid/axm-core.git")
        shutil.copy2(cached / "evidence.json", root / "evidence.json")
        cached_bill = cached / "pilot" / "bill-pilot-api.json"
        if cached_bill.is_file():
            (root / "pilot").mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_bill, root / "pilot" / cached_bill.name)
        cached_provider = cached / "pilot" / "provider-pilot-api.json"
        if cached_provider.is_file():
            (root / "pilot").mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_provider, root / "pilot" / cached_provider.name)
        plan_path = root / "plan.json"
        evidence_path = root / "evidence.json"
        return (
            plan_path, evidence_path,
            json.loads(plan_path.read_text(encoding="utf-8")),
            json.loads(evidence_path.read_text(encoding="utf-8")),
        )
    _git(root, "init", "-b", "main")
    _git(root, "remote", "add", "origin", "https://example.invalid/axm-core.git")
    manifest, manifest_artifact, profile = _manifest(root, real_billed=real_billed)
    base_commit = _commit(root, "freeze model and audit instruments", "2025-12-31T23:55:00Z")
    plan = _plan(manifest_artifact["sha256"], base_commit, profile)
    plan_path = root / "plan.json"
    plan_raw = canonical_json(plan)
    plan_path.write_bytes(plan_raw)
    _commit(root, "freeze pilot plan", "2025-12-31T23:56:00Z")
    authorization_payload = {
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": plan["pilot_id"], "plan_sha256": sha256_bytes(plan_raw),
        "backend_manifest_sha256": manifest_artifact["sha256"],
        "protocol_commit": plan["protocol_commit"], "authority": "operator",
        "authorized": True, "ratified_at": "2025-12-31T23:57:00Z",
    }
    _relative_artifact(
        root, "pilot/operator-authorization.json", canonical_json(authorization_payload)
    )
    ratification_commit = _commit(root, "record exact pilot ratification", "2025-12-31T23:57:00Z")
    _git(root, "commit", "--allow-empty", "-m", "anchor dispatch custody", date="2025-12-31T23:58:00Z")
    dispatch_anchor = _git(root, "rev-parse", "HEAD")
    authorization = _git_bound_artifact(
        root, "pilot/operator-authorization.json", ratification_commit, dispatch_anchor
    )
    interventions = root / plan["intervention_log_path"]
    interventions.parent.mkdir(parents=True, exist_ok=True)
    interventions.write_bytes(b"")
    arm_runs = []
    task_by_id = {task["task_id"]: task for task in plan["tasks"]}
    seals_by_task: dict[str, list[datetime]] = {task_id: [] for task_id in task_by_id}
    composition = load_pilot_composition(root / manifest_artifact["path"])
    original_now = pilot_composition._now
    pilot_composition._now = lambda: "2026-01-01T00:00:00Z"
    try:
        for scheduled in plan["schedule"]:
            task = task_by_id[scheduled["task_id"]]
            run, seal_time = _compose_run(
                root, composition, manifest, manifest_artifact["sha256"], task, scheduled
            )
            arm_runs.append(run)
            seals_by_task[task["task_id"]].append(seal_time)
    finally:
        pilot_composition._now = original_now
    audit_parts: dict[str, dict] = {}
    run_by_coordinate = {(run["task_id"], run["arm"]): run for run in arm_runs}
    for task_index, task in enumerate(plan["tasks"], 1):
        withheld = _relative_artifact(
            root,
            f"audits/{task['task_id']}.json",
            canonical_json({"audit": task_index}),
        )
        entries = []
        for arm in ARMS:
            opaque = audit_label(SEED, plan["pilot_id"], task["task_id"], arm)
            run = run_by_coordinate[(task["task_id"], arm)]
            state = read_state(composition, root / run["composition_state"]["path"])
            normalized_output = _relative_artifact(
                root, f"audits/{task['task_id']}/normalized-{opaque}.json",
                canonical_json(audit_normalized_payload(
                    plan["pilot_id"], task["task_id"], opaque, profile["sha256"], state,
                )),
            )
            entries.append({
                "opaque_label": opaque,
                "artifact": normalized_output,
            })
        entries.sort(key=lambda entry: entry["opaque_label"])
        labels = [entry["opaque_label"] for entry in entries]
        normalized_payload = {
            "schema": "tier-bench/tier-pilot-audit-inputs@1", "pilot_id": plan["pilot_id"],
            "task_id": task["task_id"], "profile_sha256": profile["sha256"], "entries": entries,
        }
        normalized_path = f"audits/{task['task_id']}/normalized-inputs.json"
        _relative_artifact(root, normalized_path, canonical_json(normalized_payload))
        audit_parts[task["task_id"]] = {
            "task": task, "withheld": withheld, "labels": labels,
            "normalized_path": normalized_path,
        }
    normalized_commit = _commit(root, "seal blinded normalized audit inputs", "2026-01-15T01:00:00Z")
    for task_id, part in audit_parts.items():
        scores = [
            {"opaque_label": label, "repository_ci": True, "scope_ok": True,
             "operator_accepted": False, "escaped_defects": 0}
            for label in part["labels"]
        ]
        normalized_sha = sha256_file(root / part["normalized_path"])
        score_payload = {
            "schema": "tier-bench/tier-pilot-audit-scores@1", "pilot_id": plan["pilot_id"],
            "task_id": task_id, "normalized_inputs_sha256": normalized_sha,
            "scores": scores, "sealed_at": "2026-01-15T01:01:00Z",
        }
        score_path = f"audits/{task_id}/scores.json"
        _relative_artifact(root, score_path, canonical_json(score_payload))
        part["score_path"] = score_path
    score_commit = _commit(root, "seal blinded audit scores", "2026-01-15T01:01:00Z")
    seal_by_coordinate = {
        (run["task_id"], run["arm"]): run["arm_seal"]["sha256"] for run in arm_runs
    }
    for task_id, part in audit_parts.items():
        reveal_payload = {
            "schema": "tier-bench/tier-pilot-audit-reveal@1", "pilot_id": plan["pilot_id"],
            "task_id": task_id, "score_commitment_sha256": sha256_file(root / part["score_path"]),
            "seed_hex": SEED.hex(),
            "label_map": {
                arm: {"opaque_label": audit_label(SEED, plan["pilot_id"], task_id, arm),
                      "source_seal_sha256": seal_by_coordinate[(task_id, arm)]}
                for arm in ARMS
            },
            "revealed_at": "2026-01-15T01:02:00Z",
        }
        reveal_path = f"audits/{task_id}/reveal.json"
        _relative_artifact(root, reveal_path, canonical_json(reveal_payload))
        part["reveal_path"] = reveal_path
    reveal_commit = _commit(root, "reveal audit label mapping", "2026-01-15T01:02:00Z")
    audits = []
    for task_id, part in audit_parts.items():
        final = max(seals_by_task[task_id])
        audits.append({
            "task_id": task_id, "withheld_audit": part["withheld"],
            "final_arm_sealed_at": final.isoformat().replace("+00:00", "Z"),
            "followup_closes_at": (final + timedelta(days=14)).isoformat().replace("+00:00", "Z"),
            "normalized_inputs": _git_bound_artifact(root, part["normalized_path"], normalized_commit, reveal_commit),
            "score_commitment": _git_bound_artifact(root, part["score_path"], score_commit, reveal_commit),
            "mapping_reveal": _git_bound_artifact(root, part["reveal_path"], reveal_commit, reveal_commit),
        })
    bill = None
    provider_artifact = None
    if real_billed:
        provider_artifact = _relative_artifact(
            root, "pilot/provider-pilot-api.json",
            canonical_json({"account": "pilot-api", "currency": "USD", "total_usd": 10.0}),
        )
        bill = _relative_artifact(
            root, "pilot/bill-pilot-api.json",
            canonical_json({
                "schema": "tier-bench/tier-pilot-bill@1", "account": "pilot-api",
                "currency": "USD", "period": "2026-01", "total_usd": 10.0,
                "provider_artifact_sha256": provider_artifact["sha256"],
            }),
        )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "pilot_id": plan["pilot_id"],
        "plan_sha256": sha256_bytes(plan_raw),
        "backend_manifest": manifest_artifact,
        "intervention_log": {
            "path": plan["intervention_log_path"],
            "sha256": sha256_file(interventions),
            "head_sha256": None,
        },
        "arm_runs": arm_runs,
        "voids": [],
        "audit_seed_reveal_hex": SEED.hex(),
        "audits": audits,
        "operator_authorization": authorization,
        "cost_reconciliation": [
            {"account": "pilot-api", "billed_usd": 10.0, "bill": bill,
             "provider_artifact": provider_artifact}
        ] if real_billed else [],
    }
    evidence_path = root / "evidence.json"
    evidence_path.write_bytes(canonical_json(evidence))
    # Cache a pristine sibling clone, never the directory returned to a test.
    # Negative tests mutate their fixture aggressively; caching that live root
    # makes targeted selection order-dependent and can poison every later case.
    cache_root = root.parent / (
        ".tier-pilot-admin-cache-real" if real_billed
        else ".tier-pilot-admin-cache-subscription"
    )
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cached = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "clone", "--quiet", "--shared", str(root), str(cache_root)],
        capture_output=True,
        text=True,
    )
    if cached.returncode:
        raise AssertionError(cached.stderr)
    shutil.copy2(evidence_path, cache_root / "evidence.json")
    for relative in ("pilot/bill-pilot-api.json", "pilot/provider-pilot-api.json"):
        source = root / relative
        if source.is_file():
            target = cache_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    _FIXTURE_CACHE[real_billed] = cache_root
    return plan_path, evidence_path, plan, evidence


def _rewrite(path: Path, value: dict) -> None:
    path.write_bytes(canonical_json(value))


def _reseal_audit_chain(root: Path, evidence: dict) -> None:
    normalized_commit = _commit(
        root, "reseal blinded normalized audit inputs", "2026-01-15T01:05:00Z"
    )
    for audit in evidence["audits"]:
        normalized_sha = sha256_file(root / audit["normalized_inputs"]["path"])
        score_path = root / audit["score_commitment"]["path"]
        score = json.loads(score_path.read_text(encoding="utf-8"))
        score["normalized_inputs_sha256"] = normalized_sha
        score_path.write_bytes(canonical_json(score))
    score_commit = _commit(root, "reseal blinded audit scores", "2026-01-15T01:06:00Z")
    for audit in evidence["audits"]:
        score_path = root / audit["score_commitment"]["path"]
        reveal_path = root / audit["mapping_reveal"]["path"]
        reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
        reveal["score_commitment_sha256"] = sha256_file(score_path)
        reveal["revealed_at"] = "2026-01-15T01:07:00Z"
        reveal_path.write_bytes(canonical_json(reveal))
    reveal_commit = _commit(root, "reseal audit label mapping", "2026-01-15T01:07:00Z")
    for audit in evidence["audits"]:
        audit["normalized_inputs"] = _git_bound_artifact(
            root, audit["normalized_inputs"]["path"], normalized_commit, reveal_commit
        )
        audit["score_commitment"] = _git_bound_artifact(
            root, audit["score_commitment"]["path"], score_commit, reveal_commit
        )
        audit["mapping_reveal"] = _git_bound_artifact(
            root, audit["mapping_reveal"]["path"], reveal_commit, reveal_commit
        )


def _rewrite_first_call(root: Path, evidence: dict, mutate) -> None:
    run = evidence["arm_runs"][0]
    call_path = root / run["call_receipts"][0]["path"]
    call = json.loads(call_path.read_text(encoding="utf-8"))
    mutate(call)
    call_path.write_bytes(canonical_json(call))
    run["call_receipts"][0]["sha256"] = sha256_file(call_path)
    ledger_path = root / run["ledger"]["path"]
    ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
    ledger_rows[0] = call["ledger_call"]
    ledger_path.write_bytes(b"".join(canonical_json(row) for row in ledger_rows))
    run["ledger"]["sha256"] = sha256_file(ledger_path)


def _must_refuse(
    plan_path: Path,
    evidence_path: Path,
    needle: str,
    *,
    as_of: datetime = datetime(2026, 1, 20, tzinfo=UTC),
) -> None:
    try:
        close_pilot(plan_path, evidence_path, as_of=as_of)
    except PilotError as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f"closeout accepted evidence expected to fail with {needle!r}")


def test_schedule_is_exact_and_balanced() -> None:
    plan = _plan()
    assert validate_plan(plan) == []
    rows = plan["schedule"]
    assert len(rows) == 30
    for task_id in sorted(task["task_id"] for task in plan["tasks"]):
        task_rows = [row for row in rows if row["task_id"] == task_id]
        assert {row["arm"] for row in task_rows} == set(ARMS)
        assert {row["base_commit"] for row in task_rows} == {BASE}
    first_nine = sorted(plan["tasks"], key=lambda row: row["task_id"])[:9]
    for index, task in enumerate(first_nine):
        task_rows = [row for row in rows if row["task_id"] == task["task_id"]]
        assert "".join(arm[-1].upper() for arm in [row["arm"] for row in task_rows]) == (
            "ABC", "BCA", "CAB"
        )[index % 3]


def test_plan_refuses_wrong_count_and_enumeration() -> None:
    plan = _plan()
    plan["tasks"].pop()
    errors = validate_plan(plan)
    assert any("exactly 10" in error for error in errors)
    plan = _plan()
    plan["residual_order_enumeration"] = list(reversed(RESIDUAL_ORDERS))
    errors = validate_plan(plan)
    assert any("GATED proposal" in error for error in errors)


def test_plan_refuses_hand_edited_schedule() -> None:
    plan = _plan()
    plan["schedule"][0]["arm"] = "arm_c"
    assert any("does not equal" in error for error in validate_plan(plan))


def test_plan_refuses_other_valid_protocol_sha() -> None:
    plan = _plan()
    plan["protocol_commit"] = "1" * 40
    assert any("exact v1.3" in error for error in validate_plan(plan))


def test_complete_closeout_mints_no_scientific_verdict(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, _ = _fixture(root)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["schema"] == CLOSEOUT_SCHEMA
    assert receipt["administrative_state"] == "ADMINISTRATIVELY_COMPLETE"
    assert receipt["completed_tasks"] == 10
    assert receipt["scientific_verdict_minted"] is False
    assert receipt["feasibility_readout_permitted"] is True
    assert receipt["equivalence_claim_permitted"] is False
    assert receipt["noninferiority_claim_permitted"] is False
    assert receipt["ratification_provenance"] == "local_git_object"
    assert receipt["human_identity_authenticated"] is False


def test_four_atomic_voids_demote_to_partial_without_replacement(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    voided = {f"real-{index:02d}" for index in range(1, 5)}
    evidence["arm_runs"] = [
        row for row in evidence["arm_runs"] if row["task_id"] not in voided
    ]
    evidence["audits"] = [row for row in evidence["audits"] if row["task_id"] not in voided]
    for task_id in sorted(voided):
        evidence["voids"].append({
            "task_id": task_id,
            "authority": "derived",
            "reason_code": "other_protocol_fault",
            "trigger_refs": ["missing_all_three_arm_coordinates"],
        })
    _rewrite(evidence_path, evidence)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["administrative_state"] == "PARTIAL"
    assert receipt["completed_tasks"] == 6
    assert receipt["voided_tasks"] == 4
    assert receipt["tasks_total"] == 10
    assert receipt["no_replacement"] is True
    assert receipt["feasibility_readout_permitted"] is False


def test_all_voided_pilot_emits_partial_without_score_commit(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, plan, evidence = _fixture(root)
    ratified_task = "real-01"
    evidence_ref = next(
        audit["withheld_audit"]
        for audit in evidence["audits"]
        if audit["task_id"] == ratified_task
    )
    seal_hashes = sorted(
        run["arm_seal"]["sha256"]
        for run in evidence["arm_runs"]
        if run["task_id"] == ratified_task
    )
    ratification_payload = {
        "schema": "tier-bench/tier-pilot-void-ratification@1",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": sha256_file(plan_path),
        "task_id": ratified_task,
        "reason_code": "other_protocol_fault",
        "evidence_sha256s": [evidence_ref["sha256"]],
        "arm_seal_sha256s": seal_hashes,
    }
    ratification_path = "pilot/void-real-01-all-voided.json"
    _relative_artifact(root, ratification_path, canonical_json(ratification_payload))
    ratification_commit = _commit(
        root, "ratify transparent all-voided closeout", "2026-01-15T01:05:00Z"
    )
    evidence["voids"].append({
        "task_id": ratified_task,
        "authority": "ratified",
        "reason_code": "other_protocol_fault",
        "evidence_refs": [evidence_ref],
        "ratification": _git_bound_artifact(
            root, ratification_path, ratification_commit, ratification_commit
        ),
    })
    derived_tasks = {f"real-{index:02d}" for index in range(2, 11)}
    evidence["arm_runs"] = [
        row for row in evidence["arm_runs"] if row["task_id"] == ratified_task
    ]
    for task_id in sorted(derived_tasks):
        evidence["voids"].append({
            "task_id": task_id,
            "authority": "derived",
            "reason_code": "other_protocol_fault",
            "trigger_refs": ["missing_all_three_arm_coordinates"],
        })
    evidence["audits"] = []
    _rewrite(evidence_path, evidence)

    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["administrative_state"] == "PARTIAL"
    assert receipt["completed_tasks"] == 0
    assert receipt["voided_tasks"] == 10
    assert receipt["tasks_total"] == 10
    assert receipt["no_replacement"] is True
    assert receipt["feasibility_readout_permitted"] is False


def test_missing_arm_without_void_fails_closed(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"].pop()
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not have all three arm seals")


def test_protocol_invalid_arm_requires_whole_task_void(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["protocol_valid"] = False
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "atomically void")


def test_dispatch_ledger_completeness_is_bidirectional(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    extra = _relative_artifact(
        root, "artifacts/real-01/arm_a/extra-dispatch.json", canonical_json({"extra": True})
    )
    evidence["arm_runs"][0]["dispatch_receipts"].append(extra)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "completeness is not bidirectional")


def test_dispatch_cannot_change_frozen_task_packet(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    run = evidence["arm_runs"][0]
    dispatch_path = root / run["dispatch_receipts"][0]["path"]
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    dispatch["task_sha256"] = "0" * 64
    dispatch_path.write_bytes(canonical_json(dispatch))
    run["dispatch_receipts"][0]["sha256"] = sha256_file(dispatch_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "differs from the frozen task packet")


def test_call_must_precede_its_arm_seal(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    _rewrite_first_call(
        root, evidence,
        lambda call: call["ledger_call"].update({"ts": "2026-01-02T00:00:00Z"}),
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "occurred after the arm seal")


def test_call_cannot_predate_operator_authorization(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    _rewrite_first_call(
        root, evidence,
        lambda call: call["ledger_call"].update({"ts": "2025-12-31T23:56:30Z"}),
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "occurred before operator authorization")


def test_ledger_model_must_match_opened_backend_manifest(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    _rewrite_first_call(
        root, evidence, lambda call: call["ledger_call"].update({"model": "other-model"})
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "contradicts the backend manifest")


def test_subscription_call_requires_sealed_call_receipt(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["call_receipts"] = []
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "call_receipts must be non-empty")


def test_provider_raw_evidence_is_mandatory(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["provider_receipts"] = []
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "provider_receipts must cover every call")


def test_acceptance_raw_report_must_match_replayed_receipt(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    run = evidence["arm_runs"][0]
    descriptor_ref = run["acceptance_receipts"][0]
    descriptor_path = root / descriptor_ref["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    report_path = root / descriptor["report"]["path"]
    report_path.write_text("different raw report", encoding="utf-8")
    descriptor["report"]["sha256"] = sha256_file(report_path)
    descriptor_path.write_bytes(canonical_json(descriptor))
    descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "raw report drifted")


def test_fixture_provider_evidence_is_inadmissible(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    descriptor_ref = evidence["arm_runs"][0]["provider_receipts"][0]
    descriptor_path = root / descriptor_ref["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["schema"] = "tier-bench/tier-pilot-fixture-provider-evidence@1"
    descriptor["execution_mode"] = "fixture"
    descriptor["executor_identity"] = "tier-bench/in-process-data-fixture@1"
    descriptor_path.write_bytes(canonical_json(descriptor))
    descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "fixture provider evidence is inadmissible")


def test_all_arms_share_one_production_activation_identity(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    run = evidence["arm_runs"][1]
    for key in ("provider_receipts", "acceptance_receipts"):
        for descriptor_ref in run[key]:
            descriptor_path = root / descriptor_ref["path"]
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["activation_commit"] = "c" * 40
            descriptor["activation_sha256"] = "d" * 64
            descriptor_path.write_bytes(canonical_json(descriptor))
            descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(
        plan_path, evidence_path,
        "all arm runs must share one exact production activation identity",
    )


def test_provider_raw_artifact_bijection_rejects_junk_and_aliases(tmp_path: Path) -> None:
    junk = tmp_path / "junk"
    junk.mkdir()
    plan_path, evidence_path, _, evidence = _fixture(junk)
    descriptor_ref = evidence["arm_runs"][0]["provider_receipts"][0]
    descriptor_path = junk / descriptor_ref["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    result_path = junk / descriptor["provider_result"]["path"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["artifacts"].append("junk")
    result_path.write_bytes(canonical_json(result))
    descriptor["provider_result"]["sha256"] = sha256_file(result_path)
    descriptor_path.write_bytes(canonical_json(descriptor))
    descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "declared_artifacts[1] shape is invalid")

    alias = tmp_path / "alias"
    alias.mkdir()
    plan_path, evidence_path, _, evidence = _fixture(alias)
    descriptor_ref = evidence["arm_runs"][0]["provider_receipts"][0]
    descriptor_path = alias / descriptor_ref["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    result_path = alias / descriptor["provider_result"]["path"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    original = descriptor["raw_artifacts"][0]
    copy_relative = str(Path(original["path"]).with_name("provider-copy.raw")).replace("\\", "/")
    copy_path = alias / copy_relative
    copy_path.write_bytes((alias / original["path"]).read_bytes())
    duplicate = {"name": original["name"], "path": copy_relative, "sha256": sha256_file(copy_path)}
    result["artifacts"].append(duplicate)
    descriptor["raw_artifacts"].append(duplicate)
    result_path.write_bytes(canonical_json(result))
    descriptor["provider_result"]["sha256"] = sha256_file(result_path)
    descriptor_path.write_bytes(canonical_json(descriptor))
    descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, ".name is duplicated")


def test_acceptance_before_after_artifacts_cannot_alias(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    descriptor_ref = evidence["arm_runs"][0]["acceptance_receipts"][0]
    descriptor_path = root / descriptor_ref["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["candidate_after"] = dict(descriptor["candidate_before"])
    descriptor_path.write_bytes(canonical_json(descriptor))
    descriptor_ref["sha256"] = sha256_file(descriptor_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "before/after snapshots must be distinct artifacts")


def test_arm_c_question_requires_exact_intervention_interval(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, plan, evidence = _fixture(root)
    intervention_id = "12345678-1234-4234-8234-123456789abc"
    run_index = next(index for index, item in enumerate(evidence["arm_runs"]) if item["arm"] == "arm_c")
    old_run = evidence["arm_runs"][run_index]
    task = next(item for item in plan["tasks"] if item["task_id"] == old_run["task_id"])
    scheduled = next(
        item for item in plan["schedule"]
        if item["task_id"] == old_run["task_id"] and item["arm"] == "arm_c"
    )
    manifest_path = root / evidence["backend_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    composition = load_pilot_composition(manifest_path)
    original_now = pilot_composition._now
    pilot_composition._now = lambda: "2026-01-01T00:00:00Z"
    try:
        run, _ = _compose_run(
            root, composition, manifest, evidence["backend_manifest"]["sha256"],
            task, scheduled, route_question=True, intervention_id=intervention_id,
            artifact_variant="-question",
        )
    finally:
        pilot_composition._now = original_now
    evidence["arm_runs"][run_index] = run
    question = json.loads((root / run["question_receipts"][0]["path"]).read_text(encoding="utf-8"))
    question_id = question["question_id"]
    audit = next(item for item in evidence["audits"] if item["task_id"] == run["task_id"])
    reveal_path = root / audit["mapping_reveal"]["path"]
    reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
    reveal["label_map"]["arm_c"]["source_seal_sha256"] = run["arm_seal"]["sha256"]
    reveal_path.write_bytes(canonical_json(reveal))
    reveal_commit = _commit(root, "refresh reveal for question fixture", "2026-01-15T01:04:00Z")
    audit["mapping_reveal"] = _git_bound_artifact(
        root, audit["mapping_reveal"]["path"], reveal_commit, reveal_commit
    )
    rows = []
    previous = None
    for event, ts in (("start", "2026-01-01T00:00:01Z"), ("stop", "2026-01-01T00:00:06Z")):
        row = {"arm": "arm_c", "category": "clarification", "event": event,
               "intervention_id": intervention_id, "previous_event_sha256": previous,
               "reference_id": question_id, "task_id": run["task_id"], "ts": ts}
        row["event_sha256"] = event_hash(row)
        previous = row["event_sha256"]
        rows.append(row)
    log_path = root / plan["intervention_log_path"]
    log_path.write_bytes(b"".join(canonical_json(row) for row in rows))
    evidence["intervention_log"].update({"sha256": sha256_file(log_path), "head_sha256": previous})
    _rewrite(evidence_path, evidence)
    assert close_pilot(plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC))
    log_path.write_bytes(b"")
    evidence["intervention_log"].update({"sha256": sha256_file(log_path), "head_sha256": None})
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "has no closed intervention interval")
    return
    call_path = root / run["call_receipts"][0]["path"]
    call = json.loads(call_path.read_text(encoding="utf-8"))
    question_text = "Choose the exact policy interpretation"
    question_sha = sha256_bytes(question_text.encode())
    call["outcome"] = "question"
    call["output"] = {"kind": "question", "text": question_text, "sha256": question_sha}
    call_path.write_bytes(canonical_json(call))
    run["call_receipts"][0]["sha256"] = sha256_file(call_path)
    question_id = sha256_bytes(f"{run['task_id']}:{call['call_id']}:{question_sha}".encode())
    intervention_id = "12345678-1234-4234-8234-123456789abc"
    answered_at = "2026-01-01T00:00:05Z"
    answer = "Use the literal interpretation"
    answer_sha = sha256_bytes(answer.encode())
    state_path = root / run["composition_state"]["path"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["calls"] = [call]
    state["questions"] = [{
        "question_id": question_id, "call_id": call["call_id"], "question": question_text,
        "question_sha256": question_sha, "rendered": question_text,
        "rendered_sha256": question_sha, "question_template_sha256": "f" * 64,
        "answer": answer, "answer_sha256": answer_sha, "answered_at": answered_at,
    }]
    state_path.write_bytes(canonical_json(state))
    run["composition_state"]["sha256"] = sha256_file(state_path)
    question_payload = {
        "schema": "tier-bench/tier-pilot-question-receipt@1", "question_id": question_id,
        "task_id": run["task_id"], "arm": "arm_c", "intervention_id": intervention_id,
        "asked_at": call["ledger_call"]["ts"], "answered_at": answered_at,
        "question_sha256": question_sha, "answer_sha256": answer_sha,
    }
    question_ref = _relative_artifact(
        root, f"artifacts/{run['task_id']}/arm_c/question.json", canonical_json(question_payload)
    )
    run["question_receipts"] = [question_ref]
    seal_path = root / run["arm_seal"]["path"]
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["composition_state_sha256"] = run["composition_state"]["sha256"]
    seal["question_receipt_sha256s"] = [question_ref["sha256"]]
    seal_path.write_bytes(canonical_json(seal))
    run["arm_seal"]["sha256"] = sha256_file(seal_path)
    audit = next(item for item in evidence["audits"] if item["task_id"] == run["task_id"])
    reveal_path = root / audit["mapping_reveal"]["path"]
    reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
    reveal["label_map"]["arm_c"]["source_seal_sha256"] = run["arm_seal"]["sha256"]
    reveal_path.write_bytes(canonical_json(reveal))
    reveal_commit = _commit(root, "refresh reveal for question fixture", "2026-01-15T01:04:00Z")
    audit["mapping_reveal"] = _git_bound_artifact(
        root, audit["mapping_reveal"]["path"], reveal_commit, reveal_commit
    )
    rows = []
    previous = None
    for event, ts in (("start", "2026-01-01T00:00:00Z"), ("stop", "2026-01-01T00:00:10Z")):
        row = {"arm": "arm_c", "category": "clarification", "event": event,
               "intervention_id": intervention_id, "previous_event_sha256": previous,
               "reference_id": question_id, "task_id": run["task_id"], "ts": ts}
        row["event_sha256"] = event_hash(row)
        previous = row["event_sha256"]
        rows.append(row)
    log_path = root / plan["intervention_log_path"]
    log_path.write_bytes(b"".join(canonical_json(row) for row in rows))
    evidence["intervention_log"].update({"sha256": sha256_file(log_path), "head_sha256": previous})
    _rewrite(evidence_path, evidence)
    assert close_pilot(plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC))
    log_path.write_bytes(b"")
    evidence["intervention_log"].update({"sha256": sha256_file(log_path), "head_sha256": None})
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "has no closed intervention interval")


def test_arm_run_must_follow_frozen_schedule(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["arm_runs"][0]["position"] = 3
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "deviates from the frozen schedule")


def test_withheld_audit_commitment_must_open(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    replacement = _relative_artifact(
        root, "audits/replacement.json", canonical_json({"audit": "different"})
    )
    evidence["audits"][0]["withheld_audit"] = replacement
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not open the task commitment")


def test_operator_authorization_binds_exact_plan(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    authorization = {
        "schema": "tier-bench/tier-pilot-authorization@1",
        "pilot_id": evidence["pilot_id"],
        "plan_sha256": "0" * 64,
        "backend_manifest_sha256": evidence["backend_manifest"]["sha256"],
        "protocol_commit": PROTOCOL,
        "authority": "operator",
        "authorized": True,
        "ratified_at": "2025-12-31T23:59:00Z",
    }
    relative = "pilot/operator-authorization.json"
    (root / relative).write_bytes(canonical_json(authorization))
    tampered_commit = _commit(root, "tamper authorization fixture", "2025-12-31T23:59:00Z")
    evidence["operator_authorization"] = _git_bound_artifact(
        root, relative, tampered_commit, tampered_commit
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "plan_sha256 is not ratified")


def test_audit_mapping_and_followup_are_fail_closed(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    reveal_artifact = evidence["audits"][0]["mapping_reveal"]
    reveal_path = root / reveal_artifact["path"]
    reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
    reveal["label_map"]["arm_a"]["opaque_label"] = "audit-" + "0" * 20
    reveal_path.write_bytes(canonical_json(reveal))
    tampered_commit = _commit(root, "tamper reveal fixture", "2026-01-15T01:03:00Z")
    evidence["audits"][0]["mapping_reveal"] = _git_bound_artifact(
        root, reveal_artifact["path"], tampered_commit, tampered_commit
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "label does not match committed seed")
    _, evidence_path, _, evidence = _fixture(root / "early")
    _must_refuse(
        root / "early" / "plan.json",
        evidence_path,
        "follow-up window is still open",
        as_of=datetime(2026, 1, 10, tzinfo=UTC),
    )


def test_score_commit_cannot_already_contain_reveal_path_or_bytes(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    score_commit = _empty_commit(
        root, "invalid score checkpoint after reveal", "2026-01-15T01:05:00Z"
    )
    reveal_commit = _empty_commit(
        root, "empty child reveal checkpoint", "2026-01-15T01:06:00Z"
    )
    for audit in evidence["audits"]:
        audit["score_commitment"] = _git_bound_artifact(
            root, audit["score_commitment"]["path"], score_commit, reveal_commit
        )
        audit["mapping_reveal"] = _git_bound_artifact(
            root, audit["mapping_reveal"]["path"], reveal_commit, reveal_commit
        )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "mapping reveal path already existed at score commit")


def test_all_unvoided_scores_require_one_common_commit(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    later_score = _empty_commit(root, "alternate score checkpoint", "2026-01-15T01:05:00Z")
    later_reveal = _empty_commit(root, "later reveal checkpoint", "2026-01-15T01:06:00Z")
    audit = evidence["audits"][0]
    audit["score_commitment"] = _git_bound_artifact(
        root, audit["score_commitment"]["path"], later_score, later_reveal
    )
    audit["mapping_reveal"] = _git_bound_artifact(
        root, audit["mapping_reveal"]["path"], later_reveal, later_reveal
    )
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "one common score commit")


def test_post_score_ratified_void_cannot_close(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, plan, evidence = _fixture(root)
    task_id = "real-01"
    evidence_ref = next(
        audit["withheld_audit"] for audit in evidence["audits"] if audit["task_id"] == task_id
    )
    seal_hashes = sorted(
        run["arm_seal"]["sha256"] for run in evidence["arm_runs"]
        if run["task_id"] == task_id
    )
    ratification_payload = {
        "schema": "tier-bench/tier-pilot-void-ratification@1",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": sha256_file(plan_path),
        "task_id": task_id,
        "reason_code": "other_protocol_fault",
        "evidence_sha256s": [evidence_ref["sha256"]],
        "arm_seal_sha256s": seal_hashes,
    }
    ratification_path = "pilot/void-real-01.json"
    _relative_artifact(root, ratification_path, canonical_json(ratification_payload))
    ratification_commit = _commit(
        root, "ratify void after scored result", "2026-01-15T01:05:00Z"
    )
    evidence["voids"].append({
        "task_id": task_id,
        "authority": "ratified",
        "reason_code": "other_protocol_fault",
        "evidence_refs": [evidence_ref],
        "ratification": _git_bound_artifact(
            root, ratification_path, ratification_commit, ratification_commit
        ),
    })
    evidence["audits"] = [audit for audit in evidence["audits"] if audit["task_id"] != task_id]
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "strict ancestor of the common score commit")


def test_normalized_artifact_must_be_builtin_terminal_projection(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    audit = evidence["audits"][0]
    normalized_path = root / audit["normalized_inputs"]["path"]
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    artifact_ref = normalized["entries"][0]["artifact"]
    artifact_path = root / artifact_ref["path"]
    artifact_path.write_bytes(canonical_json({"self_hashed_but_unrelated": True}))
    artifact_ref["sha256"] = sha256_file(artifact_path)
    normalized_path.write_bytes(canonical_json(normalized))
    _reseal_audit_chain(root, evidence)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "is not the built-in projection")


def test_normalized_artifacts_exclude_runner_identity_and_reject_causal_id(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    for audit in evidence["audits"]:
        normalized = json.loads(
            (root / audit["normalized_inputs"]["path"]).read_text(encoding="utf-8")
        )
        for entry in normalized["entries"]:
            raw = (root / entry["artifact"]["path"]).read_bytes()
            assert b"arm_a" not in raw
            assert b"arm_b" not in raw
            assert b"arm_c" not in raw
            assert b"causal_call_id" not in raw
            payload = json.loads(raw)
            assert set(payload["acceptance"]) == {
                "receipt_sha256", "candidate_tree_sha256", "passed", "report",
                "report_sha256",
            }

    audit = evidence["audits"][0]
    normalized_path = root / audit["normalized_inputs"]["path"]
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    artifact_ref = normalized["entries"][0]["artifact"]
    artifact_path = root / artifact_ref["path"]
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["acceptance"]["causal_call_id"] = "call-real-01-arm_a-1"
    artifact_path.write_bytes(canonical_json(payload))
    artifact_ref["sha256"] = sha256_file(artifact_path)
    normalized_path.write_bytes(canonical_json(normalized))
    _reseal_audit_chain(root, evidence)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "is not the built-in projection")


def test_normalization_profile_has_no_executable_or_unknown_surface(tmp_path: Path) -> None:
    _fixture(tmp_path / "base")
    for case, profile_value, needle in (
        (
            "executable",
            {
                "schema": "tier-bench/tier-pilot-audit-normalization-profile@1",
                "normalizer": "builtin-terminal-state-projection@1",
                "command": ["python", "normalize.py"],
            },
            "audit_normalization_profile payload fields mismatch",
        ),
        (
            "unknown",
            {
                "schema": "tier-bench/tier-pilot-audit-normalization-profile@1",
                "normalizer": "unknown-normalizer@1",
            },
            "is not the built-in supported algorithm",
        ),
    ):
        root = tmp_path / case
        plan_path, evidence_path, plan, evidence = _fixture(root)
        profile_path = root / plan["audit_normalization_profile"]["path"]
        profile_path.write_bytes(canonical_json(profile_value))
        plan["audit_normalization_profile"]["sha256"] = sha256_file(profile_path)
        plan_path.write_bytes(canonical_json(plan))
        evidence["plan_sha256"] = sha256_file(plan_path)
        _rewrite(evidence_path, evidence)
        _must_refuse(plan_path, evidence_path, needle)


def test_arm_a_driver_trace_is_required_and_replay_derived(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    run = next(run for run in evidence["arm_runs"] if run["arm"] == "arm_a")
    trace_path = root / run["driver_trace"]["path"]
    trace_path.write_bytes(canonical_json({"unrelated": "trace"}))
    run["driver_trace"]["sha256"] = sha256_file(trace_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not equal replay-derived append_driver_traces output")


def test_driver_trace_topology_refuses_missing_wrong_path_and_non_a(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    plan_path, evidence_path, _, evidence = _fixture(root)
    arm_a = next(run for run in evidence["arm_runs"] if run["arm"] == "arm_a")
    arm_a["driver_trace"] = None
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, ".driver_trace must be an object")

    root = tmp_path / "wrong-path"
    plan_path, evidence_path, _, evidence = _fixture(root)
    arm_a = next(run for run in evidence["arm_runs"] if run["arm"] == "arm_a")
    arm_a["driver_trace"]["path"] = "artifacts/absent-driver-trace.jsonl"
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, ".driver_trace.path does not exist")

    root = tmp_path / "non-a"
    plan_path, evidence_path, _, evidence = _fixture(root)
    arm_a = next(run for run in evidence["arm_runs"] if run["arm"] == "arm_a")
    arm_b = next(run for run in evidence["arm_runs"] if run["arm"] == "arm_b")
    arm_b["driver_trace"] = dict(arm_a["driver_trace"])
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "must be null outside Arm A")


def test_real_billed_rows_reconcile_and_drift_refuses(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root, real_billed=True)
    receipt = close_pilot(
        plan_path, evidence_path, as_of=datetime(2026, 1, 20, tzinfo=UTC)
    )
    assert receipt["administrative_state"] == "ADMINISTRATIVELY_COMPLETE"
    evidence["cost_reconciliation"][0]["billed_usd"] = 1.0
    bill_ref = evidence["cost_reconciliation"][0]["bill"]
    bill_path = root / bill_ref["path"]
    bill = json.loads(bill_path.read_text(encoding="utf-8"))
    bill["total_usd"] = 1.0
    bill_path.write_bytes(canonical_json(bill))
    bill_ref["sha256"] = sha256_file(bill_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "does not reconcile")


def test_real_billed_bill_requires_opened_raw_provider_artifact(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root, real_billed=True)
    record = evidence["cost_reconciliation"][0]
    bill_path = root / record["bill"]["path"]
    bill = json.loads(bill_path.read_text(encoding="utf-8"))
    bill["provider_artifact_sha256"] = None
    bill_path.write_bytes(canonical_json(bill))
    record["bill"]["sha256"] = sha256_file(bill_path)
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "must be non-null sha256")


def test_canonical_intervention_path_is_bound(tmp_path: Path) -> None:
    root = tmp_path
    plan_path, evidence_path, _, evidence = _fixture(root)
    evidence["intervention_log"]["path"] = "pilot/another.jsonl"
    _rewrite(evidence_path, evidence)
    _must_refuse(plan_path, evidence_path, "differs from the canonical plan path")


def main() -> int:
    tests = [
        test_schedule_is_exact_and_balanced,
        test_plan_refuses_wrong_count_and_enumeration,
        test_plan_refuses_hand_edited_schedule,
        test_plan_refuses_other_valid_protocol_sha,
        test_complete_closeout_mints_no_scientific_verdict,
        test_four_atomic_voids_demote_to_partial_without_replacement,
        test_all_voided_pilot_emits_partial_without_score_commit,
        test_missing_arm_without_void_fails_closed,
        test_protocol_invalid_arm_requires_whole_task_void,
        test_dispatch_ledger_completeness_is_bidirectional,
        test_dispatch_cannot_change_frozen_task_packet,
        test_call_must_precede_its_arm_seal,
        test_call_cannot_predate_operator_authorization,
        test_ledger_model_must_match_opened_backend_manifest,
        test_subscription_call_requires_sealed_call_receipt,
        test_provider_raw_evidence_is_mandatory,
        test_acceptance_raw_report_must_match_replayed_receipt,
        test_fixture_provider_evidence_is_inadmissible,
        test_all_arms_share_one_production_activation_identity,
        test_provider_raw_artifact_bijection_rejects_junk_and_aliases,
        test_acceptance_before_after_artifacts_cannot_alias,
        test_arm_run_must_follow_frozen_schedule,
        test_withheld_audit_commitment_must_open,
        test_operator_authorization_binds_exact_plan,
        test_audit_mapping_and_followup_are_fail_closed,
        test_score_commit_cannot_already_contain_reveal_path_or_bytes,
        test_all_unvoided_scores_require_one_common_commit,
        test_post_score_ratified_void_cannot_close,
        test_normalized_artifact_must_be_builtin_terminal_projection,
        test_normalized_artifacts_exclude_runner_identity_and_reject_causal_id,
        test_normalization_profile_has_no_executable_or_unknown_surface,
        test_arm_a_driver_trace_is_required_and_replay_derived,
        test_driver_trace_topology_refuses_missing_wrong_path_and_non_a,
        test_real_billed_rows_reconcile_and_drift_refuses,
        test_real_billed_bill_requires_opened_raw_provider_artifact,
        test_canonical_intervention_path_is_bound,
    ]
    parent = Path(tempfile.mkdtemp(prefix="tier-pilot-admin-tests-"))
    try:
        for index, test in enumerate(tests):
            case = parent / f"case-{index}"
            case.mkdir()
            test(case) if test.__code__.co_argcount else test()
        print(f"OK — {len(tests)}/{len(tests)} pilot-admin tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
