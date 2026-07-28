"""Deterministic semantic-action reduction and projection."""

from __future__ import annotations

import copy
from typing import Any

from .canonical import sha256_hex, stable_id
from .errors import AuthorityRefused, ScenarioError
from .model import RouteSpec, SemanticAction


def pointer_tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/") or pointer == "/":
        raise ScenarioError(f"invalid non-root JSON pointer: {pointer!r}")
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]


def get_pointer(document: Any, pointer: str) -> Any:
    current = document
    for token in pointer_tokens(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise ScenarioError(f"state path does not exist: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise ScenarioError(f"list path token is not an integer: {token!r}") from exc
            if index < 0 or index >= len(current):
                raise ScenarioError(f"list path index is out of range: {pointer}")
            current = current[index]
        else:
            raise ScenarioError(f"state path traverses a scalar: {pointer}")
    return current


def _parent(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = pointer_tokens(pointer)
    current = document
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                current[token] = {}
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise ScenarioError(f"list path token is not an integer: {token!r}") from exc
            if index < 0 or index >= len(current):
                raise ScenarioError(f"list path index is out of range: {pointer}")
            current = current[index]
        else:
            raise ScenarioError(f"state path traverses a scalar: {pointer}")
    return current, tokens[-1]


def set_pointer(document: Any, pointer: str, value: Any) -> None:
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        parent[token] = value
        return
    if isinstance(parent, list):
        try:
            index = int(token)
        except ValueError as exc:
            raise ScenarioError(f"list path token is not an integer: {token!r}") from exc
        if index < 0 or index >= len(parent):
            raise ScenarioError(f"list path index is out of range: {pointer}")
        parent[index] = value
        return
    raise ScenarioError(f"cannot set state path below scalar: {pointer}")


def _ownership_record(state: dict[str, Any], subject: str) -> dict[str, Any]:
    ownership = state.get("_ownership")
    if not isinstance(ownership, dict):
        raise AuthorityRefused("ownership_table_missing", {"subject": subject})
    record = ownership.get(subject)
    if not isinstance(record, dict):
        raise AuthorityRefused("ownership_record_missing", {"subject": subject})
    return record


def validate_authority(
    state: dict[str, Any],
    action: SemanticAction,
    route: RouteSpec,
    *,
    epoch_override: int | None = None,
) -> None:
    record = _ownership_record(state, action.subject)
    expected_actor = record.get("actor")
    expected_role = record.get("role")
    expected_mandate = record.get("mandate")
    expected_epoch = record.get("epoch")

    claim_epoch = action.authority.ownership_epoch if epoch_override is None else epoch_override

    if action.authority.actor != expected_actor:
        raise AuthorityRefused(
            "actor_not_owner",
            {"expected": expected_actor, "received": action.authority.actor},
        )
    if action.authority.role != expected_role or action.required_role != expected_role:
        raise AuthorityRefused(
            "role_not_authorized",
            {"expected": expected_role, "received": action.authority.role},
        )
    if action.authority.mandate != expected_mandate or action.required_mandate != expected_mandate:
        raise AuthorityRefused(
            "mandate_not_authorized",
            {"expected": expected_mandate, "received": action.authority.mandate},
        )
    if claim_epoch != expected_epoch:
        raise AuthorityRefused(
            "ownership_epoch_stale",
            {"expected": expected_epoch, "received": claim_epoch},
        )
    if route.required_role != expected_role or route.required_mandate != expected_mandate:
        raise AuthorityRefused(
            "route_authority_mismatch",
            {
                "route_role": route.required_role,
                "route_mandate": route.required_mandate,
                "expected_role": expected_role,
                "expected_mandate": expected_mandate,
            },
        )


def semantic_event(
    *,
    run_id: str,
    sequence: int,
    route_id: str,
    action: SemanticAction,
    state_before_hash: str,
) -> dict[str, Any]:
    payload = {
        "format": "axm-semantic-event/1",
        "run_id": run_id,
        "sequence": sequence,
        "semantic_id": action.semantic_id,
        "subject": action.subject,
        "operation": action.operation,
        "state_path": action.state_path,
        "value": action.value,
        "authority": {
            "actor": action.authority.actor,
            "role": action.authority.role,
            "mandate": action.authority.mandate,
            "ownership_epoch": action.authority.ownership_epoch,
        },
        "route_id": route_id,
        "state_before_hash": state_before_hash,
    }
    identity_basis = {
        "format": payload["format"],
        "run_id": run_id,
        "sequence": sequence,
        "semantic_id": action.semantic_id,
        "subject": action.subject,
        "operation": action.operation,
        "state_path": action.state_path,
        "value": action.value,
        "authority": payload["authority"],
        "route_id": route_id,
    }
    payload["event_id"] = stable_id("event1", identity_basis, 32)
    return payload


def reduce_action(state: dict[str, Any], action: SemanticAction) -> tuple[dict[str, Any], Any, Any]:
    next_state = copy.deepcopy(state)
    before = get_pointer(next_state, action.state_path)

    if action.operation == "set":
        after = copy.deepcopy(action.value)
        set_pointer(next_state, action.state_path, after)
    elif action.operation == "increment":
        if isinstance(before, bool) or not isinstance(before, (int, float)):
            raise ScenarioError(f"increment requires a numeric value at {action.state_path}")
        if isinstance(action.value, bool) or not isinstance(action.value, (int, float)):
            raise ScenarioError(f"increment value must be numeric for {action.step_id}")
        after = before + action.value
        set_pointer(next_state, action.state_path, after)
    elif action.operation == "append":
        if not isinstance(before, list):
            raise ScenarioError(f"append requires a list at {action.state_path}")
        after_list = copy.deepcopy(before)
        after_list.append(copy.deepcopy(action.value))
        after = after_list
        set_pointer(next_state, action.state_path, after_list)
    elif action.operation == "remove":
        if isinstance(before, list):
            after_list = copy.deepcopy(before)
            try:
                after_list.remove(action.value)
            except ValueError as exc:
                raise ScenarioError(f"remove value is absent at {action.state_path}") from exc
            after = after_list
            set_pointer(next_state, action.state_path, after_list)
        elif isinstance(before, dict):
            key = action.value
            if not isinstance(key, str) or key not in before:
                raise ScenarioError(f"remove requires an existing object key at {action.state_path}")
            after_map = copy.deepcopy(before)
            del after_map[key]
            after = after_map
            set_pointer(next_state, action.state_path, after_map)
        else:
            raise ScenarioError(f"remove requires a list or object at {action.state_path}")
    elif action.operation == "toggle":
        if not isinstance(before, bool):
            raise ScenarioError(f"toggle requires a boolean at {action.state_path}")
        after = not before
        set_pointer(next_state, action.state_path, after)
    else:  # defensive, parser already rejects this
        raise ScenarioError(f"unknown action operation: {action.operation}")

    return next_state, before, after


def desired_output(
    *,
    scenario_id: str,
    action: SemanticAction,
    before: Any,
    after: Any,
) -> dict[str, Any]:
    output = {
        "format": "axm-desired-output/1",
        "scenario_id": scenario_id,
        "semantic_id": action.semantic_id,
        "subject": action.subject,
        "state_path": action.state_path,
        "before": before,
        "after": after,
        "channels": copy.deepcopy(action.projection),
    }
    output["output_id"] = stable_id("output1", output, 32)
    return output


def causal_debrief(
    *,
    scenario_id: str,
    action: SemanticAction,
    before: Any,
    after: Any,
) -> dict[str, Any]:
    debrief = {
        "format": "axm-causal-debrief/1",
        "scenario_id": scenario_id,
        "cause": action.semantic_id,
        "subject": action.subject,
        "state_path": action.state_path,
        "operation": action.operation,
        "before": before,
        "after": after,
        "changed": before != after,
        "control_question": action.expected.get(
            "control_question",
            "Did the declared semantic action produce the expected state transition?",
        ),
    }
    debrief["debrief_id"] = stable_id("debrief1", debrief, 32)
    return debrief


def verify_projection(output: dict[str, Any], expected_hash: str) -> None:
    actual = sha256_hex(output)
    if actual != expected_hash:
        from .errors import ProjectionMismatch

        raise ProjectionMismatch(f"projection hash mismatch: expected {expected_hash}, got {actual}")
