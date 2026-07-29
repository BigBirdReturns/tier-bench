"""Normalize Task Computer runs and export Task Floor protocol views.

Exports are compatibility views over one canonical, content-addressed Task Floor
bundle. They do not claim that MCP, A2A, AG-UI, BrowserGym, OpenTelemetry, OPA,
CloudEvents, or in-toto natively enforce the Task Floor constitution.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .playwright_computer_common import (
    PlaywrightComputerError,
    atomic_json,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    safe_relative_path,
    without_hash,
)
from .task_floor_protocol import (
    BUNDLE_SCHEMA,
    TRAJECTORY_SCHEMA,
    validate_cartridge,
    validate_manifest,
    verify_record,
)

AGUI_SCHEMA = "task-floor/ag-ui-export@1"
MCP_EXPORT_SCHEMA = "task-floor/mcp-export@1"
A2A_EXPORT_SCHEMA = "task-floor/a2a-export@1"
OTEL_EXPORT_SCHEMA = "task-floor/opentelemetry-export@1"
IN_TOTO_EXPORT_SCHEMA = "task-floor/in-toto-export@1"
OPA_EXPORT_SCHEMA = "task-floor/opa-export@1"
BROWSERGYM_EXPORT_SCHEMA = "task-floor/browsergym-export@1"
CLOUDEVENTS_EXPORT_SCHEMA = "task-floor/cloudevents-export@1"
AGENTRX_EXPORT_SCHEMA = "task-floor/agentrx-export@1"
CUA_EXPORT_SCHEMA = "task-floor/cua-export@1"
CEDAR_EXPORT_SCHEMA = "task-floor/cedar-export@1"
LANGGRAPH_EXPORT_SCHEMA = "task-floor/langgraph-export@1"
EXPORT_INDEX_SCHEMA = "task-floor/export-index@1"
TASK_FLOOR_EXTENSION_URI = "urn:task-floor:extension:v1"
TASK_FLOOR_PREDICATE_TYPE = "urn:task-floor:run-attestation:v1"
OTEL_GENAI_SCHEMA_URL = "https://opentelemetry.io/schemas/gen-ai/1.42.0"


def _iso_to_nanos(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return str(int(parsed.timestamp() * 1_000_000_000))


def _iso_to_millis(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1000)


def _trace_id(seed: str) -> str:
    return hashlib.sha256(("trace:" + seed).encode()).hexdigest()[:32]


def _span_id(seed: str) -> str:
    return hashlib.sha256(("span:" + seed).encode()).hexdigest()[:16]


def _artifact_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = {part.casefold() for part in relative.parts}
        if "secrets" in parts:
            continue
        rows.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "digest": {"sha256": hash_file(path)},
            }
        )
    return rows


def _load_record(root: Path, record: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PlaywrightComputerError(f"{label} record must be an object")
    path = safe_relative_path(root, str(record.get("path", "")), f"{label} path")
    if not path.is_file():
        raise PlaywrightComputerError(f"{label} file does not exist: {path}")
    if hash_file(path) != record.get("sha256"):
        raise PlaywrightComputerError(f"{label} file hash does not verify: {path}")
    value = load_json(path)
    if not isinstance(value, dict):
        raise PlaywrightComputerError(f"{label} file is not an object: {path}")
    return value


def _load_step_record(run_dir: Path, record: dict[str, Any], label: str) -> dict[str, Any]:
    return _load_record(run_dir / "records", record, label)


def _normalize_step(run_dir: Path, step_record: dict[str, Any]) -> dict[str, Any]:
    step = _load_step_record(run_dir, step_record, "step")
    if not verify_record(step, "step_receipt_sha256"):
        raise PlaywrightComputerError(
            f"step receipt identity does not verify: {step_record.get('path')}"
        )
    packet = _load_step_record(run_dir, step["packet"], "planner packet")
    proposal = _load_step_record(run_dir, step["proposal"], "planner proposal")
    verdict = _load_step_record(run_dir, step["verdict"], "critic verdict")
    if not verify_record(packet, "packet_sha256"):
        raise PlaywrightComputerError("planner packet identity does not verify")
    if not verify_record(proposal, "proposal_sha256"):
        raise PlaywrightComputerError("planner proposal identity does not verify")
    if not verify_record(verdict, "verdict_sha256"):
        raise PlaywrightComputerError("critic verdict identity does not verify")
    return {
        "step_number": int(step["step_number"]),
        "step_receipt_sha256": step["step_receipt_sha256"],
        "started_state_id": step["started_state_id"],
        "completed_state_id": step["completed_state_id"],
        "packet": packet,
        "proposal": proposal,
        "verdict": verdict,
        "actions": step.get("actions", []),
        "planner_memory": step.get("planner_memory", ""),
        "next_goal": step.get("next_goal", ""),
        "done": bool(step.get("done")),
    }


def load_task_computer_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    receipt = load_json(run_dir / "receipt.json")
    if not isinstance(receipt, dict) or not verify_record(receipt, "receipt_sha256"):
        raise PlaywrightComputerError("Task Computer receipt does not verify")
    scenario = load_json(run_dir / "scenario.json")
    cartridge = validate_cartridge(scenario)
    handoff_record = receipt.get("project_handoff", {})
    handoff = _load_record(run_dir, handoff_record, "project handoff")
    if not verify_record(handoff, "handoff_sha256"):
        raise PlaywrightComputerError("project handoff identity does not verify")
    steps = [_normalize_step(run_dir, row) for row in receipt.get("steps", [])]
    if not steps:
        raise PlaywrightComputerError("Task Computer run has no steps")
    return {
        "run_dir": run_dir,
        "receipt": receipt,
        "scenario": scenario,
        "cartridge": cartridge,
        "handoff": handoff,
        "steps": steps,
    }


def _trajectory(run: dict[str, Any]) -> dict[str, Any]:
    receipt = run["receipt"]
    events: list[dict[str, Any]] = []
    previous: str | None = None

    def emit(kind: str, step: dict[str, Any] | None, data: dict[str, Any]) -> None:
        nonlocal previous
        event = {
            "seq": len(events) + 1,
            "kind": kind,
            "run_id": receipt["run_id"],
            "task_id": receipt["scenario_id"],
            "step_number": step["step_number"] if step is not None else None,
            "previous_event_sha256": previous,
            "data": data,
        }
        event["event_sha256"] = hash_json(event)
        previous = event["event_sha256"]
        events.append(event)

    emit(
        "run.started",
        None,
        {
            "started_at": receipt["started_at"],
            "planner": receipt.get("planner"),
            "variant": receipt.get("variant"),
        },
    )
    for step in run["steps"]:
        emit(
            "step.started",
            step,
            {
                "state_id": step["started_state_id"],
                "packet_sha256": step["packet"]["packet_sha256"],
            },
        )
        emit(
            "planner.proposal",
            step,
            {
                "proposal_sha256": step["proposal"]["proposal_sha256"],
                "packet_sha256": step["packet"]["packet_sha256"],
                "state_id": step["proposal"].get("state_id")
                or step["started_state_id"],
                "actions": step["proposal"].get("actions", []),
                "done": step["proposal"].get("done", False),
                "memory": step["proposal"].get("memory", ""),
                "next_goal": step["proposal"].get("next_goal", ""),
            },
        )
        emit(
            "critic.verdict",
            step,
            {
                "verdict_sha256": step["verdict"]["verdict_sha256"],
                "pass": step["verdict"].get("pass"),
                "errors": step["verdict"].get("errors", []),
                "warnings": step["verdict"].get("warnings", []),
                "authority": step["verdict"].get(
                    "authority", "deterministic-policy-critic"
                ),
            },
        )
        for action_index, action in enumerate(step["actions"], 1):
            emit(
                "action.executed",
                step,
                {
                    "action_index": action_index,
                    "surface": action.get("surface"),
                    "action": action.get("action"),
                    "effect": (action.get("action") or {}).get("effect"),
                    "idempotency_key": (
                        f"{receipt['run_id']}:{step['step_number']}:"
                        f"{(action.get('action') or {}).get('id', action_index)}"
                    ),
                    "browser_receipt": action.get("browser_receipt"),
                    "screen_ghost_request": action.get("screen_ghost_request"),
                    "candidate": action.get("candidate"),
                    "completed_state_id": action.get("completed_state_id"),
                    "result": action,
                },
            )
        emit(
            "step.finished",
            step,
            {
                "state_id": step["completed_state_id"],
                "step_receipt_sha256": step["step_receipt_sha256"],
            },
        )
    emit(
        "acceptance.checked",
        None,
        {
            "pass": receipt["status"] == "ACCEPTED",
            "checks": receipt.get("acceptance", []),
            "handoff_sha256": run["handoff"].get("handoff_sha256"),
            "authority": run["cartridge"].get("acceptance_authority"),
        },
    )
    if receipt.get("error"):
        emit(
            "run.failure",
            None,
            {
                "error": receipt.get("error"),
                "failure_category": "execution_or_acceptance",
            },
        )
    emit(
        "run.finished",
        None,
        {
            "completed_at": receipt["completed_at"],
            "status": receipt["status"],
            "receipt_sha256": receipt["receipt_sha256"],
        },
    )
    value = {
        "schema": TRAJECTORY_SCHEMA,
        "trajectory_id": "trajectory-" + receipt["receipt_sha256"][:24],
        "run_id": receipt["run_id"],
        "task_id": receipt["scenario_id"],
        "status": receipt["status"],
        "events": events,
        "event_head_sha256": previous,
    }
    value["trajectory_sha256"] = hash_json(value)
    return value


def _run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    receipt = run["receipt"]
    proposals = sum(len(step["proposal"].get("actions", [])) for step in run["steps"])
    executed = sum(len(step.get("actions", [])) for step in run["steps"])
    human_routes = int(receipt.get("routes", {}).get("human", 0))
    warnings = sum(
        len(step["verdict"].get("warnings", [])) for step in run["steps"]
    )
    failures = 1 if receipt.get("error") else 0
    return {
        "accepted": receipt["status"] == "ACCEPTED",
        "accepted_work_units": 1 if receipt["status"] == "ACCEPTED" else 0,
        "steps": len(run["steps"]),
        "actions_proposed": proposals,
        "actions_executed": executed,
        "critic_warnings": warnings,
        "failures": failures,
        "failure_category": (
            "execution_or_acceptance" if receipt.get("error") else None
        ),
        "human_interventions": human_routes,
        "duration_seconds": receipt.get("duration_seconds"),
        "input_tokens": None,
        "output_tokens": None,
        "model_cost_usd": None,
        "gpu_seconds": None,
        "human_seconds": None,
        "energy_joules": None,
        "accepted_work_per_hour": (
            3600.0 / float(receipt["duration_seconds"])
            if receipt["status"] == "ACCEPTED"
            and receipt.get("duration_seconds")
            else 0.0
        ),
    }


def build_bundle(run_dir: Path, raw_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_manifest(raw_manifest)
    run = load_task_computer_run(run_dir)
    trajectory = _trajectory(run)
    receipt = run["receipt"]
    value: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": "bundle-" + receipt["receipt_sha256"][:24],
        "created_at": now_utc(),
        "manifest": manifest,
        "cartridge": run["cartridge"],
        "run": {
            "run_id": receipt["run_id"],
            "scenario_id": receipt["scenario_id"],
            "project": receipt["project"],
            "variant": receipt["variant"],
            "status": receipt["status"],
            "started_at": receipt["started_at"],
            "completed_at": receipt["completed_at"],
            "duration_seconds": receipt.get("duration_seconds"),
            "receipt_sha256": receipt["receipt_sha256"],
            "routes": receipt.get("routes", {}),
            "promotion_authorized": receipt.get("promotion_authorized", False),
        },
        "metrics": _run_metrics(run),
        "trajectory": trajectory,
        "acceptance": receipt.get("acceptance", []),
        "project_handoff": run["handoff"],
        "claims": {
            "profiles_claimed": manifest["conformance"]["profiles_claimed"],
            "claim_scope": manifest["conformance"]["claim_scope"],
            "production_qualified": manifest["conformance"][
                "production_qualified"
            ],
        },
        "artifacts": _artifact_rows(run["run_dir"]),
        "exports": {},
    }
    value["bundle_sha256"] = hash_json(value)
    return value


def _verify_trajectory(trajectory: Any) -> list[str]:
    if not isinstance(trajectory, dict) or trajectory.get("schema") != TRAJECTORY_SCHEMA:
        return ["bundle trajectory is missing or invalid"]
    errors: list[str] = []
    if trajectory.get("trajectory_sha256") != hash_json(
        without_hash(trajectory, "trajectory_sha256")
    ):
        errors.append("bundle trajectory hash does not verify")
    previous: str | None = None
    events = trajectory.get("events")
    if not isinstance(events, list) or not events:
        errors.append("bundle trajectory has no events")
        return errors
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            errors.append(f"trajectory event {index} is not an object")
            continue
        if event.get("seq") != index:
            errors.append(f"trajectory event {index} has a non-contiguous sequence")
        if event.get("previous_event_sha256") != previous:
            errors.append(f"trajectory event {index} has the wrong previous hash")
        if event.get("event_sha256") != hash_json(without_hash(event, "event_sha256")):
            errors.append(f"trajectory event {index} hash does not verify")
        previous = event.get("event_sha256")
    if trajectory.get("event_head_sha256") != previous:
        errors.append("trajectory event head does not match the final event")
    return errors


def verify_bundle(raw: Any, *, root: Path | None = None) -> list[str]:
    if not isinstance(raw, dict):
        return ["bundle must be an object"]
    errors: list[str] = []
    if raw.get("schema") != BUNDLE_SCHEMA:
        errors.append(f"bundle.schema must be {BUNDLE_SCHEMA}")
    if raw.get("bundle_sha256") != hash_json(without_hash(raw, "bundle_sha256")):
        errors.append("bundle.bundle_sha256 does not match canonical content")
    try:
        normalized = validate_manifest(raw.get("manifest"))
        if raw.get("manifest", {}).get("manifest_sha256") != normalized["manifest_sha256"]:
            errors.append("bundle manifest hash does not verify")
    except Exception as exc:
        errors.append(f"bundle manifest invalid: {exc}")
    try:
        normalized_cartridge = validate_cartridge(raw.get("cartridge"))
        if raw.get("cartridge", {}).get("cartridge_sha256") != normalized_cartridge[
            "cartridge_sha256"
        ]:
            errors.append("bundle cartridge hash does not verify")
    except Exception as exc:
        errors.append(f"bundle cartridge invalid: {exc}")
    errors.extend(_verify_trajectory(raw.get("trajectory")))
    exports = raw.get("exports", {})
    if not isinstance(exports, dict):
        errors.append("bundle.exports must be an object")
    else:
        for key, value in exports.items():
            if not isinstance(value, dict):
                errors.append(f"bundle export {key} is not an object")
            elif value.get("export_sha256") != hash_json(
                without_hash(value, "export_sha256")
            ):
                errors.append(f"bundle export {key} hash does not verify")
    if root is not None:
        root = root.resolve()
        for artifact in raw.get("artifacts", []):
            try:
                path = safe_relative_path(root, artifact["path"], "bundle artifact path")
                if not path.is_file():
                    errors.append(f"bundle artifact is missing: {artifact['path']}")
                elif path.stat().st_size != artifact["bytes"]:
                    errors.append(f"bundle artifact size differs: {artifact['path']}")
                elif hash_file(path) != artifact["digest"]["sha256"]:
                    errors.append(f"bundle artifact hash differs: {artifact['path']}")
            except Exception as exc:
                errors.append(f"bundle artifact invalid: {exc}")
    return errors


def mcp_export(
    manifest: dict[str, Any], cartridge: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    cartridge_value = validate_cartridge(cartridge) if cartridge is not None else None

    def tool(
        name: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        read_only: bool,
        destructive: bool,
        idempotent: bool,
        open_world: bool,
        effects: list[str],
        state_binding: str,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "title": description.split(".")[0],
            "description": description,
            "inputSchema": input_schema,
            "outputSchema": {"type": "object", "additionalProperties": True},
            "annotations": {
                "readOnlyHint": read_only,
                "destructiveHint": destructive,
                "idempotentHint": idempotent,
                "openWorldHint": open_world,
            },
            "execution": {"taskSupport": "optional"},
            "_meta": {
                "task-floor/extension": TASK_FLOOR_EXTENSION_URI,
                "task-floor/effects": effects,
                "task-floor/stateBinding": state_binding,
                "task-floor/manifestSha256": manifest["manifest_sha256"],
                "task-floor/annotationsTrusted": False,
            },
        }

    tools = [
        tool(
            "task_floor_describe",
            "Describe capabilities, authorities, and conformance evidence.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
            effects=["read"],
            state_binding="none",
        ),
        tool(
            "task_floor_observe",
            "Observe the current state and return its content identity.",
            {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=True,
            effects=["read"],
            state_binding="produces",
        ),
        tool(
            "task_floor_act",
            "Execute one state-bound action after trusted effect and approval enforcement.",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "object"},
                    "approval": {"type": ["object", "null"]},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
            effects=manifest["effects"]["taxonomy"],
            state_binding="required",
        ),
        tool(
            "task_floor_takeover",
            "Pause agent actions and grant a state-bound human takeover lease.",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "state_id": {"type": "string"},
                },
                "required": ["task_id", "state_id"],
                "additionalProperties": False,
            },
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=False,
            effects=["privileged"],
            state_binding="required",
        ),
        tool(
            "task_floor_accept",
            "Run the independent acceptance authority and return project handoff evidence.",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "state_id": {"type": "string"},
                },
                "required": ["task_id", "state_id"],
                "additionalProperties": False,
            },
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
            effects=["read"],
            state_binding="required",
        ),
    ]
    value = {
        "schema": MCP_EXPORT_SCHEMA,
        "protocol": "mcp",
        "protocolRevision": "2025-11-25",
        "server": {
            "name": manifest["name"],
            "version": manifest["version"],
            "instructions": (
                "MCP annotations are untrusted hints. The host must enforce Task Floor "
                "state identity, effects, approvals, authority separation, and acceptance."
            ),
        },
        "tools": tools,
        "resources": [
            {
                "uri": "task-floor://manifest",
                "name": "Task Floor capability manifest",
                "mimeType": "application/json",
                "digest": {"sha256": manifest["manifest_sha256"]},
            }
        ],
        "cartridge": cartridge_value,
    }
    value["export_sha256"] = hash_json(value)
    return value


def a2a_export(
    manifest: dict[str, Any],
    *,
    endpoint: str,
    cartridge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    cartridge_value = validate_cartridge(cartridge) if cartridge is not None else None
    skills: list[dict[str, Any]] = []
    if cartridge_value is not None:
        skills.append(
            {
                "id": cartridge_value["id"],
                "name": cartridge_value["title"],
                "description": cartridge_value["goal"],
                "tags": [
                    cartridge_value["project"],
                    "task-floor",
                    *cartridge_value["surfaces"],
                ],
                "examples": [],
                "inputModes": ["application/json", "text/plain"],
                "outputModes": ["application/json", "text/plain"],
                "securityRequirements": [],
            }
        )
    else:
        for surface in manifest["surfaces"]:
            skills.append(
                {
                    "id": surface["id"],
                    "name": surface["kind"],
                    "description": (
                        f"observe={surface['observe']} act={surface['act']} "
                        f"state_bound={surface['state_bound']}"
                    ),
                    "tags": ["task-floor", surface["kind"]],
                    "examples": [],
                    "inputModes": ["application/json"],
                    "outputModes": ["application/json"],
                    "securityRequirements": [],
                }
            )
    card = {
        "name": manifest["name"],
        "description": manifest["description"] or "Task Floor conforming agent",
        "supportedInterfaces": [
            {
                "url": endpoint,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "provider": {
            "url": manifest["provider"].get("url")
            or manifest.get("documentation_url")
            or endpoint,
            "organization": manifest["provider"]["name"],
        },
        "version": manifest["version"],
        "documentationUrl": manifest.get("documentation_url"),
        "capabilities": {
            "streaming": manifest["lifecycle"]["streaming"],
            "pushNotifications": False,
            "extendedAgentCard": False,
            "extensions": [
                {
                    "uri": TASK_FLOOR_EXTENSION_URI,
                    "description": (
                        "State identity, effect authority, external acceptance, and "
                        "content-addressed evidence for A2A tasks and artifacts."
                    ),
                    "required": True,
                    "params": {
                        "manifestSha256": manifest["manifest_sha256"],
                        "profilesClaimed": manifest["conformance"]["profiles_claimed"],
                        "productionQualified": manifest["conformance"][
                            "production_qualified"
                        ],
                    },
                }
            ],
        },
        "securitySchemes": {},
        "securityRequirements": [],
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": skills,
        "signatures": [],
    }
    value = {
        "schema": A2A_EXPORT_SCHEMA,
        "protocol": "a2a",
        "protocolVersion": "1.0",
        "agentCard": card,
    }
    value["export_sha256"] = hash_json(value)
    return value


def agui_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError("cannot export invalid bundle: " + "; ".join(errors))
    run = bundle["run"]
    base_timestamp = _iso_to_millis(run["started_at"])
    events: list[dict[str, Any]] = []

    def emit(event_type: str, **payload: Any) -> None:
        events.append(
            {
                "type": event_type,
                "timestamp": base_timestamp + len(events),
                **payload,
            }
        )

    emit(
        "RUN_STARTED",
        threadId=run["run_id"],
        runId=run["run_id"],
        input={
            "scenarioId": run["scenario_id"],
            "project": run["project"],
            "variant": run["variant"],
        },
    )
    for event in bundle["trajectory"]["events"]:
        kind = event["kind"]
        if kind == "step.started":
            emit(
                "STEP_STARTED",
                stepName=f"step-{event['step_number']}",
                rawEvent=event,
            )
            emit(
                "STATE_SNAPSHOT",
                snapshot={
                    "stateId": event["data"]["state_id"],
                    "packetSha256": event["data"]["packet_sha256"],
                },
                rawEvent=event,
            )
        elif kind == "action.executed":
            call_id = (
                f"{run['run_id']}-step-{event['step_number']}-"
                f"action-{event['data']['action_index']}"
            )
            action = event["data"].get("action") or {}
            emit(
                "TOOL_CALL_START",
                toolCallId=call_id,
                toolCallName=(
                    f"{event['data'].get('surface')}.{action.get('op', 'act')}"
                ),
                parentMessageId=None,
                rawEvent=event,
            )
            emit(
                "TOOL_CALL_ARGS",
                toolCallId=call_id,
                delta=json.dumps(action, sort_keys=True),
                rawEvent=event,
            )
            emit("TOOL_CALL_END", toolCallId=call_id, rawEvent=event)
            emit(
                "TOOL_CALL_RESULT",
                messageId=call_id + "-result",
                toolCallId=call_id,
                content=json.dumps(
                    {
                        "completedStateId": event["data"].get("completed_state_id"),
                        "browserReceipt": event["data"].get("browser_receipt"),
                        "screenGhostRequest": event["data"].get(
                            "screen_ghost_request"
                        ),
                    },
                    sort_keys=True,
                ),
                role="tool",
                rawEvent=event,
            )
            emit(
                "CUSTOM",
                name="task.floor.effect",
                value={
                    "effect": action.get("effect"),
                    "surface": event["data"].get("surface"),
                    "stateId": event["data"].get("completed_state_id"),
                    "eventSha256": event["event_sha256"],
                },
                rawEvent=event,
            )
        elif kind == "step.finished":
            emit(
                "STATE_SNAPSHOT",
                snapshot={"stateId": event["data"]["state_id"]},
                rawEvent=event,
            )
            emit(
                "STEP_FINISHED",
                stepName=f"step-{event['step_number']}",
                rawEvent=event,
            )
    final_type = "RUN_FINISHED" if run["status"] == "ACCEPTED" else "RUN_ERROR"
    emit(
        final_type,
        threadId=run["run_id"],
        runId=run["run_id"],
        result={
            "status": run["status"],
            "receiptSha256": run["receipt_sha256"],
            "acceptance": bundle["acceptance"],
            "projectHandoff": bundle["project_handoff"],
        },
    )
    value = {
        "schema": AGUI_SCHEMA,
        "protocol": "ag-ui",
        "events": events,
        "taskFloorExtension": {
            "uri": TASK_FLOOR_EXTENSION_URI,
            "trajectorySha256": bundle["trajectory"]["trajectory_sha256"],
        },
    }
    value["export_sha256"] = hash_json(value)
    return value


def _otel_attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            wrapped = {"boolValue": value}
        elif isinstance(value, int):
            wrapped = {"intValue": str(value)}
        elif isinstance(value, float):
            wrapped = {"doubleValue": value}
        else:
            wrapped = {
                "stringValue": value
                if isinstance(value, str)
                else json.dumps(value, sort_keys=True)
            }
        rows.append({"key": key, "value": wrapped})
    return rows


def opentelemetry_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError("cannot export invalid bundle: " + "; ".join(errors))
    run = bundle["run"]
    trace_id = _trace_id(bundle["trajectory"]["trajectory_sha256"])
    run_start = int(_iso_to_nanos(run["started_at"]))
    run_end = int(_iso_to_nanos(run["completed_at"]))
    root_span_id = _span_id(run["run_id"])
    spans: list[dict[str, Any]] = [
        {
            "traceId": trace_id,
            "spanId": root_span_id,
            "name": "invoke_agent task-floor",
            "kind": 1,
            "startTimeUnixNano": str(run_start),
            "endTimeUnixNano": str(max(run_end, run_start + 1)),
            "attributes": _otel_attributes(
                {
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": bundle["manifest"]["name"],
                    "gen_ai.agent.version": bundle["manifest"]["version"],
                    "gen_ai.conversation.id": run["run_id"],
                    "task.floor.trajectory.sha256": bundle["trajectory"][
                        "trajectory_sha256"
                    ],
                    "task.floor.task.id": run["scenario_id"],
                    "task.floor.project": run["project"],
                    "task.floor.status": run["status"],
                    "task.floor.accepted": run["status"] == "ACCEPTED",
                    "task.floor.actions.executed": bundle["metrics"][
                        "actions_executed"
                    ],
                }
            ),
            "status": {"code": 1 if run["status"] == "ACCEPTED" else 2},
        }
    ]
    action_events = [
        event
        for event in bundle["trajectory"]["events"]
        if event["kind"] == "action.executed"
    ]
    span_window = max(run_end - run_start, len(action_events) + 1)
    for index, event in enumerate(action_events, 1):
        action = event["data"].get("action") or {}
        span_id = _span_id(event["event_sha256"])
        start = run_start + int(span_window * (index / (len(action_events) + 1)))
        spans.append(
            {
                "traceId": trace_id,
                "spanId": span_id,
                "parentSpanId": root_span_id,
                "name": (
                    f"execute_tool {event['data'].get('surface')}."
                    f"{action.get('op', 'act')}"
                ),
                "kind": 1,
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + 1),
                "attributes": _otel_attributes(
                    {
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": (
                            f"{event['data'].get('surface')}."
                            f"{action.get('op', 'act')}"
                        ),
                        "gen_ai.tool.call.id": f"{run['run_id']}:{event['seq']}",
                        "task.floor.effect": action.get("effect"),
                        "task.floor.state.completed.id": event["data"].get(
                            "completed_state_id"
                        ),
                        "task.floor.event.sha256": event["event_sha256"],
                    }
                ),
                "status": {"code": 1},
            }
        )
    value = {
        "schema": OTEL_EXPORT_SCHEMA,
        "schemaUrl": OTEL_GENAI_SCHEMA_URL,
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _otel_attributes(
                        {
                            "service.name": bundle["manifest"]["id"],
                            "service.version": bundle["manifest"]["version"],
                            "task.floor.manifest.sha256": bundle["manifest"][
                                "manifest_sha256"
                            ],
                        }
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "task-floor", "version": "1"},
                        "spans": spans,
                        "schemaUrl": OTEL_GENAI_SCHEMA_URL,
                    }
                ],
                "schemaUrl": OTEL_GENAI_SCHEMA_URL,
            }
        ],
    }
    value["export_sha256"] = hash_json(value)
    return value


def in_toto_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError("cannot attest invalid bundle: " + "; ".join(errors))
    subjects = [
        {"name": artifact["path"], "digest": artifact["digest"]}
        for artifact in bundle["artifacts"]
    ]
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": TASK_FLOOR_PREDICATE_TYPE,
        "predicate": {
            "manifest": {
                "id": bundle["manifest"]["id"],
                "sha256": bundle["manifest"]["manifest_sha256"],
                "profilesClaimed": bundle["manifest"]["conformance"][
                    "profiles_claimed"
                ],
                "productionQualified": bundle["manifest"]["conformance"][
                    "production_qualified"
                ],
            },
            "task": {
                "id": bundle["cartridge"]["id"],
                "project": bundle["cartridge"]["project"],
                "cartridgeSha256": bundle["cartridge"]["cartridge_sha256"],
            },
            "run": bundle["run"],
            "metrics": bundle["metrics"],
            "trajectorySha256": bundle["trajectory"]["trajectory_sha256"],
            "acceptance": bundle["acceptance"],
            "projectHandoffSha256": bundle["project_handoff"].get(
                "handoff_sha256"
            ),
            "authority": bundle["manifest"]["authority"],
        },
    }
    value = {"schema": IN_TOTO_EXPORT_SCHEMA, "statement": statement}
    value["export_sha256"] = hash_json(value)
    return value


def opa_export(manifest: dict[str, Any], cartridge: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    cartridge = validate_cartridge(cartridge)
    value = {
        "schema": OPA_EXPORT_SCHEMA,
        "protocol": "opa",
        "decision": "data.task_floor.admission",
        "inputSchema": {
            "type": "object",
            "required": ["manifest", "cartridge", "state", "action", "runtime"],
            "properties": {
                "manifest": {"type": "object"},
                "cartridge": {"type": "object"},
                "state": {"type": "object"},
                "action": {"type": "object"},
                "runtime": {"type": "object"},
            },
        },
        "data": {
            "manifestSha256": manifest["manifest_sha256"],
            "cartridgeSha256": cartridge["cartridge_sha256"],
            "effectTaxonomy": manifest["effects"]["taxonomy"],
            "defaultEffect": manifest["effects"]["default"],
            "approvalRequiredEffects": [
                "external_write",
                "destructive",
                "financial",
                "identity",
                "sensitive",
                "privileged",
            ],
            "authority": manifest["authority"],
        },
        "outputContract": {
            "allow": "boolean",
            "reasons": "array<string>",
            "effect": "string",
            "state_id": "string",
        },
        "enforcementNotice": (
            "OPA returns a decision. The trusted Task Floor host remains the enforcement point."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def browsergym_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError("cannot export invalid bundle: " + "; ".join(errors))
    cartridge = bundle["cartridge"]
    value = {
        "schema": BROWSERGYM_EXPORT_SCHEMA,
        "protocol": "browsergym",
        "registration": {
            "taskId": f"taskfloor/{cartridge['id']}",
            "abstractTaskBase": "browsergym.core.task.AbstractBrowserTask",
            "goal": cartridge["goal"],
            "variants": cartridge["variants"],
            "mutationDimensions": cartridge["mutation_dimensions"],
            "surfaces": cartridge["surfaces"],
            "acceptance": cartridge["acceptance"],
            "taskFloorCartridgeSha256": cartridge["cartridge_sha256"],
        },
        "trajectory": {
            "taskFloorTrajectorySha256": bundle["trajectory"]["trajectory_sha256"],
            "status": bundle["run"]["status"],
            "metrics": bundle["metrics"],
        },
        "notice": (
            "This descriptor is an adapter input. A BrowserGym environment must still "
            "implement setup, validation, teardown, and benchmark isolation."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def cloudevents_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError("cannot export invalid bundle: " + "; ".join(errors))
    events = []
    source = f"urn:task-floor:{bundle['manifest']['id']}"
    started = bundle["run"]["started_at"]
    for event in bundle["trajectory"]["events"]:
        events.append(
            {
                "specversion": "1.0",
                "id": event["event_sha256"],
                "source": source,
                "type": "org.taskfloor." + event["kind"].replace(".", "_"),
                "subject": f"{bundle['run']['run_id']}/step/{event['step_number']}",
                "time": started,
                "datacontenttype": "application/json",
                "dataschema": "urn:task-floor:trajectory-event:v1",
                "data": event,
                "taskfloortaskid": bundle["cartridge"]["id"],
                "taskfloortrajectorysha256": bundle["trajectory"][
                    "trajectory_sha256"
                ],
            }
        )
    value = {
        "schema": CLOUDEVENTS_EXPORT_SCHEMA,
        "protocol": "cloudevents",
        "specversion": "1.0",
        "events": events,
    }
    value["export_sha256"] = hash_json(value)
    return value


def agentrx_export(bundle: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical trajectory into a diagnosis-oriented step IR.

    AgentRx owns its evolving canonical IR. This export preserves the fields its
    normalization stage needs without claiming that Task Floor is the AgentRx
    implementation or that the downstream judge has run.
    """
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot export invalid bundle: " + "; ".join(errors)
        )
    by_step: dict[int, dict[str, Any]] = {}
    for event in bundle["trajectory"]["events"]:
        step_number = event.get("step_number")
        if step_number is None:
            continue
        row = by_step.setdefault(
            int(step_number),
            {
                "step_id": f"step-{int(step_number):04d}",
                "step_number": int(step_number),
                "observation": None,
                "proposal": None,
                "verdict": None,
                "actions": [],
                "outcome": None,
                "evidence": [],
            },
        )
        if event["kind"] == "step.started":
            row["observation"] = {
                "state_id": event["data"].get("state_id"),
                "packet_sha256": event["data"].get("packet_sha256"),
            }
        elif event["kind"] == "planner.proposal":
            row["proposal"] = event["data"]
        elif event["kind"] == "critic.verdict":
            row["verdict"] = event["data"]
        elif event["kind"] == "action.executed":
            row["actions"].append(event["data"])
        elif event["kind"] == "step.finished":
            row["outcome"] = event["data"]
        row["evidence"].append(event["event_sha256"])
    value = {
        "schema": AGENTRX_EXPORT_SCHEMA,
        "protocol": "agentrx",
        "adapter": "Task Floor trajectory normalization input",
        "source": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trajectory_sha256": bundle["trajectory"]["trajectory_sha256"],
        },
        "task": {
            "id": bundle["cartridge"]["id"],
            "project": bundle["cartridge"]["project"],
            "goal": bundle["cartridge"]["goal"],
            "acceptance": bundle["cartridge"]["acceptance"],
        },
        "trajectory_ir": {
            "run_id": bundle["run"]["run_id"],
            "status": bundle["run"]["status"],
            "steps": [by_step[key] for key in sorted(by_step)],
            "failure": {
                "category": bundle["metrics"].get("failure_category"),
                "error": next(
                    (
                        event["data"].get("error")
                        for event in bundle["trajectory"]["events"]
                        if event["kind"] == "run.failure"
                    ),
                    None,
                ),
            },
        },
        "notice": (
            "This is an AgentRx normalization input. Invariant generation, checking, "
            "failure localization, and judge classification remain AgentRx stages."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def cua_export(bundle: dict[str, Any]) -> dict[str, Any]:
    """Export a generic computer-use trajectory with explicit state and effect data."""
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot export invalid bundle: " + "; ".join(errors)
        )
    screenshots = [
        artifact
        for artifact in bundle["artifacts"]
        if artifact["path"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]
    actions = [
        {
            "event_sha256": event["event_sha256"],
            "step_number": event["step_number"],
            "state_id": (event["data"].get("browser_receipt") or {}).get(
                "started_state_id"
            )
            or (event["data"].get("candidate") or {}).get("state_id"),
            "surface": event["data"].get("surface"),
            "effect": event["data"].get("effect"),
            "action": event["data"].get("action"),
            "result": event["data"].get("result"),
            "completed_state_id": event["data"].get("completed_state_id"),
        }
        for event in bundle["trajectory"]["events"]
        if event["kind"] == "action.executed"
    ]
    value = {
        "schema": CUA_EXPORT_SCHEMA,
        "protocol": "cua",
        "source": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trajectory_sha256": bundle["trajectory"]["trajectory_sha256"],
        },
        "task": {
            "id": bundle["cartridge"]["id"],
            "goal": bundle["cartridge"]["goal"],
        },
        "trajectory": {
            "run_id": bundle["run"]["run_id"],
            "status": bundle["run"]["status"],
            "actions": actions,
            "screenshots": screenshots,
            "metrics": bundle["metrics"],
        },
        "notice": (
            "This is a portable CUA adapter record. A Cua sandbox or benchmark "
            "runner remains responsible for environment execution and native export."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def cedar_export(manifest: dict[str, Any], cartridge: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    cartridge = validate_cartridge(cartridge)
    actions = [
        {
            "uid": {"type": "TaskFloor::Action", "id": effect},
            "attrs": {"effect": effect},
            "parents": [],
        }
        for effect in manifest["effects"]["taxonomy"]
    ]
    value = {
        "schema": CEDAR_EXPORT_SCHEMA,
        "protocol": "cedar",
        "source": {
            "manifest_sha256": manifest["manifest_sha256"],
            "cartridge_sha256": cartridge["cartridge_sha256"],
        },
        "authorization_request": {
            "principal": {
                "type": "TaskFloor::Agent",
                "id": "<planner-or-executor-identity>",
            },
            "action": {"type": "TaskFloor::Action", "id": "<effect>"},
            "resource": {"type": "TaskFloor::Task", "id": cartridge["id"]},
            "context": {
                "stateId": "<state-sha256>",
                "actionSha256": "<action-sha256>",
                "onBehalfOf": "<optional-human-or-service-principal>",
                "approvalSha256": "<optional-approval-sha256>",
            },
        },
        "entities": [
            {
                "uid": {"type": "TaskFloor::Task", "id": cartridge["id"]},
                "attrs": {
                    "project": cartridge["project"],
                    "failureDefault": cartridge["failure_default"],
                },
                "parents": [],
            },
            *actions,
        ],
        "notice": (
            "Cedar decides authorization. The trusted Task Floor host still enforces "
            "state identity, executes effects, and records receipts."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def langgraph_export(bundle: dict[str, Any]) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot export invalid bundle: " + "; ".join(errors)
        )
    checkpoints = [
        {
            "checkpoint_id": event["data"].get("state_id"),
            "step_number": event["step_number"],
            "event_sha256": event["event_sha256"],
        }
        for event in bundle["trajectory"]["events"]
        if event["kind"] in {"step.started", "step.finished"}
    ]
    value = {
        "schema": LANGGRAPH_EXPORT_SCHEMA,
        "protocol": "langgraph",
        "thread_id": bundle["run"]["run_id"],
        "checkpoints": checkpoints,
        "interrupt_contract": {
            "takeover": "pause before any human-governed action",
            "resume": "re-observe and require a new state identity",
            "idempotency": (
                "nodes that may replay after an interrupt must use the action "
                "idempotency key and receipt lookup"
            ),
        },
        "state": {
            "taskFloorBundleSha256": bundle["bundle_sha256"],
            "taskFloorTrajectorySha256": bundle["trajectory"]["trajectory_sha256"],
            "projectHandoff": bundle["project_handoff"],
        },
        "notice": (
            "This descriptor maps Task Floor checkpoints and takeover rules into a "
            "LangGraph-style durable execution thread; it is not a compiled graph."
        ),
    }
    value["export_sha256"] = hash_json(value)
    return value


def attach_exports(
    bundle: dict[str, Any],
    *,
    a2a_endpoint: str = "https://example.invalid/a2a",
) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot attach exports to invalid bundle: " + "; ".join(errors)
        )
    value = without_hash(bundle, "bundle_sha256")
    value["exports"] = {
        "mcp": mcp_export(bundle["manifest"], bundle["cartridge"]),
        "a2a": a2a_export(
            bundle["manifest"], endpoint=a2a_endpoint, cartridge=bundle["cartridge"]
        ),
        "ag-ui": agui_export(bundle),
        "opentelemetry": opentelemetry_export(bundle),
        "in-toto": in_toto_export(bundle),
        "opa": opa_export(bundle["manifest"], bundle["cartridge"]),
        "browsergym": browsergym_export(bundle),
        "cloudevents": cloudevents_export(bundle),
        "agentrx": agentrx_export(bundle),
        "cua": cua_export(bundle),
        "cedar": cedar_export(bundle["manifest"], bundle["cartridge"]),
        "langgraph": langgraph_export(bundle),
    }
    value["bundle_sha256"] = hash_json(value)
    return value


def _export_index(exports: dict[str, Any]) -> dict[str, Any]:
    filenames = {
        "mcp": "mcp-tools.json",
        "a2a": "agent-card.json",
        "ag-ui": "ag-ui-events.json",
        "opentelemetry": "otel-traces.json",
        "in-toto": "attestation.json",
        "opa": "opa-policy-contract.json",
        "browsergym": "browsergym-task.json",
        "cloudevents": "cloudevents.json",
        "agentrx": "agentrx-trajectory.json",
        "cua": "cua-trajectory.json",
        "cedar": "cedar-authorization.json",
        "langgraph": "langgraph-checkpoints.json",
    }
    value = {
        "schema": EXPORT_INDEX_SCHEMA,
        "exports": [
            {
                "id": key,
                "path": filenames[key],
                "export_sha256": exports[key]["export_sha256"],
            }
            for key in sorted(exports)
        ],
    }
    value["index_sha256"] = hash_json(value)
    return value


def _materialize_bundle_artifacts(
    bundle: dict[str, Any],
    *,
    source_root: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """Copy non-secret run artifacts into a portable bundle directory.

    Canonical artifact paths become relative to the bundle root. The source run
    may be deleted after this function returns without invalidating provenance.
    """
    value = deepcopy(bundle)
    source_root = source_root.resolve()
    for artifact in value.get("artifacts", []):
        source = safe_relative_path(
            source_root, artifact["path"], "source bundle artifact path"
        )
        if not source.is_file():
            raise PlaywrightComputerError(
                f"source bundle artifact is missing: {artifact['path']}"
            )
        if source.stat().st_size != artifact["bytes"]:
            raise PlaywrightComputerError(
                f"source bundle artifact size differs: {artifact['path']}"
            )
        if hash_file(source) != artifact["digest"]["sha256"]:
            raise PlaywrightComputerError(
                f"source bundle artifact hash differs: {artifact['path']}"
            )
        portable_path = Path("artifacts") / Path(artifact["path"])
        destination = safe_relative_path(
            out_dir, portable_path.as_posix(), "portable bundle artifact path"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            destination.name + f".tmp-{os.getpid()}"
        )
        shutil.copy2(source, temporary)
        if (
            temporary.stat().st_size != artifact["bytes"]
            or hash_file(temporary) != artifact["digest"]["sha256"]
        ):
            temporary.unlink(missing_ok=True)
            raise PlaywrightComputerError(
                f"portable artifact verification failed: {artifact['path']}"
            )
        os.replace(temporary, destination)
        artifact["path"] = portable_path.as_posix()
    value["bundle_sha256"] = hash_json(without_hash(value, "bundle_sha256"))
    return value


def write_bundle_directory(
    out_dir: Path,
    bundle: dict[str, Any],
    *,
    a2a_endpoint: str = "https://example.invalid/a2a",
    artifact_source_root: Path | None = None,
) -> dict[str, Any]:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise PlaywrightComputerError(f"bundle directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    portable = (
        _materialize_bundle_artifacts(
            bundle, source_root=artifact_source_root, out_dir=out_dir
        )
        if artifact_source_root is not None
        else bundle
    )
    complete = attach_exports(portable, a2a_endpoint=a2a_endpoint)
    errors = verify_bundle(
        complete, root=out_dir if artifact_source_root is not None else None
    )
    if errors:
        raise PlaywrightComputerError(
            "complete bundle failed verification: " + "; ".join(errors)
        )
    atomic_json(out_dir / "bundle.json", complete)
    filenames = {
        "mcp": "mcp-tools.json",
        "a2a": "agent-card.json",
        "ag-ui": "ag-ui-events.json",
        "opentelemetry": "otel-traces.json",
        "in-toto": "attestation.json",
        "opa": "opa-policy-contract.json",
        "browsergym": "browsergym-task.json",
        "cloudevents": "cloudevents.json",
        "agentrx": "agentrx-trajectory.json",
        "cua": "cua-trajectory.json",
        "cedar": "cedar-authorization.json",
        "langgraph": "langgraph-checkpoints.json",
    }
    for key, filename in filenames.items():
        atomic_json(out_dir / filename, complete["exports"][key])
    atomic_json(out_dir / "exports.json", _export_index(complete["exports"]))
    return complete
