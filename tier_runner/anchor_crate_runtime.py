"""Deterministic Anchor Crate controller and artifact-custody runtime."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from .anchor_crate_common import (
    ANCHOR_SCHEMA,
    CRATE_SCHEMA,
    DRIVER_REQUEST_SCHEMA,
    DRIVER_RESPONSE_SCHEMA,
    RECEIPT_SCHEMA,
    RUN_SCHEMA,
    AnchorError,
    canonical_bytes,
    hash_json,
    need_array,
    need_boolean,
    need_digest,
    need_integer,
    need_object,
    need_text,
    safe_id,
    sha256_bytes,
    write_json,
)
from .anchor_crate_plan import compile_plan, verify_plan
from .anchor_crate_schema import validate_backend_registry, validate_cartridge, validate_floor


@dataclass(frozen=True)
class RunPaths:
    root: Path
    artifacts: Path
    anchors: Path
    crates: Path
    receipts: Path
    events: Path
    run_json: Path


def _paths(root: Path) -> RunPaths:
    return RunPaths(
        root=root,
        artifacts=root / "artifacts",
        anchors=root / "anchors",
        crates=root / "crates",
        receipts=root / "receipts",
        events=root / "events.jsonl",
        run_json=root / "run.json",
    )


def _ensure_paths(paths: RunPaths) -> None:
    for path in (paths.root, paths.artifacts, paths.anchors, paths.crates, paths.receipts):
        path.mkdir(parents=True, exist_ok=True)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    rendered = canonical_bytes(event)
    with path.open("ab") as handle:
        handle.write(rendered)


def _artifact_path(paths: RunPaths, digest: str) -> Path:
    return paths.artifacts / digest[:2] / f"{digest}.json"


def put_artifact(paths: RunPaths, value: Any) -> dict[str, Any]:
    payload = canonical_bytes(value)
    digest = sha256_bytes(payload)
    path = _artifact_path(paths, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise AnchorError(f"artifact collision for {digest}")
    else:
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return {"sha256": digest, "bytes": len(payload), "media_type": "application/json"}


def get_artifact(paths: RunPaths, descriptor: dict[str, Any]) -> Any:
    digest = need_digest(descriptor.get("sha256"), "artifact.sha256")
    path = _artifact_path(paths, digest)
    if not path.is_file():
        raise AnchorError(f"missing artifact {digest}")
    payload = path.read_bytes()
    if sha256_bytes(payload) != digest:
        raise AnchorError(f"artifact hash mismatch for {digest}")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AnchorError(f"artifact {digest} is not valid JSON") from exc


def _anchor_body(
    *,
    plan: dict[str, Any],
    cartridge: dict[str, Any],
    parent_anchor_sha256: str | None,
    sequence: int,
    status: str,
    node_states: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    receipt_sha256s: list[str],
    consumed_wall_ms: int,
    consumed_energy_mwh: int,
    remaining_attempts: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema": ANCHOR_SCHEMA,
        "portable_task_id": plan["portable_task_id"],
        "plan_id": plan["plan_id"],
        "floor_id": plan["floor_id"],
        "cartridge_id": plan["cartridge_id"],
        "parent_anchor_sha256": parent_anchor_sha256,
        "sequence": sequence,
        "status": status,
        "node_states": {key: node_states[key] for key in sorted(node_states)},
        "artifacts": {key: artifacts[key] for key in sorted(artifacts)},
        "receipt_sha256s": list(receipt_sha256s),
        "budgets": {
            "max_wall_ms": cartridge["budgets"]["max_wall_ms"],
            "max_energy_mwh": cartridge["budgets"]["max_energy_mwh"],
            "consumed_wall_ms": consumed_wall_ms,
            "consumed_energy_mwh": consumed_energy_mwh,
            "remaining_wall_ms": max(0, cartridge["budgets"]["max_wall_ms"] - consumed_wall_ms),
            "remaining_energy_mwh": max(
                0, cartridge["budgets"]["max_energy_mwh"] - consumed_energy_mwh
            ),
            "remaining_attempts": {key: remaining_attempts[key] for key in sorted(remaining_attempts)},
        },
        "exact_stop_condition": (
            f"accept {cartridge['acceptance']['final_node']} after controller validators pass"
        ),
        "production_claim": False,
        "promotion_authorized": False,
    }


def _seal_anchor(paths: RunPaths, body: dict[str, Any]) -> dict[str, Any]:
    digest = hash_json(body)
    record = {"anchor_sha256": digest, **body}
    path = paths.anchors / f"{body['sequence']:04d}-{digest}.json"
    write_json(path, record)
    return record


def _validate_anchor(
    raw: Any,
    *,
    plan: dict[str, Any],
    cartridge: dict[str, Any],
) -> dict[str, Any]:
    row = need_object(raw, "anchor")
    if row.get("schema") != ANCHOR_SCHEMA:
        raise AnchorError(f"anchor.schema must be {ANCHOR_SCHEMA}")
    claimed = need_digest(row.get("anchor_sha256"), "anchor.anchor_sha256")
    body = {key: value for key, value in row.items() if key != "anchor_sha256"}
    if hash_json(body) != claimed:
        raise AnchorError("anchor content hash mismatch")
    if row.get("plan_id") != plan["plan_id"]:
        raise AnchorError("anchor plan identity mismatch")
    if row.get("portable_task_id") != plan["portable_task_id"]:
        raise AnchorError("anchor portable task identity mismatch")
    if row.get("cartridge_id") != cartridge["id"]:
        raise AnchorError("anchor cartridge identity mismatch")
    need_integer(row.get("sequence"), "anchor.sequence", 0)
    node_states = need_object(row.get("node_states"), "anchor.node_states")
    artifacts = need_object(row.get("artifacts"), "anchor.artifacts")
    receipts = need_array(row.get("receipt_sha256s"), "anchor.receipt_sha256s")
    for item in receipts:
        need_digest(item, "anchor.receipt_sha256s[]")
    budgets = need_object(row.get("budgets"), "anchor.budgets")
    need_integer(budgets.get("consumed_wall_ms"), "anchor.budgets.consumed_wall_ms")
    need_integer(budgets.get("consumed_energy_mwh"), "anchor.budgets.consumed_energy_mwh")
    need_object(budgets.get("remaining_attempts"), "anchor.budgets.remaining_attempts")
    if row.get("production_claim") is not False or row.get("promotion_authorized") is not False:
        raise AnchorError("an anchor cannot claim production or promotion")
    return row


def _validate_driver_response(
    raw: Any, *, request_id: str, backend_id: str
) -> dict[str, Any]:
    row = need_object(raw, "executor response")
    if row.get("schema") != DRIVER_RESPONSE_SCHEMA:
        raise AnchorError(f"executor response schema must be {DRIVER_RESPONSE_SCHEMA}")
    if row.get("request_id") != request_id:
        raise AnchorError("executor response request identity mismatch")
    if row.get("backend_id") != backend_id:
        raise AnchorError("executor response backend identity mismatch")
    status = need_text(row.get("status"), "executor response.status", limit=40)
    if status not in {"ok", "error"}:
        raise AnchorError("executor response status is invalid")
    telemetry = need_object(row.get("telemetry"), "executor response.telemetry")
    normalized = {
        "status": need_text(telemetry.get("status"), "telemetry.status", limit=40),
        "elapsed_ms": need_integer(telemetry.get("elapsed_ms"), "telemetry.elapsed_ms"),
        "memory_peak_mib": need_integer(
            telemetry.get("memory_peak_mib"), "telemetry.memory_peak_mib"
        ),
        "energy_mwh": need_integer(telemetry.get("energy_mwh"), "telemetry.energy_mwh"),
    }
    forbidden = {
        "accepted",
        "acceptance",
        "artifact_sha256",
        "anchor_sha256",
        "crate_sha256",
        "final_disposition",
        "hidden_validator",
    }
    if forbidden & set(row):
        raise AnchorError("executor attempted to claim controller-owned state or acceptance")
    return {
        "schema": DRIVER_RESPONSE_SCHEMA,
        "request_id": request_id,
        "backend_id": backend_id,
        "status": status,
        "output": row.get("output"),
        "telemetry": normalized,
        "advisory": [need_text(item, "executor response.advisory[]", limit=4000) for item in need_array(row.get("advisory", []), "executor response.advisory")],
    }


def invoke_backend(
    backend: dict[str, Any],
    request: dict[str, Any],
    *,
    cwd: Path,
    timeout_ms: int,
) -> dict[str, Any]:
    command = backend["driver_command"]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input=canonical_bytes(request),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            timeout=max(0.001, timeout_ms / 1000),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnchorError(f"backend {backend['id']} timed out") from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        diagnostic = completed.stderr.decode("utf-8", errors="replace")[:2000]
        raise AnchorError(
            f"backend {backend['id']} returned invalid JSON; exit={completed.returncode}; "
            f"stderr={diagnostic!r}"
        ) from exc
    response = _validate_driver_response(
        raw, request_id=request["request_id"], backend_id=backend["id"]
    )
    response["controller_elapsed_ms"] = elapsed_ms
    response["process_exit_code"] = completed.returncode
    response["stderr_sha256"] = sha256_bytes(completed.stderr)
    if completed.returncode != 0 or response["status"] != "ok":
        raise AnchorError(
            f"backend {backend['id']} failed: exit={completed.returncode}, "
            f"advisory={response['advisory']}"
        )
    return response


def _validator_normalized_records(product: Any, context: dict[str, Any]) -> tuple[bool, str]:
    row = need_object(product, "normalized records")
    if row.get("asset_id") != "A-17":
        return False, "asset identity was not normalized to A-17"
    records = need_array(row.get("records"), "normalized records.records", nonempty=True)
    keys = [(item.get("record_type"), item.get("record_id")) for item in records]
    if keys != sorted(keys):
        return False, "records are not in canonical order"
    if len(records) != 3:
        return False, "expected exactly three source records"
    return True, "normalized source records are canonical"


def _expected_availability() -> dict[str, Any]:
    return {
        "asset_id": "A-17",
        "physically_available": False,
        "blockers": [
            "on-hand part is not serviceable",
            "maintenance work order remains open",
            "replacement due-in is delayed",
        ],
        "evidence_record_ids": ["due-001", "inv-001", "wo-001"],
    }


def _validator_availability(product: Any, context: dict[str, Any]) -> tuple[bool, str]:
    if product != _expected_availability():
        return False, "availability state does not match deterministic source join"
    return True, "physical availability state matches the source-bound constraint chain"


def _validator_decision(product: Any, context: dict[str, Any]) -> tuple[bool, str]:
    row = need_object(product, "decision packet")
    expected = _expected_availability()
    required = {
        "asset_id",
        "claim",
        "blockers",
        "evidence_record_ids",
        "summary",
        "requires_human_review",
    }
    if set(row) != required:
        return False, "decision packet fields differ from the frozen product schema"
    if row["asset_id"] != expected["asset_id"]:
        return False, "decision packet asset identity drifted"
    if row["claim"] != "not_physically_available":
        return False, "decision packet promoted an unsupported availability claim"
    if row["blockers"] != expected["blockers"]:
        return False, "decision packet blockers drifted from deterministic state"
    if row["evidence_record_ids"] != expected["evidence_record_ids"]:
        return False, "decision packet evidence references drifted"
    if not isinstance(row["summary"], str) or not row["summary"].strip():
        return False, "decision packet summary is empty"
    if row["requires_human_review"] is not True:
        return False, "decision packet attempted to bypass human review"
    return True, "candidate is validator-equivalent despite backend-specific wording"


def _validator_acceptance(product: Any, context: dict[str, Any]) -> tuple[bool, str]:
    row = need_object(product, "acceptance product")
    if set(row) != {"availability_state", "decision_packet"}:
        return False, "acceptance product schema drifted"
    ok, reason = _validator_availability(row["availability_state"], context)
    if not ok:
        return False, reason
    ok, reason = _validator_decision(row["decision_packet"], context)
    if not ok:
        return False, reason
    return True, "controller acceptance product preserves deterministic state and human review"


VALIDATOR_OPERATIONS: dict[str, Callable[[Any, dict[str, Any]], tuple[bool, str]]] = {
    "validate.normalized-records": _validator_normalized_records,
    "validate.availability-state": _validator_availability,
    "validate.decision-packet": _validator_decision,
    "validate.acceptance-product": _validator_acceptance,
}


def run_validators(
    *,
    validator_ids: list[str],
    cartridge: dict[str, Any],
    product: Any,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    registry = {row["id"]: row for row in cartridge["validators"]}
    results = []
    for validator_id in validator_ids:
        validator = registry[validator_id]
        operation = validator["operation"]
        if operation not in VALIDATOR_OPERATIONS:
            raise AnchorError(f"controller validator operation is not implemented: {operation}")
        try:
            passed, detail = VALIDATOR_OPERATIONS[operation](product, context)
        except AnchorError as exc:
            passed, detail = False, str(exc)
        results.append(
            {
                "validator_id": validator_id,
                "operation": operation,
                "hidden": validator["hidden"],
                "controller_owned": True,
                "passed": bool(passed),
                "detail": detail,
            }
        )
    return results


def _input_values(
    *,
    paths: RunPaths,
    artifacts: dict[str, dict[str, Any]],
    refs: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values: dict[str, Any] = {}
    descriptors = []
    for ref in refs:
        if ref not in artifacts:
            raise AnchorError(f"node input reference is not available: {ref}")
        descriptor = artifacts[ref]
        values[ref] = get_artifact(paths, descriptor)
        descriptors.append({"ref": ref, **descriptor})
    return values, descriptors


def _crate(
    *,
    plan: dict[str, Any],
    planned_node: dict[str, Any],
    anchor: dict[str, Any],
    input_descriptors: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "schema": CRATE_SCHEMA,
        "portable_task_id": plan["portable_task_id"],
        "plan_id": plan["plan_id"],
        "anchor_sha256": anchor["anchor_sha256"],
        "node_id": planned_node["node_id"],
        "node_semantic_id": planned_node["node_semantic_id"],
        "execution_id": planned_node["execution_id"],
        "operation": planned_node["operation"],
        "kind": planned_node["kind"],
        "semantic_class": planned_node["semantic_class"],
        "input_artifacts": input_descriptors,
        "output_schema": planned_node["output_schema"],
        "validator_ids": planned_node["validators"],
        "effects": planned_node["effects"],
        "resources": planned_node["resources"],
        "remaining_budget": anchor["budgets"],
        "stop_condition": planned_node["stop_condition"],
        "backend": {
            "id": planned_node["backend"]["id"],
            "manifest_sha256": planned_node["backend"]["manifest_sha256"],
            "architecture": planned_node["backend"]["architecture"],
            "isa": planned_node["backend"]["isa"],
            "runtime_id": planned_node["backend"]["runtime_id"],
            "runtime_version": planned_node["backend"]["runtime_version"],
            "model_identity": planned_node["backend"]["model_identity"],
            "execution_cartridge_id": planned_node["backend"]["execution_cartridge_id"],
            "execution_cartridge_sha256": planned_node["backend"]["execution_cartridge_sha256"],
            "toolchain_sha256": planned_node["backend"]["toolchain_sha256"],
            "lowering_sha256": planned_node["backend"]["lowering_sha256"],
        },
    }
    return {"crate_id": f"handcrate1_{hash_json(body)}", **body}


def _validate_receipt(raw: Any) -> dict[str, Any]:
    row = need_object(raw, "crate receipt")
    if row.get("schema") != RECEIPT_SCHEMA:
        raise AnchorError(f"receipt.schema must be {RECEIPT_SCHEMA}")
    claimed = need_digest(row.get("receipt_sha256"), "receipt.receipt_sha256")
    body = {key: value for key, value in row.items() if key != "receipt_sha256"}
    if hash_json(body) != claimed:
        raise AnchorError("receipt content hash mismatch")
    if row.get("accepted") not in {True, False}:
        raise AnchorError("receipt.accepted must be boolean")
    return row


def run_cartridge(
    raw_floor: Any,
    raw_cartridge: Any,
    raw_registry: Any,
    *,
    run_root: Path,
    controller_cwd: Path,
    bindings: dict[str, str] | None = None,
    resume_anchor: Path | None = None,
    stop_after_node: str | None = None,
) -> dict[str, Any]:
    floor = validate_floor(raw_floor)
    cartridge = validate_cartridge(raw_cartridge)
    registry = validate_backend_registry(raw_registry)
    plan = compile_plan(floor, cartridge, registry, bindings=bindings)
    if verify_plan(floor, cartridge, registry, plan, bindings=bindings):
        raise AnchorError("controller-generated plan failed its own verifier")
    paths = _paths(run_root)
    _ensure_paths(paths)
    backend_map = {row["id"]: row for row in registry["backends"]}
    planned_map = {row["node_id"]: row for row in plan["nodes"]}

    if resume_anchor is None:
        if paths.run_json.exists() or any(paths.anchors.glob("*.json")):
            raise AnchorError("run root already contains state; resume requires an explicit anchor")
        input_descriptor = put_artifact(paths, cartridge["input_payload"])
        artifacts = {"input:readiness_records": input_descriptor}
        node_states = {
            row["node_id"]: {"status": "pending", "attempts": 0}
            for row in plan["nodes"]
        }
        remaining_attempts = {
            row["node_id"]: cartridge["budgets"]["max_attempts_per_node"]
            for row in plan["nodes"]
        }
        anchor = _seal_anchor(
            paths,
            _anchor_body(
                plan=plan,
                cartridge=cartridge,
                parent_anchor_sha256=None,
                sequence=0,
                status="ready",
                node_states=node_states,
                artifacts=artifacts,
                receipt_sha256s=[],
                consumed_wall_ms=0,
                consumed_energy_mwh=0,
                remaining_attempts=remaining_attempts,
            ),
        )
    else:
        if not resume_anchor.is_file():
            raise AnchorError("resume anchor does not exist")
        anchor = _validate_anchor(
            json.loads(resume_anchor.read_text(encoding="utf-8")),
            plan=plan,
            cartridge=cartridge,
        )
        artifacts = deepcopy(anchor["artifacts"])
        node_states = deepcopy(anchor["node_states"])
        remaining_attempts = deepcopy(anchor["budgets"]["remaining_attempts"])
        for descriptor in artifacts.values():
            get_artifact(paths, descriptor)

    run_record = {
        "schema": RUN_SCHEMA,
        "run_id": f"anchorrun1_{hash_json({'plan_id': plan['plan_id'], 'root': run_root.name})}",
        "plan": plan,
        "run_root_name": run_root.name,
        "controller": {
            "implementation": "tier_runner.anchor_crate_runtime",
            "acceptance_authority": True,
            "hash_authority": True,
        },
        "production_claim": False,
        "promotion_authorized": False,
    }
    write_json(paths.run_json, run_record)
    _append_event(
        paths.events,
        {
            "event": "controller_start" if resume_anchor is None else "controller_resume",
            "plan_id": plan["plan_id"],
            "anchor_sha256": anchor["anchor_sha256"],
        },
    )

    receipt_sha256s = list(anchor["receipt_sha256s"])
    consumed_wall_ms = anchor["budgets"]["consumed_wall_ms"]
    consumed_energy_mwh = anchor["budgets"]["consumed_energy_mwh"]

    for planned_node in plan["nodes"]:
        node_id = planned_node["node_id"]
        state = node_states[node_id]
        if state["status"] == "accepted":
            continue
        if state["status"] not in {"pending", "rejected"}:
            raise AnchorError(f"node {node_id} has invalid resumable state {state['status']}")
        for dependency in planned_node["depends_on"]:
            if node_states[dependency]["status"] != "accepted":
                raise AnchorError(f"node {node_id} dependency is not accepted: {dependency}")
        if remaining_attempts[node_id] <= 0:
            raise AnchorError(f"node {node_id} exhausted its attempt budget")

        remaining_attempts[node_id] -= 1
        state["attempts"] += 1
        state["status"] = "active"
        input_values, input_descriptors = _input_values(
            paths=paths, artifacts=artifacts, refs=planned_node["input_refs"]
        )
        crate = _crate(
            plan=plan,
            planned_node=planned_node,
            anchor=anchor,
            input_descriptors=input_descriptors,
        )
        crate_path = paths.crates / f"{planned_node['position']:04d}-{crate['crate_id']}.json"
        write_json(crate_path, crate)
        _append_event(
            paths.events,
            {
                "event": "crate_dispatch",
                "node_id": node_id,
                "crate_id": crate["crate_id"],
                "backend_id": planned_node["backend"]["id"],
                "anchor_sha256": anchor["anchor_sha256"],
            },
        )

        request_body = {
            "schema": DRIVER_REQUEST_SCHEMA,
            "operation": "execute",
            "backend_id": planned_node["backend"]["id"],
            "payload": {
                "crate": crate,
                "inputs": input_values,
            },
        }
        request = {
            "request_id": f"anchorreq1_{hash_json(request_body)}",
            **request_body,
        }
        backend = backend_map[planned_node["backend"]["id"]]
        response = invoke_backend(
            backend,
            request,
            cwd=controller_cwd,
            timeout_ms=anchor["budgets"]["remaining_wall_ms"],
        )
        output_descriptor = put_artifact(paths, response["output"])
        validator_results = run_validators(
            validator_ids=planned_node["validators"],
            cartridge=cartridge,
            product=response["output"],
            context={"inputs": input_values, "artifacts": artifacts},
        )
        accepted = all(item["passed"] for item in validator_results)
        receipt_body = {
            "schema": RECEIPT_SCHEMA,
            "portable_task_id": plan["portable_task_id"],
            "plan_id": plan["plan_id"],
            "node_id": node_id,
            "node_semantic_id": planned_node["node_semantic_id"],
            "execution_id": planned_node["execution_id"],
            "anchor_before_sha256": anchor["anchor_sha256"],
            "crate_id": crate["crate_id"],
            "crate_sha256": hash_json({key: value for key, value in crate.items() if key != "crate_id"}),
            "backend": planned_node["backend"],
            "input_artifacts": input_descriptors,
            "output_artifact": output_descriptor,
            "executor": {
                "request_id": request["request_id"],
                "process_exit_code": response["process_exit_code"],
                "stderr_sha256": response["stderr_sha256"],
                "advisory": response["advisory"],
            },
            "telemetry": {
                **response["telemetry"],
                "controller_elapsed_ms": response["controller_elapsed_ms"],
            },
            "validators": validator_results,
            "accepted": accepted,
            "controller_disposition": "accepted" if accepted else "rejected",
            "production_claim": False,
            "promotion_authorized": False,
        }
        receipt = {
            "receipt_sha256": f"{hash_json(receipt_body)}",
            **receipt_body,
        }
        _validate_receipt(receipt)
        receipt_path = paths.receipts / f"{planned_node['position']:04d}-{receipt['receipt_sha256']}.json"
        write_json(receipt_path, receipt)
        receipt_sha256s.append(receipt["receipt_sha256"])
        consumed_wall_ms += max(
            response["telemetry"]["elapsed_ms"], response["controller_elapsed_ms"]
        )
        consumed_energy_mwh += response["telemetry"]["energy_mwh"]

        if not accepted:
            state["status"] = "rejected"
            state["receipt_sha256"] = receipt["receipt_sha256"]
            state["output_artifact_sha256"] = output_descriptor["sha256"]
            failed_anchor = _seal_anchor(
                paths,
                _anchor_body(
                    plan=plan,
                    cartridge=cartridge,
                    parent_anchor_sha256=anchor["anchor_sha256"],
                    sequence=anchor["sequence"] + 1,
                    status="failed",
                    node_states=node_states,
                    artifacts=artifacts,
                    receipt_sha256s=receipt_sha256s,
                    consumed_wall_ms=consumed_wall_ms,
                    consumed_energy_mwh=consumed_energy_mwh,
                    remaining_attempts=remaining_attempts,
                ),
            )
            raise AnchorError(
                f"node {node_id} was rejected; anchor={failed_anchor['anchor_sha256']}"
            )

        output_ref = f"node:{node_id}"
        artifacts[output_ref] = output_descriptor
        state["status"] = "accepted"
        state["receipt_sha256"] = receipt["receipt_sha256"]
        state["output_ref"] = output_ref
        state["output_artifact_sha256"] = output_descriptor["sha256"]
        next_status = (
            "accepted"
            if node_id == cartridge["acceptance"]["final_node"]
            else "ready"
        )
        anchor = _seal_anchor(
            paths,
            _anchor_body(
                plan=plan,
                cartridge=cartridge,
                parent_anchor_sha256=anchor["anchor_sha256"],
                sequence=anchor["sequence"] + 1,
                status=next_status,
                node_states=node_states,
                artifacts=artifacts,
                receipt_sha256s=receipt_sha256s,
                consumed_wall_ms=consumed_wall_ms,
                consumed_energy_mwh=consumed_energy_mwh,
                remaining_attempts=remaining_attempts,
            ),
        )
        _append_event(
            paths.events,
            {
                "event": "node_accepted",
                "node_id": node_id,
                "receipt_sha256": receipt["receipt_sha256"],
                "anchor_sha256": anchor["anchor_sha256"],
            },
        )
        if stop_after_node == node_id:
            _append_event(
                paths.events,
                {
                    "event": "controller_stop_requested",
                    "node_id": node_id,
                    "anchor_sha256": anchor["anchor_sha256"],
                },
            )
            return {
                "schema": RUN_SCHEMA,
                "status": "paused",
                "run_id": run_record["run_id"],
                "portable_task_id": plan["portable_task_id"],
                "plan_id": plan["plan_id"],
                "anchor": anchor,
                "final_product": None,
                "production_claim": False,
                "promotion_authorized": False,
            }

    final_node = cartridge["acceptance"]["final_node"]
    if node_states[final_node]["status"] != "accepted":
        raise AnchorError("controller ended without accepting the declared final node")
    final_product = get_artifact(paths, artifacts[f"node:{final_node}"])
    result = {
        "schema": RUN_SCHEMA,
        "status": "accepted",
        "run_id": run_record["run_id"],
        "portable_task_id": plan["portable_task_id"],
        "plan_id": plan["plan_id"],
        "anchor": anchor,
        "final_product": final_product,
        "receipt_sha256s": receipt_sha256s,
        "bindings": plan["bindings"],
        "consumed_wall_ms": consumed_wall_ms,
        "consumed_energy_mwh": consumed_energy_mwh,
        "production_claim": False,
        "promotion_authorized": False,
    }
    write_json(paths.root / "result.json", result)
    _append_event(
        paths.events,
        {
            "event": "run_accepted",
            "run_id": run_record["run_id"],
            "anchor_sha256": anchor["anchor_sha256"],
        },
    )
    return result


def backend_conformance(
    raw_registry: Any,
    *,
    backend_id: str,
    controller_cwd: Path,
) -> dict[str, Any]:
    registry = validate_backend_registry(raw_registry)
    backends = {row["id"]: row for row in registry["backends"]}
    if backend_id not in backends:
        raise AnchorError(f"unknown backend: {backend_id}")
    backend = backends[backend_id]
    cases: list[dict[str, Any]] = []

    def call(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "schema": DRIVER_REQUEST_SCHEMA,
            "operation": operation,
            "backend_id": backend_id,
            "payload": payload,
        }
        request = {"request_id": f"anchorreq1_{hash_json(body)}", **body}
        return invoke_backend(backend, request, cwd=controller_cwd, timeout_ms=30_000)

    describe = call("describe", {})
    cases.append({"id": "describe", "passed": describe["output"]["backend_id"] == backend_id})
    probe = call("probe", {"required_capabilities": ["structured-json"]})
    cases.append(
        {
            "id": "probe",
            "passed": probe["output"]["backend_id"] == backend_id
            and "structured-json" in probe["output"]["capabilities"],
        }
    )
    if "candidate-generation" in backend["capabilities"]:
        execute_payload = {
            "crate": {"operation": "decision.generate"},
            "inputs": {"node:derive_availability": _expected_availability()},
        }
        executed = call("execute", execute_payload)
        execute_ok, _ = _validator_decision(executed["output"], {})
    else:
        execute_payload = {
            "crate": {"operation": "records.normalize"},
            "inputs": {
                "input:readiness_records": {
                    "asset_id": "a-17",
                    "records": [
                        {
                            "record_id": "INV-001",
                            "record_type": "Inventory",
                            "asset_id": "a-17",
                            "status": "On Hand",
                            "value": {
                                "quantity": 1,
                                "condition": "unserviceable",
                                "allocated": False,
                            },
                        },
                        {
                            "record_id": "WO-001",
                            "record_type": "Maintenance",
                            "asset_id": "A-17",
                            "status": "Open",
                            "value": {"work_order_open": True, "work_order": "MX-884"},
                        },
                        {
                            "record_id": "DUE-001",
                            "record_type": "Due_In",
                            "asset_id": "A-17",
                            "status": "Delayed",
                            "value": {
                                "status": "delayed",
                                "expected_date": "2026-08-19",
                            },
                        },
                    ],
                }
            },
        }
        executed = call("execute", execute_payload)
        execute_ok, _ = _validator_normalized_records(executed["output"], {})
    cases.append({"id": "execute", "passed": execute_ok})
    collect = call("collect", {})
    cases.append({"id": "collect", "passed": collect["output"] == {"state": "no_async_work"}})
    cancel = call("cancel", {})
    cases.append({"id": "cancel", "passed": cancel["output"] == {"state": "no_async_work"}})
    body = {
        "schema": "tier-bench/anchor-backend-conformance@1",
        "backend_id": backend_id,
        "backend_manifest_sha256": hash_json(backend),
        "cases": cases,
        "passed": all(item["passed"] for item in cases),
        "physical_qualification": backend["physical_qualification"],
        "production_claim": False,
        "promotion_authorized": False,
    }
    return {"report_sha256": hash_json(body), **body}
