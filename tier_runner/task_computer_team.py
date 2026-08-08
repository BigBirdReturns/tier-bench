"""Independent planner and critic seats for distributed Task Computer runs."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Protocol

from .playwright_computer_common import (
    PlaywrightComputerError,
    atomic_json,
    canonical,
    hash_json,
    load_json,
    without_hash,
)
from .task_computer_protocol import PROPOSAL_SCHEMA, validate_proposal

CRITIC_REQUEST_SCHEMA = "tier-bench/task-computer-critic-request@1"
CRITIC_RESPONSE_SCHEMA = "tier-bench/task-computer-critic-response@1"


class PlannerLike(Protocol):
    def propose(self, packet: dict[str, Any]) -> dict[str, Any]: ...


class Critic(Protocol):
    def review(
        self,
        packet: dict[str, Any],
        proposal: dict[str, Any],
    ) -> dict[str, Any]: ...


def compile_critic_request(
    packet: dict[str, Any], proposal: dict[str, Any]
) -> dict[str, Any]:
    if proposal.get("packet_sha256") != packet.get("packet_sha256"):
        raise PlaywrightComputerError("critic proposal belongs to another planner packet")
    request: dict[str, Any] = {
        "schema": CRITIC_REQUEST_SCHEMA,
        "run_id": packet["run_id"],
        "scenario_id": packet["scenario_id"],
        "project": packet["project"],
        "variant": packet["variant"],
        "step_number": packet["step_number"],
        "packet_sha256": packet["packet_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "goal": packet["goal"],
        "acceptance": packet["acceptance"],
        "effect_policy": packet["effect_policy"],
        "allowed_ops": packet["allowed_ops"],
        "state": packet["state"],
        "proposal": proposal,
        "response_contract": {
            "schema": CRITIC_RESPONSE_SCHEMA,
            "required": [
                "request_sha256",
                "pass",
                "errors",
                "warnings",
                "rationale",
            ],
        },
    }
    request["request_sha256"] = hash_json(request)
    return request


def validate_critic_response(
    value: Any, request: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlaywrightComputerError("critic response must be an object")
    if value.get("schema", CRITIC_RESPONSE_SCHEMA) != CRITIC_RESPONSE_SCHEMA:
        raise PlaywrightComputerError(
            f"critic response schema must be {CRITIC_RESPONSE_SCHEMA}"
        )
    if value.get("request_sha256") != request["request_sha256"]:
        raise PlaywrightComputerError("critic response belongs to another request")
    passed = value.get("pass")
    if not isinstance(passed, bool):
        raise PlaywrightComputerError("critic response pass must be boolean")
    errors = value.get("errors", [])
    warnings = value.get("warnings", [])
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        raise PlaywrightComputerError("critic response errors must be an array of strings")
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) for item in warnings
    ):
        raise PlaywrightComputerError("critic response warnings must be an array of strings")
    rationale = value.get("rationale", "")
    if not isinstance(rationale, str) or len(rationale) > 12000:
        raise PlaywrightComputerError("critic response rationale must be a bounded string")
    if passed and errors:
        raise PlaywrightComputerError("passing critic response cannot contain errors")
    result: dict[str, Any] = {
        "schema": CRITIC_RESPONSE_SCHEMA,
        "request_sha256": request["request_sha256"],
        "pass": passed,
        "errors": errors,
        "warnings": warnings,
        "rationale": rationale,
        "model": value.get("model"),
        "seat": value.get("seat"),
    }
    result["response_sha256"] = hash_json(result)
    return result


def _run_command(
    command: str | list[str], payload: dict[str, Any], timeout_seconds: float
) -> dict[str, Any]:
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if not argv:
        raise PlaywrightComputerError("team command cannot be empty")
    try:
        result = subprocess.run(
            argv,
            input=canonical(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlaywrightComputerError(f"team command failed to execute: {exc}") from exc
    if result.returncode:
        raise PlaywrightComputerError(
            f"team command exited {result.returncode}: "
            + result.stderr.decode("utf-8", errors="replace")[-4000:]
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PlaywrightComputerError(
            "team command returned invalid JSON: "
            + result.stdout.decode("utf-8", errors="replace")[-4000:]
        ) from exc
    if not isinstance(value, dict):
        raise PlaywrightComputerError("team command output must be a JSON object")
    return value


class CommandCritic:
    def __init__(self, command: str | list[str], *, timeout_seconds: float = 300.0):
        self.command = command
        self.timeout_seconds = timeout_seconds

    def review(
        self, packet: dict[str, Any], proposal: dict[str, Any]
    ) -> dict[str, Any]:
        request = compile_critic_request(packet, proposal)
        return validate_critic_response(
            _run_command(self.command, request, self.timeout_seconds),
            request,
        )


class FileExchangeCritic:
    """Send the proposal to a separately claimed critic seat over shared storage."""

    def __init__(
        self,
        exchange_root: Path,
        *,
        role: str = "critic",
        timeout_seconds: float = 1800.0,
        poll_seconds: float = 0.5,
    ):
        self.exchange_root = exchange_root.resolve()
        self.role = role
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def review(
        self, packet: dict[str, Any], proposal: dict[str, Any]
    ) -> dict[str, Any]:
        request_value = compile_critic_request(packet, proposal)
        run_id = packet["run_id"]
        step = int(packet["step_number"])
        stem = f"{step:04d}-{request_value['request_sha256'][:16]}"
        request = self.exchange_root / run_id / self.role / "requests" / f"{stem}.json"
        response = self.exchange_root / run_id / self.role / "responses" / f"{stem}.json"
        atomic_json(request, request_value)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() <= deadline:
            if response.exists():
                return validate_critic_response(load_json(response), request_value)
            time.sleep(self.poll_seconds)
        raise PlaywrightComputerError(
            f"timed out waiting for {self.role} response {response}"
        )


class TeamedPlanner:
    """Require an independent critic response before returning a proposal to the desktop."""

    def __init__(self, planner: PlannerLike, critic: Critic):
        self.planner = planner
        self.critic = critic
        self.last_critic_response: dict[str, Any] | None = None

    def propose(self, packet: dict[str, Any]) -> dict[str, Any]:
        proposal = validate_proposal(self.planner.propose(packet), packet)
        response = self.critic.review(packet, proposal)
        self.last_critic_response = response
        if not response["pass"]:
            details = "; ".join(response["errors"]) or response["rationale"]
            raise PlaywrightComputerError(
                "independent critic rejected planner proposal: " + details
            )
        return proposal
