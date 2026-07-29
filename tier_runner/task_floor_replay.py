"""Safe replay plans and draft skill packages derived from accepted trajectories."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .playwright_computer_common import (
    PlaywrightComputerError,
    hash_file,
    hash_json,
    now_utc,
)
from .task_floor_export import verify_bundle
from .task_floor_protocol import (
    REPLAY_PLAN_SCHEMA,
    SKILL_SCHEMA,
    seal_skill_package,
)

HIGH_RISK_EFFECTS = {
    "external_write",
    "destructive",
    "financial",
    "identity",
    "sensitive",
    "privileged",
}


def compile_replay_plan(
    bundle: dict[str, Any],
    *,
    mode: str = "simulate",
    allow_effects: list[str] | None = None,
) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot replay invalid bundle: " + "; ".join(errors)
        )
    if mode not in {"simulate", "counterfactual", "execute"}:
        raise PlaywrightComputerError(
            "replay mode must be simulate, counterfactual, or execute"
        )
    permitted = set(allow_effects or ["read", "interactive"])
    events = bundle["trajectory"]["events"]
    steps: list[dict[str, Any]] = []
    by_step: dict[int, dict[str, Any]] = {}
    for event in events:
        step = event.get("step_number")
        if step is None:
            continue
        row = by_step.setdefault(
            int(step),
            {
                "step_number": int(step),
                "starting_state_id": None,
                "completed_state_id": None,
                "actions": [],
                "evidence": [],
            },
        )
        if event["kind"] == "step.started":
            row["starting_state_id"] = event["data"].get("state_id")
        elif event["kind"] == "step.finished":
            row["completed_state_id"] = event["data"].get("state_id")
        elif event["kind"] == "action.executed":
            action = event["data"].get("action") or {}
            effect = action.get("effect") or event["data"].get("effect")
            row["actions"].append(
                {
                    "action": action,
                    "effect": effect,
                    "idempotency_key": event["data"].get("idempotency_key"),
                    "event_sha256": event["event_sha256"],
                    "admitted_for_execution": (
                        mode == "execute" and effect in permitted
                    ),
                    "requires_new_approval": effect in HIGH_RISK_EFFECTS,
                }
            )
        row["evidence"].append(event["event_sha256"])
    steps = [by_step[key] for key in sorted(by_step)]
    blocked = [
        {
            "step_number": step["step_number"],
            "effect": action["effect"],
            "event_sha256": action["event_sha256"],
        }
        for step in steps
        for action in step["actions"]
        if mode == "execute" and not action["admitted_for_execution"]
    ]
    value: dict[str, Any] = {
        "schema": REPLAY_PLAN_SCHEMA,
        "created_at": now_utc(),
        "mode": mode,
        "source": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trajectory_sha256": bundle["trajectory"]["trajectory_sha256"],
            "run_id": bundle["run"]["run_id"],
        },
        "cartridge": {
            "id": bundle["cartridge"]["id"],
            "cartridge_sha256": bundle["cartridge"]["cartridge_sha256"],
            "failure_default": bundle["cartridge"]["failure_default"],
        },
        "allow_effects": sorted(permitted),
        "steps": steps,
        "blocked_actions": blocked,
        "execution_authorized": mode == "execute" and not blocked,
        "notice": (
            "Replay is fail-closed. State must be re-observed before execution, "
            "idempotency receipts must be consulted, and high-risk effects always "
            "require a new approval bound to the new state."
        ),
    }
    value["replay_plan_sha256"] = hash_json(value)
    return value


def propose_skill_package(
    bundle: dict[str, Any],
    *,
    skill_id: str,
    version: str,
    name: str,
    entrypoint: str,
    artifact_path: Path,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = verify_bundle(bundle)
    if errors:
        raise PlaywrightComputerError(
            "cannot compile skill from invalid bundle: " + "; ".join(errors)
        )
    if bundle["run"]["status"] != "ACCEPTED":
        raise PlaywrightComputerError(
            "only externally accepted trajectories may propose a skill package"
        )
    artifact_path = artifact_path.resolve()
    if not artifact_path.is_file():
        raise PlaywrightComputerError(f"skill artifact does not exist: {artifact_path}")
    acceptance_sha256 = hash_json(bundle["acceptance"])
    effects = sorted(
        {
            event["data"].get("effect")
            or (event["data"].get("action") or {}).get("effect")
            for event in bundle["trajectory"]["events"]
            if event["kind"] == "action.executed"
            and (
                event["data"].get("effect")
                or (event["data"].get("action") or {}).get("effect")
            )
        }
    )
    value = {
        "schema": SKILL_SCHEMA,
        "id": skill_id,
        "version": version,
        "name": name,
        "description": (
            "Draft skill derived from one externally accepted Task Floor trajectory. "
            "It requires independent review, mutation tests, signatures, and explicit "
            "production authorization before use outside the lab."
        ),
        "source": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trajectory_sha256": bundle["trajectory"]["trajectory_sha256"],
            "run_id": bundle["run"]["run_id"],
            "acceptance_sha256": acceptance_sha256,
        },
        "entrypoint": entrypoint,
        "runtime": runtime or {"kind": "unspecified", "version": "unspecified"},
        "inputs": {
            "task_floor_state": "task-floor/state@1",
            "task_floor_cartridge": bundle["cartridge"]["cartridge_sha256"],
        },
        "outputs": {
            "task_floor_action_receipts": "task-floor/action-receipt@1"
        },
        "effects": effects,
        "supported_cartridges": [bundle["cartridge"]["id"]],
        "compatibility": {
            "manifest": bundle["manifest"]["manifest_sha256"],
            "state_schema": "task-floor/state@1",
            "action_schema": "task-floor/action@1",
        },
        "tests": [
            {
                "kind": "source-run",
                "bundle_sha256": bundle["bundle_sha256"],
                "status": "passed",
            },
            {
                "kind": "mutation-suite",
                "status": "required",
                "dimensions": bundle["cartridge"]["mutation_dimensions"],
            },
            {"kind": "prompt-injection", "status": "required"},
            {"kind": "role-reversal", "status": "required"},
        ],
        "review": {
            "status": "unreviewed",
            "required_authorities": ["project-owner", "policy-owner"],
            "review_receipts": [],
        },
        "rollback": {
            "supported": False,
            "strategy": "disable-package-and-revert-to-planner",
        },
        "artifacts": [
            {
                "path": artifact_path.name,
                "bytes": artifact_path.stat().st_size,
                "digest": {"sha256": hash_file(artifact_path)},
            }
        ],
        "signatures": [],
        "production_authorized": False,
    }
    return seal_skill_package(value)
