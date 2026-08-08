"""Reference, command, and shared-file planners for Task Computer experiments."""
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
    load_json,
)
from .task_computer_fixture_oracles import install_fixture_oracles
from .task_computer_protocol import (
    PLAYWRIGHT_TARGET_OPS,
    PROPOSAL_SCHEMA,
    resolve_element,
    validate_proposal,
)

# Install only the explicitly labeled synthetic visual candidates used by the
# deterministic project fixtures. This does not participate in real ScreenGhost
# execution or claim model-derived visual evidence.
install_fixture_oracles()


class Planner(Protocol):
    def propose(self, packet: dict[str, Any]) -> dict[str, Any]: ...


class ReferencePlanner:
    """A deterministic semantic baseline. It never reads fixture-hidden state."""

    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.index = 0
        self.wait_count = 0

    def propose(self, packet: dict[str, Any]) -> dict[str, Any]:
        plan = self.scenario["reference_plan"]
        if self.index >= len(plan):
            proposal = {
                "schema": PROPOSAL_SCHEMA,
                "packet_sha256": packet["packet_sha256"],
                "state_id": packet["state"]["state_id"],
                "actions": [],
                "done": True,
                "memory": f"Completed {len(plan)} of {len(plan)} reference steps.",
                "next_goal": "Return the task for external acceptance.",
            }
            return validate_proposal(proposal, packet)
        step = plan[self.index]
        if step["surface"] == "playwright" and step["op"] in PLAYWRIGHT_TARGET_OPS:
            try:
                resolve_element(packet["state"], step["target"])
            except PlaywrightComputerError:
                self.wait_count += 1
                proposal = {
                    "schema": PROPOSAL_SCHEMA,
                    "packet_sha256": packet["packet_sha256"],
                    "state_id": packet["state"]["state_id"],
                    "actions": [
                        {
                            "id": f"wait-for-{step['id']}-{self.wait_count:02d}",
                            "surface": "playwright",
                            "op": "wait",
                            "effect": "read",
                            "intent": f"Wait for the current page to expose the target for {step['id']}",
                            "target": None,
                            "args": {
                                "seconds": min(
                                    max(step["retry_seconds"] / 3.0, 0.1),
                                    1.0,
                                )
                            },
                        }
                    ],
                    "done": False,
                    "memory": (
                        f"The target for reference step {step['id']} is not yet present. "
                        "The page may still be settling."
                    ),
                    "next_goal": step["intent"],
                }
                return validate_proposal(proposal, packet)
        self.index += 1
        self.wait_count = 0
        proposal = {
            "schema": PROPOSAL_SCHEMA,
            "packet_sha256": packet["packet_sha256"],
            "state_id": packet["state"]["state_id"],
            "actions": [
                {
                    "id": step["id"],
                    "surface": step["surface"],
                    "op": step["op"],
                    "effect": step["effect"],
                    "intent": step["intent"],
                    "target": step["target"],
                    "args": step["args"],
                }
            ],
            "done": False,
            "memory": (
                f"Completed {self.index - 1} of {len(plan)} reference steps "
                "before this proposal."
            ),
            "next_goal": step["intent"],
        }
        return validate_proposal(proposal, packet)


class CommandPlanner:
    """Invoke an arbitrary local model wrapper through JSON stdin and stdout."""

    def __init__(self, command: str | list[str], *, timeout_seconds: float = 300.0):
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise PlaywrightComputerError("planner command cannot be empty")
        self.timeout_seconds = timeout_seconds

    def propose(self, packet: dict[str, Any]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                self.command,
                input=canonical(packet),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PlaywrightComputerError(f"planner command failed to execute: {exc}") from exc
        if result.returncode:
            raise PlaywrightComputerError(
                f"planner command exited {result.returncode}: "
                + result.stderr.decode("utf-8", errors="replace")[-4000:]
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PlaywrightComputerError(
                "planner command returned invalid JSON: "
                + result.stdout.decode("utf-8", errors="replace")[-4000:]
            ) from exc
        return validate_proposal(value, packet)


class FileExchangePlanner:
    """Content-addressed planner handoff for an <dual-3090-node> or another worker host."""

    def __init__(
        self,
        exchange_root: Path,
        *,
        role: str = "planner",
        timeout_seconds: float = 1800.0,
        poll_seconds: float = 0.5,
    ):
        self.exchange_root = exchange_root.resolve()
        self.role = role
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def propose(self, packet: dict[str, Any]) -> dict[str, Any]:
        run_id = packet["run_id"]
        step = int(packet["step_number"])
        stem = f"{step:04d}-{packet['packet_sha256'][:16]}"
        request = self.exchange_root / run_id / self.role / "requests" / f"{stem}.json"
        response = self.exchange_root / run_id / self.role / "responses" / f"{stem}.json"
        atomic_json(request, packet)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() <= deadline:
            if response.exists():
                return validate_proposal(load_json(response), packet)
            time.sleep(self.poll_seconds)
        raise PlaywrightComputerError(
            f"timed out waiting for {self.role} response {response}"
        )
