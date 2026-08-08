#!/usr/bin/env python3
"""Dependency-free reference implementation of the Task Floor command driver."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tier_runner.playwright_computer_common import atomic_json, hash_json, load_json, now_utc
from tier_runner.task_floor_protocol import (
    ACTION_RECEIPT_SCHEMA,
    DRIVER_RESPONSE_SCHEMA,
    MANIFEST_SCHEMA,
    make_driver_request,
    seal_record,
    seal_state,
    validate_action,
    validate_driver_request,
    validate_manifest,
)

ROOT = Path(os.environ.get("TASK_FLOOR_DRIVER_ROOT", ".task-floor-reference-driver")).resolve()
STATE_PATH = ROOT / "state.json"
TAKEOVER_PATH = ROOT / "takeover.json"
TASK_PATH = ROOT / "task.json"
IDEMPOTENCY_DIR = ROOT / "idempotency"


def manifest() -> dict[str, Any]:
    return validate_manifest(
        {
            "schema": MANIFEST_SCHEMA,
            "id": "task-floor-reference-driver",
            "name": "Task Floor reference command driver",
            "version": "1.0.0",
            "description": "In-memory-like persistent reference used by the public conformance kit.",
            "provider": {"name": "Task Floor reference"},
            "license": "MIT",
            "interfaces": [
                {
                    "protocol": "native-json",
                    "version": "1",
                    "role": "driver",
                    "transport": "stdio",
                    "extensions": ["urn:task-floor:v1"],
                }
            ],
            "surfaces": [
                {
                    "id": "reference-api",
                    "kind": "api",
                    "observe": True,
                    "act": True,
                    "state_bound": True,
                    "supports_artifacts": True,
                    "operations": ["increment", "publish"],
                },
                {
                    "id": "reference-human",
                    "kind": "human",
                    "observe": True,
                    "act": True,
                    "state_bound": True,
                    "supports_artifacts": False,
                    "operations": ["takeover", "release"],
                },
            ],
            "lifecycle": {
                "persistent_state": True,
                "streaming": False,
                "async_tasks": False,
                "cancel": False,
                "resume": True,
                "human_takeover": True,
            },
            "state": {
                "content_addressed": True,
                "exact_action_binding": True,
                "replay": True,
                "snapshots": True,
                "conflict_detection": True,
            },
            "authority": {
                "observer": ["reference-driver"],
                "policy": ["reference-driver"],
                "executor": ["reference-driver"],
                "acceptor": ["reference-hidden-acceptor"],
                "credential_custodian": ["reference-driver"],
                "artifact_custodian": ["reference-driver"],
                "human": ["conformance-caller"],
            },
            "effects": {
                "taxonomy": ["read", "local_write", "external_write", "privileged"],
                "declared": True,
                "argument_scoped": True,
                "enforced": True,
                "approval": True,
                "postconditions": True,
                "default": "privileged",
            },
            "evidence": {
                "content_addressed": True,
                "event_chain": False,
                "action_receipts": True,
                "artifact_hashes": True,
                "trajectory_export": True,
                "signatures": False,
            },
            "acceptance": {
                "external_verifier": True,
                "hidden_state": True,
                "postconditions": True,
                "project_handoff": True,
                "mutation_suite": True,
            },
            "security": {
                "authentication": False,
                "authorization": True,
                "secrets_isolated": True,
                "credential_lease": True,
                "network_policy": True,
                "sandbox": True,
                "prompt_injection_boundary": True,
            },
            "observability": {
                "trace_context": True,
                "opentelemetry": True,
                "token_usage": False,
                "cost": False,
                "human_time": True,
                "evaluation_events": True,
            },
            "identity": {
                "workload_identity": False,
                "agent_delegation": True,
                "runtime_attestation": True,
                "signed_messages": False,
            },
            "execution": {
                "optimistic_concurrency": True,
                "idempotency_keys": True,
                "transactions": False,
                "compensation": False,
                "rollback": False,
            },
            "privacy": {
                "redaction": True,
                "retention": True,
                "data_classification": True,
                "deletion_receipts": False,
                "secret_exclusion": True,
            },
            "supply_chain": {
                "dependency_inventory": True,
                "signed_skills": False,
                "reproducible_environment": True,
                "model_runtime_identity": True,
                "build_provenance": False,
            },
            "versioning": {
                "schema_negotiation": True,
                "backward_compatibility": True,
                "deprecation_policy": True,
            },
            "diagnostics": {
                "failure_taxonomy": True,
                "counterfactual_replay": True,
                "invariant_checks": True,
                "claim_verification": True,
            },
            "resilience": {
                "mutation_suite": True,
                "prompt_injection_tests": True,
                "recovery": True,
                "role_reversal": True,
            },
            "interop": {
                "mcp": True,
                "a2a": True,
                "ag-ui": True,
                "opentelemetry": True,
                "in-toto": True,
                "opa": True,
                "browsergym": True,
                "cloudevents": True,
                "agentrx": True,
                "cua": True,
                "spiffe": False,
                "cedar": True,
                "langgraph": True,
            },
            "conformance": {
                "profiles_claimed": ["TF0", "TF1", "TF2", "TF3", "TF4"],
                "claim_scope": "reference-driver and synthetic protocol conformance",
                "production_qualified": False,
                "evidence": [],
            },
        }
    )


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        raise RuntimeError("reference task is not initialized")
    return load_json(STATE_PATH)


def write_state(data: dict[str, Any], *, previous: str | None = None) -> dict[str, Any]:
    current_revision = 0
    if STATE_PATH.exists():
        current_revision = int(load_json(STATE_PATH)["revision"]) + 1
    value = seal_state(
        {
            "task_id": "task-floor-reference-effect-task",
            "revision": current_revision,
            "observed_at": now_utc(),
            "previous_state_id": previous,
            "surfaces": {
                "api": {
                    "operations": ["increment", "publish"],
                    "takeover_active": TAKEOVER_PATH.exists(),
                }
            },
            "artifacts": [
                {
                    "name": "reference-state.json",
                    "digest": {"sha256": hash_json(data)},
                    "media_type": "application/json",
                }
            ],
            "data": data,
        }
    )
    atomic_json(STATE_PATH, value)
    return value


def response(request: dict[str, Any], ok: bool, **payload: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": DRIVER_RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "ok": ok,
        "manifest": payload.get("manifest"),
        "state": payload.get("state"),
        "receipt": payload.get("receipt"),
        "lease": payload.get("lease"),
        "acceptance": payload.get("acceptance"),
        "error": payload.get("error"),
        "metadata": payload.get("metadata", {}),
    }
    return seal_record(value, "response_sha256")


def action_receipt(
    action: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    admitted: bool,
) -> dict[str, Any]:
    value = {
        "schema": ACTION_RECEIPT_SCHEMA,
        "action_id": action["action_id"],
        "task_id": action["task_id"],
        "surface": action["surface"],
        "operation": action["operation"],
        "effect": action["effect"],
        "action_sha256": action["action_sha256"],
        "idempotency_key": action["idempotency_key"],
        "started_state_id": before["state_id"],
        "completed_state_id": after["state_id"],
        "executed_at": now_utc(),
        "authority": {
            "policy": "reference-driver",
            "executor": "reference-driver",
            "acceptor": "reference-hidden-acceptor",
        },
        "approval": {
            "required": action["effect"] in {"external_write", "destructive", "financial", "identity", "sensitive", "privileged"},
            "admitted": admitted,
            "scope": action["effect"] if admitted else None,
            "token_retained": False,
        },
        "preconditions": action.get("preconditions", []),
        "expected_postconditions": action.get("expected_postconditions", []),
        "postconditions": {
            "counter": after["data"]["counter"],
            "published": after["data"]["published"],
        },
        "runtime": {
            "driver": "task-floor-reference-driver",
            "version": "1.0.0",
            "pid": os.getpid(),
        },
        "artifacts": after["artifacts"],
        "trace_context": action.get("trace_context"),
    }
    return seal_record(value, "receipt_sha256")


def handle(raw: dict[str, Any]) -> dict[str, Any]:
    request = validate_driver_request(raw)
    op = request["op"]
    if op == "describe":
        return response(request, True, manifest=manifest())
    if op == "reset":
        ROOT.mkdir(parents=True, exist_ok=True)
        TAKEOVER_PATH.unlink(missing_ok=True)
        if IDEMPOTENCY_DIR.exists():
            for path in IDEMPOTENCY_DIR.glob("*.json"):
                path.unlink()
        IDEMPOTENCY_DIR.mkdir(parents=True, exist_ok=True)
        atomic_json(TASK_PATH, request.get("task") or {})
        state = write_state({"counter": 0, "published": False})
        return response(request, True, state=state)
    if op == "observe":
        return response(request, True, state=read_state())
    if op == "act":
        if TAKEOVER_PATH.exists():
            return response(request, False, error="human takeover is active")
        action = validate_action(request["action"])
        IDEMPOTENCY_DIR.mkdir(parents=True, exist_ok=True)
        idempotency_path = IDEMPOTENCY_DIR / (hash_json({"key": action["idempotency_key"]}) + ".json")
        if idempotency_path.exists():
            retained = load_json(idempotency_path)
            if retained.get("action_sha256") != action["action_sha256"]:
                return response(request, False, error="idempotency key was reused for a different action")
            return response(
                request,
                True,
                state=retained["state"],
                receipt=retained["receipt"],
                metadata={"idempotent_replay": True},
            )
        before = read_state()
        if action["expected_state_id"] != before["state_id"]:
            return response(request, False, error="expected state does not match current state")
        if action["task_id"] != before["task_id"]:
            return response(request, False, error="action belongs to another task")
        operation = action["operation"]
        data = dict(before["data"])
        admitted = False
        if operation == "increment":
            if action["effect"] != "local_write":
                return response(request, False, error="increment requires local_write effect")
            data["counter"] += 1
        elif operation == "publish":
            if action["effect"] != "external_write":
                return response(request, False, error="publish requires external_write effect")
            approval = request.get("approval") or action.get("approval") or {}
            if approval.get("scope") != "external_write" or approval.get("token") != "reference-approval":
                return response(request, False, error="external_write requires approval")
            admitted = True
            data["published"] = True
        else:
            return response(request, False, error=f"unsupported operation {operation!r}")
        after = write_state(data, previous=before["state_id"])
        receipt_value = action_receipt(action, before, after, admitted=admitted)
        atomic_json(
            idempotency_path,
            {
                "action_sha256": action["action_sha256"],
                "state": after,
                "receipt": receipt_value,
            },
        )
        return response(
            request,
            True,
            state=after,
            receipt=receipt_value,
            metadata={"idempotent_replay": False},
        )
    if op == "takeover":
        if TAKEOVER_PATH.exists():
            return response(request, False, error="human takeover is already active")
        lease = {
            "schema": "task-floor/takeover-lease@1",
            "lease_id": "lease-" + secrets.token_hex(8),
            "owner": "human",
            "claimed_at": now_utc(),
            "state_id": read_state()["state_id"],
        }
        lease["lease_sha256"] = hash_json(lease)
        atomic_json(TAKEOVER_PATH, lease)
        return response(request, True, lease=lease)
    if op == "release":
        if not TAKEOVER_PATH.exists():
            return response(request, False, error="no human takeover is active")
        lease = load_json(TAKEOVER_PATH)
        if request.get("lease_id") != lease["lease_id"]:
            return response(request, False, error="takeover lease identity does not match")
        before = read_state()
        TAKEOVER_PATH.unlink()
        after = write_state(dict(before["data"]), previous=before["state_id"])
        return response(request, True, state=after)
    if op == "accept":
        state = read_state()
        passed = state["data"] == {"counter": 1, "published": True}
        acceptance = {
            "schema": "task-floor/acceptance-result@1",
            "task_id": state["task_id"],
            "state_id": state["state_id"],
            "pass": passed,
            "checks": [
                {
                    "id": "counter-one",
                    "pass": state["data"]["counter"] == 1,
                    "observed": state["data"]["counter"],
                    "expected": 1,
                },
                {
                    "id": "published",
                    "pass": state["data"]["published"] is True,
                    "observed": state["data"]["published"],
                    "expected": True,
                },
            ],
            "authority": "reference-hidden-acceptor",
            "project_handoff": {
                "counter": state["data"]["counter"],
                "published": state["data"]["published"],
            },
        }
        acceptance["acceptance_sha256"] = hash_json(acceptance)
        return response(request, True, acceptance=acceptance)
    if op == "close":
        return response(request, True, metadata={"closed": True})
    return response(request, False, error=f"unsupported op {op!r}")


def main() -> int:
    try:
        raw = json.load(sys.stdin)
        print(json.dumps(handle(raw), sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        request_id = "unknown"
        try:
            request_id = str(raw.get("request_id", "unknown"))
        except Exception:
            pass
        failure = seal_record(
            {
                "schema": DRIVER_RESPONSE_SCHEMA,
                "request_id": request_id,
                "request_sha256": (
                    raw.get("request_sha256") if isinstance(raw, dict) else None
                ),
                "ok": False,
                "manifest": None,
                "state": None,
                "receipt": None,
                "lease": None,
                "acceptance": None,
                "error": f"{type(exc).__name__}: {exc}",
                "metadata": {},
            },
            "response_sha256",
        )
        print(json.dumps(failure, sort_keys=True, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
