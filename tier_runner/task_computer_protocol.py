"""Project-native Work IR, planner packets, proposals, and critic verdicts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .playwright_computer_common import (
    PlaywrightComputerError,
    hash_json,
    safe_id,
    without_hash,
)

CATALOG_SCHEMA = "tier-bench/task-computer-catalog@1"
SCENARIO_SCHEMA = "tier-bench/task-computer-scenario@1"
PLANNER_PACKET_SCHEMA = "tier-bench/task-computer-planner-packet@1"
PROPOSAL_SCHEMA = "tier-bench/task-computer-proposal@1"
VERDICT_SCHEMA = "tier-bench/task-computer-critic-verdict@1"
STEP_RECEIPT_SCHEMA = "tier-bench/task-computer-step-receipt@1"
RUN_RECEIPT_SCHEMA = "tier-bench/task-computer-run-receipt@1"
SCREEN_GHOST_REQUEST_SCHEMA = "tier-bench/screen-ghost-request@1"

SURFACES = {"playwright", "screen_ghost", "workspace", "human"}
EFFECTS = {"read", "interactive", "local_write", "external_write", "sensitive", "privileged"}
SURFACE_OPS = {
    "playwright": {
        "observe",
        "navigate",
        "back",
        "open_tab",
        "switch_tab",
        "close_tab",
        "click",
        "fill",
        "type",
        "press",
        "select",
        "scroll",
        "wait",
        "extract",
        "screenshot",
        "upload",
        "done",
    },
    "screen_ghost": {"observe", "tap", "swipe", "type", "done"},
    "workspace": {"assert_file", "hash_file", "copy_file", "write_manifest", "done"},
    "human": {"takeover", "release", "done"},
}
PLAYWRIGHT_TARGET_OPS = {"click", "fill", "type", "press", "select", "upload"}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlaywrightComputerError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise PlaywrightComputerError(f"{label} must be an array{suffix}")
    return value


def _text(value: Any, label: str, *, limit: int = 4000, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise PlaywrightComputerError(
            f"{label} must be {'a' if allow_empty else 'a non-empty'} string of at most {limit} characters"
        )
    return value if allow_empty else value.strip()


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PlaywrightComputerError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PlaywrightComputerError(f"{label} must be an integer between {low} and {high}")
    return value


def _surface_list(value: Any, label: str) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_array(value, label, nonempty=True)):
        surface = _text(raw, f"{label}[{index}]", limit=40)
        if surface not in SURFACES:
            raise PlaywrightComputerError(f"{label}[{index}] must be one of {sorted(SURFACES)}")
        if surface not in result:
            result.append(surface)
    return result


def _effect_list(value: Any, label: str) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_array(value, label)):
        effect = _text(raw, f"{label}[{index}]", limit=40)
        if effect not in EFFECTS:
            raise PlaywrightComputerError(f"{label}[{index}] must be one of {sorted(EFFECTS)}")
        if effect not in result:
            result.append(effect)
    return sorted(result)


def _matcher(value: Any, label: str) -> dict[str, Any]:
    row = _object(value, label)
    allowed = {
        "id",
        "testid",
        "name",
        "name_contains",
        "text_contains",
        "role",
        "tag",
        "attribute",
        "visual_id",
    }
    unknown = set(row) - allowed
    if unknown:
        raise PlaywrightComputerError(f"{label} has unknown fields: {sorted(unknown)}")
    result: dict[str, Any] = {}
    for key in ("id", "testid", "name", "name_contains", "text_contains", "role", "tag", "visual_id"):
        if key in row:
            result[key] = _text(row[key], f"{label}.{key}", limit=1000)
    if "attribute" in row:
        attribute = _object(row["attribute"], f"{label}.attribute")
        if len(attribute) != 1:
            raise PlaywrightComputerError(f"{label}.attribute must contain exactly one name/value pair")
        key, raw = next(iter(attribute.items()))
        result["attribute"] = {
            _text(key, f"{label}.attribute key", limit=120): _text(
                raw, f"{label}.attribute value", limit=1000, allow_empty=True
            )
        }
    if not result:
        raise PlaywrightComputerError(f"{label} must contain at least one matcher field")
    return result


def _reference_step(value: Any, index: int, scenario_id: str) -> dict[str, Any]:
    label = f"scenario {scenario_id}.reference_plan[{index}]"
    row = _object(value, label)
    surface = _text(row.get("surface"), f"{label}.surface", limit=40)
    if surface not in SURFACES:
        raise PlaywrightComputerError(f"{label}.surface must be one of {sorted(SURFACES)}")
    op = _text(row.get("op"), f"{label}.op", limit=40)
    if op not in SURFACE_OPS[surface]:
        raise PlaywrightComputerError(
            f"{label}.op must be one of {sorted(SURFACE_OPS[surface])} for {surface}"
        )
    effect = _text(row.get("effect", "read"), f"{label}.effect", limit=40)
    if effect not in EFFECTS:
        raise PlaywrightComputerError(f"{label}.effect must be one of {sorted(EFFECTS)}")
    target = row.get("target")
    if target is not None:
        target = _matcher(target, f"{label}.target")
    if surface == "playwright" and op in PLAYWRIGHT_TARGET_OPS and target is None:
        raise PlaywrightComputerError(f"{label} requires a target matcher")
    if surface == "screen_ghost" and op in {"tap", "swipe", "type"} and target is None:
        args = _object(row.get("args", {}), f"{label}.args")
        if "x" not in args or "y" not in args:
            raise PlaywrightComputerError(
                f"{label} requires target.visual_id or explicit args.x and args.y"
            )
    return {
        "id": safe_id(row.get("id", f"step-{index + 1:03d}"), f"{label}.id"),
        "surface": surface,
        "op": op,
        "effect": effect,
        "intent": _text(row.get("intent", op), f"{label}.intent", limit=2000),
        "target": target,
        "args": deepcopy(_object(row.get("args", {}), f"{label}.args")),
        "retry_seconds": float(row.get("retry_seconds", 3.0)),
    }


def validate_scenario(value: Any, index: int = 0) -> dict[str, Any]:
    row = _object(value, f"catalog.scenarios[{index}]")
    if row.get("schema", SCENARIO_SCHEMA) != SCENARIO_SCHEMA:
        raise PlaywrightComputerError(
            f"catalog.scenarios[{index}].schema must be {SCENARIO_SCHEMA}"
        )
    scenario_id = safe_id(row.get("id"), f"catalog.scenarios[{index}].id")
    surfaces = _surface_list(
        row.get("surface_order", ["playwright", "screen_ghost", "human"]),
        f"scenario {scenario_id}.surface_order",
    )
    variants = [
        safe_id(raw, f"scenario {scenario_id}.variants[{variant_index}]")
        for variant_index, raw in enumerate(
            _array(row.get("variants", ["base"]), f"scenario {scenario_id}.variants", nonempty=True)
        )
    ]
    if len(variants) != len(set(variants)):
        raise PlaywrightComputerError(f"scenario {scenario_id}.variants must be unique")
    policy = _object(row.get("policy", {}), f"scenario {scenario_id}.policy")
    approval_effects = _effect_list(
        policy.get("approval_effects", ["external_write", "sensitive", "privileged"]),
        f"scenario {scenario_id}.policy.approval_effects",
    )
    preauthorized_effects = _effect_list(
        policy.get("preauthorized_effects", ["read", "interactive"]),
        f"scenario {scenario_id}.policy.preauthorized_effects",
    )
    overlap = set(approval_effects) & set(preauthorized_effects)
    if overlap:
        raise PlaywrightComputerError(
            f"scenario {scenario_id} effects cannot be both preauthorized and approval-governed: {sorted(overlap)}"
        )
    reference_plan = [
        _reference_step(step, step_index, scenario_id)
        for step_index, step in enumerate(
            _array(row.get("reference_plan"), f"scenario {scenario_id}.reference_plan", nonempty=True)
        )
    ]
    step_ids = [step["id"] for step in reference_plan]
    if len(step_ids) != len(set(step_ids)):
        raise PlaywrightComputerError(f"scenario {scenario_id}.reference_plan step ids must be unique")
    acceptance = []
    for acceptance_index, raw in enumerate(
        _array(row.get("acceptance"), f"scenario {scenario_id}.acceptance", nonempty=True)
    ):
        item = _object(raw, f"scenario {scenario_id}.acceptance[{acceptance_index}]")
        acceptance.append(
            {
                "id": safe_id(
                    item.get("id", f"acceptance-{acceptance_index + 1:03d}"),
                    f"scenario {scenario_id}.acceptance[{acceptance_index}].id",
                ),
                "description": _text(
                    item.get("description"),
                    f"scenario {scenario_id}.acceptance[{acceptance_index}].description",
                    limit=2000,
                ),
            }
        )
    cold = _object(row.get("cold_operator", {}), f"scenario {scenario_id}.cold_operator")
    required_cold = ("identity", "problem", "choice", "changed", "record", "next")
    cold_operator = {
        key: _text(cold.get(key), f"scenario {scenario_id}.cold_operator.{key}", limit=2000)
        for key in required_cold
    }
    handoff = _object(row.get("handoff", {}), f"scenario {scenario_id}.handoff")
    result = {
        "schema": SCENARIO_SCHEMA,
        "id": scenario_id,
        "project": safe_id(row.get("project"), f"scenario {scenario_id}.project"),
        "title": _text(row.get("title", scenario_id), f"scenario {scenario_id}.title", limit=300),
        "goal": _text(row.get("goal"), f"scenario {scenario_id}.goal", limit=8000),
        "surface_order": surfaces,
        "variants": variants,
        "max_steps": _integer(row.get("max_steps", max(10, len(reference_plan) + 3)), f"scenario {scenario_id}.max_steps", low=1, high=500),
        "policy": {
            "approval_effects": approval_effects,
            "preauthorized_effects": preauthorized_effects,
            "max_actions_per_proposal": _integer(
                policy.get("max_actions_per_proposal", 3),
                f"scenario {scenario_id}.policy.max_actions_per_proposal",
                low=1,
                high=20,
            ),
        },
        "acceptance": acceptance,
        "cold_operator": cold_operator,
        "handoff": deepcopy(handoff),
        "reference_plan": reference_plan,
    }
    governed = set(result["policy"]["approval_effects"]) | set(
        result["policy"]["preauthorized_effects"]
    )
    used = {step["effect"] for step in reference_plan}
    unknown = used - governed
    if unknown:
        raise PlaywrightComputerError(
            f"scenario {scenario_id} uses effects that policy neither preauthorizes nor approval-governs: {sorted(unknown)}"
        )
    return result


def validate_catalog(value: Any) -> dict[str, Any]:
    row = _object(value, "catalog")
    if row.get("schema") != CATALOG_SCHEMA:
        raise PlaywrightComputerError(f"catalog.schema must be {CATALOG_SCHEMA}")
    scenarios = [
        validate_scenario(raw, index)
        for index, raw in enumerate(_array(row.get("scenarios"), "catalog.scenarios", nonempty=True))
    ]
    identifiers = [scenario["id"] for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise PlaywrightComputerError("catalog scenario ids must be unique")
    return {
        "schema": CATALOG_SCHEMA,
        "id": safe_id(row.get("id"), "catalog.id"),
        "title": _text(row.get("title", row.get("id")), "catalog.title", limit=300),
        "scenarios": scenarios,
    }


def scenario_by_id(catalog: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    matches = [scenario for scenario in catalog["scenarios"] if scenario["id"] == scenario_id]
    if len(matches) != 1:
        raise PlaywrightComputerError(f"catalog has no unique scenario {scenario_id!r}")
    return matches[0]


def compile_planner_packet(
    *,
    run_id: str,
    scenario: dict[str, Any],
    variant: str,
    state: dict[str, Any],
    step_number: int,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema": PLANNER_PACKET_SCHEMA,
        "run_id": safe_id(run_id, "run_id"),
        "scenario_id": scenario["id"],
        "project": scenario["project"],
        "variant": safe_id(variant, "variant"),
        "step_number": step_number,
        "max_steps": scenario["max_steps"],
        "goal": scenario["goal"],
        "acceptance": scenario["acceptance"],
        "cold_operator_questions": {
            "identity": "Who am I in this workflow?",
            "problem": "What problem am I solving?",
            "choice": "What did I choose or do?",
            "changed": "What changed because of that action?",
            "record": "What evidence was recorded?",
            "next": "What happens next?",
        },
        "surface_order": scenario["surface_order"],
        "allowed_ops": {
            surface: sorted(SURFACE_OPS[surface]) for surface in scenario["surface_order"]
        },
        "effect_policy": scenario["policy"],
        "state": {
            "state_id": state["state_id"],
            "page_id": state["page_id"],
            "url": state["url"],
            "title": state["title"],
            "tabs": state["tabs"],
            "elements": state["elements"],
            "elements_text": state["elements_text"],
            "scroll": state["scroll"],
            "artifacts": state["artifacts"],
        },
        "recent_history": history[-5:],
        "response_contract": {
            "schema": PROPOSAL_SCHEMA,
            "required": ["packet_sha256", "state_id", "actions", "done", "memory", "next_goal"],
            "action_fields": ["surface", "op", "effect", "intent", "target", "args"],
        },
    }
    packet["packet_sha256"] = hash_json(packet)
    return packet


def validate_proposal(value: Any, packet: dict[str, Any]) -> dict[str, Any]:
    row = _object(value, "proposal")
    if row.get("schema", PROPOSAL_SCHEMA) != PROPOSAL_SCHEMA:
        raise PlaywrightComputerError(f"proposal.schema must be {PROPOSAL_SCHEMA}")
    if row.get("packet_sha256") != packet["packet_sha256"]:
        raise PlaywrightComputerError("proposal.packet_sha256 does not match the planner packet")
    if row.get("state_id") != packet["state"]["state_id"]:
        raise PlaywrightComputerError("proposal.state_id does not match the planner packet state")
    actions = []
    for index, raw in enumerate(_array(row.get("actions", []), "proposal.actions")):
        label = f"proposal.actions[{index}]"
        action = _object(raw, label)
        surface = _text(action.get("surface"), f"{label}.surface", limit=40)
        if surface not in SURFACES:
            raise PlaywrightComputerError(f"{label}.surface must be one of {sorted(SURFACES)}")
        op = _text(action.get("op"), f"{label}.op", limit=40)
        effect = _text(action.get("effect", "read"), f"{label}.effect", limit=40)
        if effect not in EFFECTS:
            raise PlaywrightComputerError(f"{label}.effect must be one of {sorted(EFFECTS)}")
        target = action.get("target")
        if target is not None:
            target = _matcher(target, f"{label}.target")
        actions.append(
            {
                "id": safe_id(action.get("id", f"proposal-action-{index + 1:03d}"), f"{label}.id"),
                "surface": surface,
                "op": op,
                "effect": effect,
                "intent": _text(action.get("intent", op), f"{label}.intent", limit=2000),
                "target": target,
                "args": deepcopy(_object(action.get("args", {}), f"{label}.args")),
            }
        )
    done = _boolean(row.get("done", False), "proposal.done")
    if not actions and not done:
        raise PlaywrightComputerError("proposal must contain actions or declare done")
    normalized = {
        "schema": PROPOSAL_SCHEMA,
        "packet_sha256": packet["packet_sha256"],
        "state_id": packet["state"]["state_id"],
        "actions": actions,
        "done": done,
        "memory": _text(row.get("memory", ""), "proposal.memory", limit=8000, allow_empty=True),
        "next_goal": _text(row.get("next_goal", ""), "proposal.next_goal", limit=2000, allow_empty=True),
    }
    normalized["proposal_sha256"] = hash_json(normalized)
    return normalized


def _contains(haystack: Any, needle: str) -> bool:
    return needle.casefold() in str(haystack or "").casefold()


def element_matches(element: dict[str, Any], matcher: dict[str, Any]) -> bool:
    attributes = element.get("attributes", {})
    if "id" in matcher and attributes.get("id") != matcher["id"]:
        return False
    if "testid" in matcher:
        values = [attributes.get(key) for key in ("data-testid", "data-test", "data-qa", "data-cy")]
        if matcher["testid"] not in values:
            return False
    if "name" in matcher and str(element.get("name") or "").casefold() != matcher["name"].casefold():
        return False
    if "name_contains" in matcher and not _contains(element.get("name"), matcher["name_contains"]):
        return False
    if "text_contains" in matcher and not _contains(element.get("text"), matcher["text_contains"]):
        return False
    if "role" in matcher and str(element.get("role") or "").casefold() != matcher["role"].casefold():
        return False
    if "tag" in matcher and str(element.get("tag") or "").casefold() != matcher["tag"].casefold():
        return False
    if "attribute" in matcher:
        key, expected = next(iter(matcher["attribute"].items()))
        if str(attributes.get(key, "")) != expected:
            return False
    return True


def resolve_element(state: dict[str, Any], matcher: dict[str, Any]) -> dict[str, Any]:
    if "visual_id" in matcher:
        raise PlaywrightComputerError("visual targets are resolved by the ScreenGhost adapter")
    matches = [element for element in state.get("elements", []) if element_matches(element, matcher)]
    if len(matches) != 1:
        raise PlaywrightComputerError(
            f"target matcher resolved {len(matches)} elements; expected exactly one: {matcher}"
        )
    return matches[0]


def critic_verdict(
    *,
    scenario: dict[str, Any],
    packet: dict[str, Any],
    proposal: dict[str, Any],
    approval_available: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if proposal["packet_sha256"] != packet["packet_sha256"]:
        errors.append("proposal belongs to another planner packet")
    if proposal["state_id"] != packet["state"]["state_id"]:
        errors.append("proposal is stale")
    if len(proposal["actions"]) > scenario["policy"]["max_actions_per_proposal"]:
        errors.append("proposal exceeds max_actions_per_proposal")
    for action in proposal["actions"]:
        surface = action["surface"]
        op = action["op"]
        effect = action["effect"]
        if surface not in scenario["surface_order"]:
            errors.append(f"surface {surface!r} is outside the scenario surface order")
            continue
        if op not in SURFACE_OPS[surface]:
            errors.append(f"operation {op!r} is not valid for surface {surface!r}")
        if effect in scenario["policy"]["approval_effects"] and not approval_available:
            errors.append(f"effect {effect!r} requires an approval token")
        if effect not in scenario["policy"]["approval_effects"] and effect not in scenario["policy"]["preauthorized_effects"]:
            errors.append(f"effect {effect!r} is not governed by the scenario policy")
        if surface == "playwright" and op in PLAYWRIGHT_TARGET_OPS:
            if action["target"] is None:
                errors.append(f"playwright operation {op!r} requires a semantic target")
            else:
                try:
                    resolve_element(packet["state"], action["target"])
                except PlaywrightComputerError as exc:
                    errors.append(str(exc))
        if surface == "screen_ghost" and op in {"tap", "swipe", "type"}:
            has_visual_target = bool(action["target"] and action["target"].get("visual_id"))
            has_coordinates = "x" in action["args"] and "y" in action["args"]
            if not has_visual_target and not has_coordinates:
                errors.append("ScreenGhost action requires target.visual_id or x/y coordinates")
            if effect in {"external_write", "sensitive", "privileged"}:
                warnings.append("visual action crosses a high-risk effect boundary")
    verdict: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "scenario_id": scenario["id"],
        "packet_sha256": packet["packet_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "state_id": packet["state"]["state_id"],
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "authority": "deterministic task-computer rule critic",
    }
    verdict["verdict_sha256"] = hash_json(verdict)
    return verdict


def screen_ghost_request(
    *,
    scenario: dict[str, Any],
    packet: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema": SCREEN_GHOST_REQUEST_SCHEMA,
        "scenario_id": scenario["id"],
        "project": scenario["project"],
        "packet_sha256": packet["packet_sha256"],
        "state_id": packet["state"]["state_id"],
        "goal": scenario["goal"],
        "intent": action["intent"],
        "effect": action["effect"],
        "target": action["target"],
        "screenshot": packet["state"]["artifacts"]["clean_screenshot"],
        "marked_screenshot": packet["state"]["artifacts"]["marked_screenshot"],
        "viewport": packet["state"]["scroll"],
        "candidate_contract": {
            "required": ["state_id", "x", "y", "confidence", "description"],
            "coordinate_space": "current viewport pixels or normalized 0..1 coordinates",
            "failure": "unsupported_surface",
        },
    }
    request["request_sha256"] = hash_json(request)
    return request


def verify_hashed_record(value: dict[str, Any], field: str) -> bool:
    observed = value.get(field)
    return isinstance(observed, str) and observed == hash_json(without_hash(value, field))
