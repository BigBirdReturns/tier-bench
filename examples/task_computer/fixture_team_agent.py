#!/usr/bin/env python3
"""Deterministic stdin/stdout team adapter for Task Computer fixture flights.

This is a transport and topology smoke, not a model. Replace the decision functions
with a local model wrapper while preserving the same JSON contracts.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

PLANNER_SCHEMA = "tier-bench/task-computer-proposal@1"
CRITIC_SCHEMA = "tier-bench/task-computer-critic-response@1"


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))


def ids(state: dict[str, Any]) -> set[str]:
    return {
        str(element.get("attributes", {}).get("id"))
        for element in state.get("elements", [])
        if element.get("attributes", {}).get("id")
    }


def history_ids(packet: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for row in packet.get("recent_history", []):
        for action in row.get("actions", []):
            intent = str(action.get("intent", ""))
            result.add(intent)
    return result


def action(
    identifier: str,
    *,
    surface: str,
    op: str,
    effect: str,
    intent: str,
    target: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "surface": surface,
        "op": op,
        "effect": effect,
        "intent": intent,
        "target": target,
        "args": args or {},
    }


def planner(packet: dict[str, Any]) -> dict[str, Any]:
    scenario = packet["scenario_id"]
    state = packet["state"]
    available = ids(state)
    title = str(state.get("title", ""))
    visible = str(state.get("elements_text", ""))
    prior = history_ids(packet)
    selected: dict[str, Any] | None = None

    if scenario == "tier-desk-approve-underdrain":
        if "task-underdrain" in available:
            selected = action(
                "open-underdrain",
                surface="playwright",
                op="click",
                effect="read",
                intent="Open the Underdrain authored-pilot task from the queue.",
                target={"id": "task-underdrain"},
            )
        elif "acceptance-tab" in available and "arm-task" not in available:
            selected = action(
                "review-acceptance",
                surface="playwright",
                op="click",
                effect="read",
                intent="Read and acknowledge the player-facing acceptance contract.",
                target={"id": "acceptance-tab"},
            )
        elif "arm-task" in available:
            selected = action(
                "arm-underdrain",
                surface="playwright",
                op="click",
                effect="local_write",
                intent="Arm the reviewed Underdrain task for the governed queue.",
                target={"id": "arm-task"},
            )
        elif "transition receipt" not in title.casefold():
            selected = action(
                "wait-tier-desk",
                surface="playwright",
                op="wait",
                effect="read",
                intent="Wait for the governed task surface to settle.",
                args={"seconds": 0.5},
            )
    elif scenario == "axm-chat-pull-latest":
        sequence = [
            (
                "open-shared-chat",
                "read",
                "Open the shared Manus Playwright conversation.",
            ),
            (
                "pull-latest",
                "read",
                "Retrieve the latest remote turn boundary and compute the delta.",
            ),
            (
                "import-turns",
                "local_write",
                "Import only the three new turns into the local conversation estate.",
            ),
            (
                "seal-shard",
                "local_write",
                "Seal the refreshed local conversation shard at turn 45.",
            ),
            (
                "download-sync-receipt",
                "read",
                "Download the browser-sync receipt into the task computer.",
            ),
        ]
        for element_id, effect, intent in sequence:
            if element_id in available:
                if element_id == "download-sync-receipt" and intent in prior:
                    break
                selected = action(
                    element_id,
                    surface="playwright",
                    op="click",
                    effect=effect,
                    intent=intent,
                    target={"id": element_id},
                )
                break
    elif scenario == "screen-ghost-visual-fallback":
        if "Synchronized" not in visible:
            selected = action(
                "tap-visual-sync",
                surface="screen_ghost",
                op="tap",
                effect="local_write",
                intent=(
                    "Tap the visual SYNC NOW control that is absent from the semantic "
                    "DOM action map."
                ),
                target={"visual_id": "sync-now"},
            )
    elif scenario == "axm-world-underdrain-playtest":
        sequence = [
            (
                "start-pilot",
                "interactive",
                "Enter the Main Street drain call as the town plumber.",
            ),
            (
                "snake-drain",
                "local_write",
                "Use the drain snake on the measured obstruction eighteen feet into the line.",
            ),
            (
                "inspect-fungus",
                "local_write",
                "Bag the exposed fungal sample and record its location and consequence.",
            ),
            (
                "report-back",
                "local_write",
                "Report the finding and unlock the municipal-underworks continuation.",
            ),
        ]
        for element_id, effect, intent in sequence:
            if element_id in available:
                selected = action(
                    element_id,
                    surface="playwright",
                    op="click",
                    effect=effect,
                    intent=intent,
                    target={"id": element_id},
                )
                break

    done = selected is None
    emit_value = {
        "schema": PLANNER_SCHEMA,
        "packet_sha256": packet["packet_sha256"],
        "state_id": state["state_id"],
        "actions": [selected] if selected else [],
        "done": done,
        "memory": (
            "Fixture team adapter selected one state-bound action."
            if selected
            else "Fixture task appears complete; return it for hidden acceptance."
        ),
        "next_goal": selected["intent"] if selected else "Run external acceptance.",
    }
    emit(emit_value)
    return emit_value


def critic(request: dict[str, Any]) -> dict[str, Any]:
    proposal = request["proposal"]
    errors: list[str] = []
    warnings: list[str] = []
    if proposal.get("packet_sha256") != request.get("packet_sha256"):
        errors.append("proposal belongs to another packet")
    if proposal.get("state_id") != request.get("state", {}).get("state_id"):
        errors.append("proposal is stale")
    maximum = int(request.get("effect_policy", {}).get("max_actions_per_proposal", 1))
    actions = proposal.get("actions", [])
    if len(actions) > maximum:
        errors.append("proposal exceeds the scenario action limit")
    available = ids(request.get("state", {}))
    for candidate in actions:
        if candidate.get("surface") == "playwright" and candidate.get("target", {}).get("id"):
            if candidate["target"]["id"] not in available:
                errors.append(
                    f"target id {candidate['target']['id']!r} is absent from current state"
                )
        if candidate.get("surface") == "screen_ghost":
            warnings.append("visual action requires changed-state verification")
    response = {
        "schema": CRITIC_SCHEMA,
        "request_sha256": request["request_sha256"],
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "rationale": (
            "Proposal is bound to the current state and uses available project surfaces."
            if not errors
            else "Proposal violated one or more state or surface constraints."
        ),
        "model": "deterministic-fixture-team-adapter",
        "seat": os.environ.get("TIER_TASK_SEAT_ID"),
    }
    emit(response)
    return response


def main() -> int:
    try:
        value = json.load(sys.stdin)
        role = os.environ.get("TIER_TASK_ROLE")
        if role == "planner":
            planner(value)
        elif role == "critic":
            critic(value)
        else:
            raise RuntimeError("TIER_TASK_ROLE must be planner or critic")
        return 0
    except Exception as exc:
        print(f"fixture_team_agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
