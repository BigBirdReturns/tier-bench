from __future__ import annotations

# Production pilot activation binds this backend-manifest authority exactly.

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable


SCHEMA = "tier-bench/pilot-backends@1"
COST_BASES = {"real-billed", "shadow-estimated", "subscription-derived"}
PLACEHOLDERS = {
    "{arm}",
    "{backend_result}",
    "{dispatch_receipt}",
    "{prompt}",
    "{task_id}",
    "{worktree}",
}


class ManifestError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


@dataclass(frozen=True)
class Backend:
    arm: str
    model_id: str
    effort: str
    surface: str
    cost_basis: str
    account: str
    tier: str
    command: tuple[str, ...]
    template_name: str
    template_path: Path
    template_bytes: bytes
    template_sha256: str
    manifest_path: Path
    manifest_sha256: str
    protocol_commit: str
    isolation: dict[str, Any]
    tool_versions: dict[str, str]


def _need(obj: dict[str, Any], key: str, kind: type) -> Any:
    value = obj.get(key)
    if not isinstance(value, kind):
        raise ManifestError(f"{key} must be {kind.__name__}")
    return value


def _need_nonempty(obj: dict[str, Any], key: str) -> str:
    value = _need(obj, key, str)
    if not value:
        raise ManifestError(f"{key} must be non-empty")
    return value


def _validate_command(command: list[Any]) -> tuple[str, ...]:
    if not command or not all(isinstance(x, str) and x for x in command):
        raise ManifestError("adapter.command must be a non-empty argv string array")
    joined = "\n".join(command)
    unknown = set(re.findall(r"\{[^{}]+\}", joined)) - PLACEHOLDERS
    if unknown:
        raise ManifestError(f"adapter.command has unknown placeholders: {sorted(unknown)}")
    required = {"{backend_result}", "{dispatch_receipt}", "{prompt}", "{worktree}"}
    missing = {x for x in required if x not in joined}
    if missing:
        raise ManifestError(f"adapter.command is missing placeholders: {sorted(missing)}")
    return tuple(command)


def load_backend(
    path: Path,
    arm: str,
    read_bytes: Callable[[Path], bytes] | None = None,
) -> Backend:
    path = path.resolve()
    reader = read_bytes or (lambda item: item.read_bytes())
    raw = reader(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ManifestError(f"manifest schema must be {SCHEMA}")
    protocol_commit = _need(data, "protocol_commit", str)
    if not re.fullmatch(r"[0-9a-f]{40}", protocol_commit):
        raise ManifestError("protocol_commit must be a full lowercase Git SHA")

    isolation = _need(data, "isolation", dict)
    required_isolation = {
        "fresh_session_per_call": True,
        "instruction_files": False,
        "auto_memory": False,
        "conversation_carryover": False,
    }
    for key, expected in required_isolation.items():
        if isolation.get(key) is not expected:
            raise ManifestError(f"isolation.{key} must be {expected!r}")
    tool_versions = _need(data, "tool_versions", dict)
    if not tool_versions or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in tool_versions.items()
    ):
        raise ManifestError("tool_versions must bind at least one non-empty name/version")

    templates = _need(data, "prompt_templates", dict)
    arms = _need(data, "arms", dict)
    if arm not in arms or not isinstance(arms[arm], dict):
        raise ManifestError(f"manifest has no arm {arm!r}")
    entry = arms[arm]
    template_name = _need(entry, "prompt_template", str)
    template = templates.get(template_name)
    if not isinstance(template, dict):
        raise ManifestError(f"unknown prompt template {template_name!r}")
    template_rel = Path(_need(template, "path", str))
    if template_rel.is_absolute() or ".." in template_rel.parts:
        raise ManifestError("prompt template path must stay under the manifest directory")
    template_path = (path.parent / template_rel).resolve()
    try:
        template_path.relative_to(path.parent)
    except ValueError as exc:
        raise ManifestError("prompt template escapes the manifest directory") from exc
    declared_template_hash = _need(template, "sha256", str)
    template_bytes = reader(template_path)
    actual_template_hash = sha256_bytes(template_bytes)
    if actual_template_hash != declared_template_hash:
        raise ManifestError(
            f"prompt template hash mismatch: expected {declared_template_hash}, "
            f"got {actual_template_hash}"
        )

    cost_basis = _need_nonempty(entry, "cost_basis")
    if cost_basis not in COST_BASES:
        raise ManifestError(f"unsupported cost_basis {cost_basis!r}")
    adapter = _need(entry, "adapter", dict)
    command = _validate_command(_need(adapter, "command", list))
    return Backend(
        arm=arm,
        model_id=_need_nonempty(entry, "model_id"),
        effort=_need_nonempty(entry, "effort"),
        surface=_need_nonempty(entry, "surface"),
        cost_basis=cost_basis,
        account=_need_nonempty(entry, "account"),
        tier=_need_nonempty(entry, "tier"),
        command=command,
        template_name=template_name,
        template_path=template_path,
        template_bytes=template_bytes,
        template_sha256=actual_template_hash,
        manifest_path=path,
        manifest_sha256=sha256_bytes(raw),
        protocol_commit=protocol_commit,
        isolation=isolation,
        tool_versions=tool_versions,
    )


def expand_command(command: tuple[str, ...], values: dict[str, str]) -> list[str]:
    expanded: list[str] = []
    for arg in command:
        for key, value in values.items():
            arg = arg.replace("{" + key + "}", value)
        if re.search(r"\{[^{}]+\}", arg):
            raise ManifestError(f"unexpanded command placeholder in {arg!r}")
        expanded.append(arg)
    return expanded
