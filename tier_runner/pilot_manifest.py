from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from .manifest import COST_BASES, ManifestError


SCHEMA = "tier-bench/pilot-backends@2"
ARMS = ("arm_a", "arm_b", "arm_c")
MODES = {
    "arm_a": "frontier_driver",
    "arm_b": "cheap_driver",
    "arm_c": "operator_routed",
}
PLACEHOLDERS = {
    "{arm}",
    "{call_receipt}",
    "{dispatch_receipt}",
    "{prompt}",
    "{result}",
    "{stage}",
    "{task_id}",
    "{worktree}",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be an object")
    return value


def _keys(value: dict[str, Any], required: set[str], optional: set[str], label: str) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise ManifestError(
            f"{label} fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ManifestError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    path: Path
    raw: bytes
    sha256: str


@dataclass(frozen=True)
class PilotBackend:
    name: str
    model_id: str
    effort: str
    surface: str
    cost_basis: str
    account: str
    tier: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Stage:
    backend: str
    prompt_template: str


@dataclass(frozen=True)
class Repair(Stage):
    max_calls: int


@dataclass(frozen=True)
class QuestionRoute:
    question_template: str
    resume_prompt_template: str
    max_questions: int


@dataclass(frozen=True)
class PilotArm:
    name: str
    mode: str
    hands: Stage
    repair: Repair
    escalations: tuple[Stage, ...]
    driver: Stage | None = None
    question_route: QuestionRoute | None = None
    driver_trace_path: str | None = None


@dataclass(frozen=True)
class PilotComposition:
    path: Path
    sha256: str
    protocol_commit: str
    isolation: dict[str, Any]
    tool_versions: dict[str, str]
    templates: dict[str, PromptTemplate]
    backends: dict[str, PilotBackend]
    arms: dict[str, PilotArm]


def _command(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ManifestError(f"{label} must be a non-empty argv string array")
    joined = "\n".join(value)
    unknown = set(re.findall(r"\{[^{}]+\}", joined)) - PLACEHOLDERS
    if unknown:
        raise ManifestError(f"{label} has unknown placeholders: {sorted(unknown)}")
    required = {"{dispatch_receipt}", "{prompt}", "{result}", "{worktree}"}
    missing = required - {marker for marker in required if marker in joined}
    if missing:
        raise ManifestError(f"{label} is missing placeholders: {sorted(missing)}")
    return tuple(value)


def _stage(
    value: Any,
    label: str,
    backends: dict[str, PilotBackend],
    templates: dict[str, PromptTemplate],
) -> Stage:
    obj = _object(value, label)
    _keys(obj, {"backend", "prompt_template"}, set(), label)
    backend = _string(obj["backend"], f"{label}.backend")
    template = _string(obj["prompt_template"], f"{label}.prompt_template")
    if backend not in backends:
        raise ManifestError(f"{label} names unknown backend {backend!r}")
    if template not in templates:
        raise ManifestError(f"{label} names unknown prompt template {template!r}")
    return Stage(backend, template)


def _repair(
    value: Any,
    label: str,
    backends: dict[str, PilotBackend],
    templates: dict[str, PromptTemplate],
) -> Repair:
    obj = _object(value, label)
    _keys(obj, {"backend", "prompt_template", "max_calls"}, set(), label)
    stage = _stage(
        {"backend": obj["backend"], "prompt_template": obj["prompt_template"]},
        label,
        backends,
        templates,
    )
    max_calls = _positive_int(obj["max_calls"], f"{label}.max_calls")
    if max_calls != 1:
        raise ManifestError(
            f"{label}.max_calls must be 1 in pilot-backends@2; repeated repair semantics "
            "are not preregistered"
        )
    return Repair(stage.backend, stage.prompt_template, max_calls)


def load_pilot_composition(
    path: Path,
    read_bytes: Callable[[Path], bytes] | None = None,
) -> PilotComposition:
    path = path.resolve()
    reader = read_bytes or (lambda item: item.read_bytes())
    raw = reader(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid pilot composition JSON: {exc}") from exc
    data = _object(data, "pilot composition")
    _keys(
        data,
        {
            "schema",
            "protocol_commit",
            "isolation",
            "tool_versions",
            "prompt_templates",
            "backends",
            "arms",
        },
        set(),
        "pilot composition",
    )
    if data["schema"] != SCHEMA:
        raise ManifestError(f"pilot composition schema must be {SCHEMA}")
    protocol_commit = _string(data["protocol_commit"], "protocol_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", protocol_commit):
        raise ManifestError("protocol_commit must be a full lowercase Git SHA")

    isolation = _object(data["isolation"], "isolation")
    required_isolation = {
        "fresh_session_per_call": True,
        "instruction_files": False,
        "auto_memory": False,
        "conversation_carryover": False,
    }
    for key, expected in required_isolation.items():
        if isolation.get(key) is not expected:
            raise ManifestError(f"isolation.{key} must be {expected!r}")

    tool_versions = _object(data["tool_versions"], "tool_versions")
    if not tool_versions or not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
        for key, value in tool_versions.items()
    ):
        raise ManifestError("tool_versions must bind non-empty names to versions")

    templates: dict[str, PromptTemplate] = {}
    for name, value in _object(data["prompt_templates"], "prompt_templates").items():
        name = _string(name, "prompt template name")
        obj = _object(value, f"prompt_templates.{name}")
        _keys(obj, {"path", "sha256"}, set(), f"prompt_templates.{name}")
        relative = Path(_string(obj["path"], f"prompt_templates.{name}.path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ManifestError(f"prompt_templates.{name}.path must stay under the manifest")
        template_path = (path.parent / relative).resolve()
        try:
            template_path.relative_to(path.parent)
        except ValueError as exc:
            raise ManifestError(f"prompt_templates.{name}.path escapes the manifest") from exc
        template_raw = reader(template_path)
        actual = _sha(template_raw)
        declared = _string(obj["sha256"], f"prompt_templates.{name}.sha256")
        if actual != declared:
            raise ManifestError(
                f"prompt_templates.{name} hash mismatch: expected {declared}, got {actual}"
            )
        templates[name] = PromptTemplate(name, template_path, template_raw, actual)
    if not templates:
        raise ManifestError("prompt_templates must not be empty")

    backends: dict[str, PilotBackend] = {}
    for name, value in _object(data["backends"], "backends").items():
        name = _string(name, "backend name")
        obj = _object(value, f"backends.{name}")
        _keys(
            obj,
            {"model_id", "effort", "surface", "cost_basis", "account", "tier", "adapter"},
            set(),
            f"backends.{name}",
        )
        cost_basis = _string(obj["cost_basis"], f"backends.{name}.cost_basis")
        if cost_basis not in COST_BASES:
            raise ManifestError(f"backends.{name}.cost_basis is unsupported: {cost_basis!r}")
        adapter = _object(obj["adapter"], f"backends.{name}.adapter")
        _keys(adapter, {"command"}, set(), f"backends.{name}.adapter")
        backends[name] = PilotBackend(
            name=name,
            model_id=_string(obj["model_id"], f"backends.{name}.model_id"),
            effort=_string(obj["effort"], f"backends.{name}.effort"),
            surface=_string(obj["surface"], f"backends.{name}.surface"),
            cost_basis=cost_basis,
            account=_string(obj["account"], f"backends.{name}.account"),
            tier=_string(obj["tier"], f"backends.{name}.tier"),
            command=_command(adapter["command"], f"backends.{name}.adapter.command"),
        )
    if not backends:
        raise ManifestError("backends must not be empty")

    arm_values = _object(data["arms"], "arms")
    if set(arm_values) != set(ARMS):
        raise ManifestError(f"arms must contain exactly {list(ARMS)}")
    arms: dict[str, PilotArm] = {}
    for arm_name in ARMS:
        obj = _object(arm_values[arm_name], f"arms.{arm_name}")
        common = {"mode", "hands", "repair", "escalations"}
        if arm_name in {"arm_a", "arm_b"}:
            required = common | {"driver"}
            if arm_name == "arm_a":
                required.add("driver_trace")
            optional = set()
        else:
            required = common | {"question_route"}
            optional = set()
        _keys(obj, required, optional, f"arms.{arm_name}")
        mode = _string(obj["mode"], f"arms.{arm_name}.mode")
        if mode != MODES[arm_name]:
            raise ManifestError(f"arms.{arm_name}.mode must be {MODES[arm_name]!r}")
        hands = _stage(obj["hands"], f"arms.{arm_name}.hands", backends, templates)
        repair = _repair(obj["repair"], f"arms.{arm_name}.repair", backends, templates)
        escalation_values = obj["escalations"]
        if not isinstance(escalation_values, list):
            raise ManifestError(f"arms.{arm_name}.escalations must be an array")
        escalations = tuple(
            _stage(item, f"arms.{arm_name}.escalations[{index}]", backends, templates)
            for index, item in enumerate(escalation_values)
        )
        driver: Stage | None = None
        question_route: QuestionRoute | None = None
        driver_trace_path: str | None = None
        if arm_name in {"arm_a", "arm_b"}:
            driver = _stage(obj["driver"], f"arms.{arm_name}.driver", backends, templates)
            if repair.backend != driver.backend:
                raise ManifestError(f"arms.{arm_name}.repair must use its frozen driver backend")
            expected_tier = "frontier" if arm_name == "arm_a" else "cheap"
            if backends[driver.backend].tier != expected_tier:
                raise ManifestError(
                    f"arms.{arm_name}.driver backend tier must be {expected_tier!r}"
                )
            if arm_name == "arm_a":
                trace = _object(obj.get("driver_trace"), "arms.arm_a.driver_trace")
                _keys(trace, {"required", "path"}, set(), "arms.arm_a.driver_trace")
                if trace["required"] is not True:
                    raise ManifestError("arms.arm_a.driver_trace.required must be true")
                driver_trace_path = _string(trace["path"], "arms.arm_a.driver_trace.path")
                trace_path = Path(driver_trace_path)
                if trace_path.is_absolute() or ".." in trace_path.parts:
                    raise ManifestError("arms.arm_a.driver_trace.path must be repository-relative")
        else:
            if escalations:
                raise ManifestError("arms.arm_c.escalations must be empty; models cannot replace operator routing")
            if repair.backend != hands.backend:
                raise ManifestError("arms.arm_c.repair must use the same cheap hands backend")
            route = _object(obj["question_route"], "arms.arm_c.question_route")
            _keys(
                route,
                {"question_template", "resume_prompt_template", "max_questions"},
                set(),
                "arms.arm_c.question_route",
            )
            question_template = _string(
                route["question_template"], "arms.arm_c.question_route.question_template"
            )
            resume_template = _string(
                route["resume_prompt_template"],
                "arms.arm_c.question_route.resume_prompt_template",
            )
            for template in (question_template, resume_template):
                if template not in templates:
                    raise ManifestError(f"arms.arm_c.question_route names unknown template {template!r}")
            question_route = QuestionRoute(
                question_template,
                resume_template,
                _positive_int(route["max_questions"], "arms.arm_c.question_route.max_questions"),
            )
        arms[arm_name] = PilotArm(
            name=arm_name,
            mode=mode,
            hands=hands,
            repair=repair,
            escalations=escalations,
            driver=driver,
            question_route=question_route,
            driver_trace_path=driver_trace_path,
        )

    if len({arms[name].hands for name in ARMS}) != 1:
        raise ManifestError("all three arms must freeze the identical cheap-hands backend and prompt")
    hands_backend = backends[arms["arm_a"].hands.backend]
    if hands_backend.tier != "cheap":
        raise ManifestError("the common hands backend tier must be 'cheap'")

    return PilotComposition(
        path=path,
        sha256=_sha(raw),
        protocol_commit=protocol_commit,
        isolation=isolation,
        tool_versions=dict(tool_versions),
        templates=templates,
        backends=backends,
        arms=arms,
    )
