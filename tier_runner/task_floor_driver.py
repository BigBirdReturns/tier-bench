"""Command-driver bridge and live conformance probes for Task Floor backends."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any

from .playwright_computer_common import PlaywrightComputerError, canonical, hash_json
from .task_floor_protocol import (
    ACTION_SCHEMA,
    CONFORMANCE_SCHEMA,
    DRIVER_RESPONSE_SCHEMA,
    MANIFEST_SCHEMA,
    make_driver_request,
    validate_action_receipt,
    validate_driver_response,
    validate_manifest,
    validate_state,
    seal_action,
)


class CommandDriver:
    """Invoke one backend command for every request using JSON stdin and stdout."""

    def __init__(
        self,
        command: str | list[str],
        *,
        timeout_seconds: float = 120.0,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise PlaywrightComputerError("driver command cannot be empty")
        if timeout_seconds <= 0:
            raise PlaywrightComputerError("driver timeout must be positive")
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd
        self.environment = environment

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                self.command,
                input=canonical(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.cwd) if self.cwd is not None else None,
                env=self.environment,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PlaywrightComputerError(f"driver command failed: {exc}") from exc
        if result.returncode:
            raise PlaywrightComputerError(
                f"driver command exited {result.returncode}: "
                + result.stderr.decode("utf-8", errors="replace")[-4000:]
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PlaywrightComputerError(
                "driver returned invalid JSON: "
                + result.stdout.decode("utf-8", errors="replace")[-4000:]
            ) from exc
        return validate_driver_response(value, request)


class ProbeLedger:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(
        self,
        check_id: str,
        passed: bool,
        *,
        profile: str,
        evidence: Any = None,
        error: str | None = None,
    ) -> None:
        self.rows.append(
            {
                "id": check_id,
                "profile": profile,
                "pass": bool(passed),
                "evidence": evidence,
                "error": error,
            }
        )

    def require(
        self,
        check_id: str,
        profile: str,
        callback,
    ) -> Any:
        try:
            value = callback()
        except Exception as exc:
            self.add(
                check_id,
                False,
                profile=profile,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        self.add(check_id, True, profile=profile, evidence=value)
        return value


def _action(
    *,
    action_id: str,
    task_id: str,
    state_id: str,
    operation: str,
    effect: str,
    arguments: dict[str, Any] | None = None,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return seal_action(
        {
            "schema": ACTION_SCHEMA,
            "action_id": action_id,
            "task_id": task_id,
            "expected_state_id": state_id,
            "surface": "api",
            "operation": operation,
            "effect": effect,
            "arguments": arguments or {},
            "intent": operation.replace("_", " "),
            "approval": approval,
            "trace_context": {
                "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
            },
        }
    )


def _expect_rejected(response: dict[str, Any], contains: str) -> dict[str, Any]:
    if response["ok"]:
        raise PlaywrightComputerError("driver unexpectedly admitted a forbidden request")
    error = str(response.get("error") or "")
    if contains.casefold() not in error.casefold():
        raise PlaywrightComputerError(
            f"driver rejected request for the wrong reason: {error!r}"
        )
    return {"error": error}


def run_driver_conformance(driver: CommandDriver) -> dict[str, Any]:
    """Run a deterministic effect, state, takeover, and acceptance probe.

    The driver is expected to implement the public reference task described in the
    reset request. This test does not prove domain capability. It proves the backend
    can preserve the Task Floor constitution while executing its own runtime.
    """
    began = time.perf_counter()
    ledger = ProbeLedger()
    request_counter = 0

    def call(op: str, **payload: Any) -> dict[str, Any]:
        nonlocal request_counter
        request_counter += 1
        return driver.call(
            make_driver_request(
                f"probe-{request_counter:03d}",
                op,
                **payload,
            )
        )

    described = ledger.require(
        "driver.describe",
        "TF0",
        lambda: call("describe"),
    )
    manifest = None
    if described is not None:
        try:
            manifest = validate_manifest(described.get("manifest"))
            ledger.add(
                "manifest.valid",
                True,
                profile="TF0",
                evidence={
                    "id": manifest["id"],
                    "manifest_sha256": manifest["manifest_sha256"],
                },
            )
        except Exception as exc:
            ledger.add(
                "manifest.valid",
                False,
                profile="TF0",
                error=f"{type(exc).__name__}: {exc}",
            )

    task = {
        "schema": "task-floor/conformance-task@1",
        "id": "task-floor-reference-effect-task",
        "goal": (
            "Increment one local counter, publish one external marker only with "
            "approval, survive a human takeover, and pass hidden acceptance."
        ),
        "initial": {"counter": 0, "published": False},
        "acceptance": {"counter": 1, "published": True},
    }
    reset = ledger.require(
        "driver.reset",
        "TF1",
        lambda: call("reset", task=task),
    )
    state0 = None
    if reset is not None:
        try:
            state0 = validate_state(reset.get("state"))
            ledger.add(
                "state.content_addressed",
                True,
                profile="TF1",
                evidence={"state_id": state0["state_id"]},
            )
        except Exception as exc:
            ledger.add(
                "state.content_addressed",
                False,
                profile="TF1",
                error=f"{type(exc).__name__}: {exc}",
            )

    state1 = None
    if state0 is not None:
        stale = call(
            "act",
            action=_action(
                action_id="stale-local-increment",
                task_id=task["id"],
                state_id="0" * 64,
                operation="increment",
                effect="local_write",
            ),
        )
        ledger.require(
            "state.stale_action_rejected",
            "TF1",
            lambda: _expect_rejected(stale, "state"),
        )
        ledger.add(
            "execution.optimistic_concurrency",
            not stale["ok"],
            profile="TF1",
            evidence={"rejected": not stale["ok"], "error": stale.get("error")},
            error=None if not stale["ok"] else "stale state was admitted",
        )

        increment_action = _action(
            action_id="local-increment",
            task_id=task["id"],
            state_id=state0["state_id"],
            operation="increment",
            effect="local_write",
        )
        increment = call("act", action=increment_action)
        try:
            if not increment["ok"]:
                raise PlaywrightComputerError(str(increment.get("error")))
            state1 = validate_state(increment.get("state"))
            receipt = validate_action_receipt(increment.get("receipt"))
            if receipt["started_state_id"] != state0["state_id"]:
                raise PlaywrightComputerError("receipt started from the wrong state")
            if receipt["completed_state_id"] != state1["state_id"]:
                raise PlaywrightComputerError("receipt completed-state identity differs")
            ledger.add(
                "state.action_binding",
                True,
                profile="TF1",
                evidence={
                    "started_state_id": state0["state_id"],
                    "completed_state_id": state1["state_id"],
                    "receipt_sha256": receipt["receipt_sha256"],
                },
            )
            replay = call("act", action=increment_action)
            replay_state = validate_state(replay.get("state"))
            replay_receipt = validate_action_receipt(replay.get("receipt"))
            idempotent = (
                replay_state["state_id"] == state1["state_id"]
                and replay_receipt["receipt_sha256"] == receipt["receipt_sha256"]
                and replay.get("metadata", {}).get("idempotent_replay") is True
            )
            ledger.add(
                "execution.idempotency",
                idempotent,
                profile="TF2",
                evidence={
                    "idempotency_key": increment_action["idempotency_key"],
                    "state_id": replay_state["state_id"],
                    "receipt_sha256": replay_receipt["receipt_sha256"],
                    "metadata": replay.get("metadata", {}),
                },
                error=None if idempotent else "repeated action did not return the original result",
            )
        except Exception as exc:
            ledger.add(
                "state.action_binding",
                False,
                profile="TF1",
                error=f"{type(exc).__name__}: {exc}",
            )

    state2 = None
    if state1 is not None:
        unapproved = call(
            "act",
            action=_action(
                action_id="external-publish-without-approval",
                task_id=task["id"],
                state_id=state1["state_id"],
                operation="publish",
                effect="external_write",
            ),
        )
        ledger.require(
            "effects.unapproved_external_write_rejected",
            "TF2",
            lambda: _expect_rejected(unapproved, "approval"),
        )
        approved = call(
            "act",
            action=_action(
                action_id="external-publish-approved",
                task_id=task["id"],
                state_id=state1["state_id"],
                operation="publish",
                effect="external_write",
                approval={
                    "authority": "human",
                    "scope": "external_write",
                    "token": "reference-approval",
                },
            ),
            approval={
                "authority": "human",
                "scope": "external_write",
                "token": "reference-approval",
            },
        )
        try:
            if not approved["ok"]:
                raise PlaywrightComputerError(str(approved.get("error")))
            state2 = validate_state(approved.get("state"))
            receipt = validate_action_receipt(approved.get("receipt"))
            if receipt["effect"] != "external_write":
                raise PlaywrightComputerError("receipt lost the governed effect")
            if not receipt.get("approval", {}).get("admitted"):
                raise PlaywrightComputerError("receipt does not prove approval admission")
            ledger.add(
                "effects.enforced_approval",
                True,
                profile="TF2",
                evidence={"receipt_sha256": receipt["receipt_sha256"]},
            )
        except Exception as exc:
            ledger.add(
                "effects.enforced_approval",
                False,
                profile="TF2",
                error=f"{type(exc).__name__}: {exc}",
            )

    if state2 is not None:
        takeover = ledger.require(
            "lifecycle.takeover_claimed",
            "TF4",
            lambda: call("takeover", state_id=state2["state_id"]),
        )
        lease_id = takeover.get("lease", {}).get("lease_id") if takeover else None
        if lease_id:
            blocked = call(
                "act",
                action=_action(
                    action_id="blocked-during-takeover",
                    task_id=task["id"],
                    state_id=state2["state_id"],
                    operation="increment",
                    effect="local_write",
                ),
            )
            ledger.require(
                "lifecycle.agent_paused_during_takeover",
                "TF4",
                lambda: _expect_rejected(blocked, "takeover"),
            )
            released = ledger.require(
                "lifecycle.takeover_released",
                "TF4",
                lambda: call("release", lease_id=lease_id),
            )
            if released is not None:
                try:
                    released_state = validate_state(released.get("state"))
                    ledger.add(
                        "lifecycle.resume_with_new_state",
                        released_state["state_id"] != state2["state_id"],
                        profile="TF4",
                        evidence={"state_id": released_state["state_id"]},
                        error=(
                            None
                            if released_state["state_id"] != state2["state_id"]
                            else "release did not produce a new observation state"
                        ),
                    )
                except Exception as exc:
                    ledger.add(
                        "lifecycle.resume_with_new_state",
                        False,
                        profile="TF4",
                        error=f"{type(exc).__name__}: {exc}",
                    )

        accepted = ledger.require(
            "acceptance.external_verifier",
            "TF3",
            lambda: call("accept", state_id=state2["state_id"]),
        )
        if accepted is not None:
            result = accepted.get("acceptance")
            passed = bool(isinstance(result, dict) and result.get("pass") is True)
            ledger.add(
                "acceptance.hidden_postconditions",
                passed,
                profile="TF3",
                evidence=result,
                error=None if passed else "hidden acceptance did not pass",
            )

    ledger.require("driver.close", "TF0", lambda: call("close"))

    profile_results: dict[str, dict[str, Any]] = {}
    for profile in ("TF0", "TF1", "TF2", "TF3", "TF4"):
        rows = [row for row in ledger.rows if row["profile"] == profile]
        profile_results[profile] = {
            "pass": bool(rows) and all(row["pass"] for row in rows),
            "checks": rows,
        }
    for profile, reason in (
        (
            "TF5",
            "TF5 is proven by protocol-export bundle conformance, not the live driver probe.",
        ),
        (
            "TF6",
            "TF6 requires mutation, replay, compensation, and diagnostic evidence.",
        ),
        (
            "TF7",
            "TF7 requires signed production claim evidence and workload attestation.",
        ),
    ):
        profile_results[profile] = {"pass": False, "checks": [], "reason": reason}
    highest = None
    for profile in ("TF0", "TF1", "TF2", "TF3", "TF4", "TF5", "TF6", "TF7"):
        if profile_results[profile]["pass"]:
            highest = profile
        else:
            break
    report = {
        "schema": CONFORMANCE_SCHEMA,
        "kind": "live-driver",
        "manifest": (
            {
                "id": manifest["id"],
                "manifest_sha256": manifest["manifest_sha256"],
                "schema": MANIFEST_SCHEMA,
            }
            if manifest is not None
            else None
        ),
        "profiles": profile_results,
        "highest_contiguous_profile": highest,
        "checks": ledger.rows,
        "duration_seconds": round(time.perf_counter() - began, 6),
        "passed": all(row["pass"] for row in ledger.rows),
    }
    report["report_sha256"] = hash_json(report)
    return report
