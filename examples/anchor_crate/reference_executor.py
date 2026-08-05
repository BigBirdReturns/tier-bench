#!/usr/bin/env python3
"""Stateless reference executor for the Anchor Crate command ABI.

This process is deliberately advisory. It never computes canonical hashes, runs hidden
acceptance, mutates the anchor, or claims that its output is accepted.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

REQUEST_SCHEMA = "tier-bench/anchor-executor-request@1"
RESPONSE_SCHEMA = "tier-bench/anchor-executor-response@1"


def normalize_records(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload["records"]
    normalized = []
    for record in records:
        normalized.append(
            {
                "record_id": str(record["record_id"]).strip().lower(),
                "record_type": str(record["record_type"]).strip().lower(),
                "asset_id": str(record["asset_id"]).strip().upper(),
                "status": str(record["status"]).strip().lower(),
                "value": record["value"],
            }
        )
    normalized.sort(key=lambda item: (item["record_type"], item["record_id"]))
    return {"asset_id": payload["asset_id"].upper(), "records": normalized}


def derive_availability(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload["records"]
    by_type = {record["record_type"]: record for record in records}
    inventory = by_type["inventory"]
    maintenance = by_type["maintenance"]
    due_in = by_type["due_in"]
    physically_available = bool(
        inventory["value"]["quantity"] > 0
        and inventory["value"]["condition"] == "serviceable"
        and inventory["value"]["allocated"] is False
        and maintenance["value"]["work_order_open"] is False
    )
    blockers = []
    if inventory["value"]["condition"] != "serviceable":
        blockers.append("on-hand part is not serviceable")
    if inventory["value"]["allocated"]:
        blockers.append("on-hand part is allocated elsewhere")
    if maintenance["value"]["work_order_open"]:
        blockers.append("maintenance work order remains open")
    if due_in["value"]["status"] != "on_time":
        blockers.append("replacement due-in is delayed")
    return {
        "asset_id": payload["asset_id"],
        "physically_available": physically_available,
        "blockers": blockers,
        "evidence_record_ids": sorted(record["record_id"] for record in records),
    }


def decision_packet(payload: dict[str, Any], backend_id: str) -> dict[str, Any]:
    state = payload["availability_state"]
    if backend_id == "backend.riscv-llm-fixture":
        summary = (
            f"{state['asset_id']} remains unavailable: " + "; ".join(state["blockers"]) + "."
        )
    elif backend_id == "backend.cuda3090-fixture":
        summary = (
            f"Asset {state['asset_id']} is not physically serviceable because "
            + "; ".join(state["blockers"])
            + "."
        )
    else:
        summary = (
            f"Readiness review for {state['asset_id']}: " + "; ".join(state["blockers"]) + "."
        )
    return {
        "asset_id": state["asset_id"],
        "claim": "physically_available" if state["physically_available"] else "not_physically_available",
        "blockers": state["blockers"],
        "evidence_record_ids": state["evidence_record_ids"],
        "summary": summary,
        "requires_human_review": True,
    }


def acceptance_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "availability_state": payload["availability_state"],
        "decision_packet": payload["decision_packet"],
    }


def execute(operation: str, inputs: dict[str, Any], backend_id: str) -> dict[str, Any]:
    if operation == "records.normalize":
        return normalize_records(inputs["input:readiness_records"])
    if operation == "readiness.derive":
        return derive_availability(inputs["node:normalize_records"])
    if operation == "decision.generate":
        return decision_packet(
            {"availability_state": inputs["node:derive_availability"]}, backend_id
        )
    if operation == "acceptance.project":
        return acceptance_projection(
            {
                "availability_state": inputs["node:derive_availability"],
                "decision_packet": inputs["node:generate_decision_packet"],
            }
        )
    raise ValueError(f"unsupported operation: {operation}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    args = parser.parse_args(argv)
    request = json.load(sys.stdin)
    if request.get("schema") != REQUEST_SCHEMA:
        raise SystemExit("invalid request schema")
    operation = request["operation"]
    payload = request.get("payload", {})
    response: dict[str, Any] = {
        "schema": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "backend_id": args.backend,
        "status": "ok",
        "output": None,
        "telemetry": {
            "status": "ok",
            "elapsed_ms": 1,
            "memory_peak_mib": 16,
            "energy_mwh": 0,
        },
        "advisory": [],
    }
    if operation == "describe":
        response["output"] = {"backend_id": args.backend, "protocol": RESPONSE_SCHEMA}
    elif operation == "probe":
        response["output"] = {
            "backend_id": args.backend,
            "capabilities": payload.get("required_capabilities", []),
            "probe": "fixture-only",
        }
    elif operation == "execute":
        crate = payload["crate"]
        response["output"] = execute(crate["operation"], payload["inputs"], args.backend)
    elif operation in {"cancel", "collect"}:
        response["output"] = {"state": "no_async_work"}
    else:
        response["status"] = "error"
        response["output"] = None
        response["advisory"] = [f"unsupported driver operation: {operation}"]
    json.dump(response, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0 if response["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
