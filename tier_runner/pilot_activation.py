from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from .pilot_manifest import PROTOCOL_COMMIT, PilotComposition, load_pilot_composition


SCHEMA = "tier-bench/tier-pilot-activation@1"
EXECUTOR_IDENTITY = "tier-bench/pilot-production-adapter@1"
ADAPTER_IDENTITY = "tier-bench/pilot-claude-code-bytes@1"
ADAPTER_VERSION = "1"
PROVIDER_RESULT_SCHEMA = "tier-bench/tier-backend-result@1"
DEFAULT_REF = "refs/remotes/origin/main"
REMOTE_DEFAULT_REF = "refs/heads/main"
CONTROL_REMOTE_URL = "https://github.com/BigBirdReturns/tier-bench.git"
SOURCE_PATHS = {
    "activation_validator": "tier_runner/pilot_activation.py",
    "production_adapter": "tier_runner/pilot_adapter.py",
    "production_bridge": "tier_runner/pilot_bridge.py",
    "claude_adapter": "tier_runner/adapters/claude_code.py",
    "composition_runtime": "tier_runner/pilot_composition.py",
    "composition_manifest_runtime": "tier_runner/pilot_manifest.py",
    "runner_core": "tier_runner/core.py",
    "backend_manifest_runtime": "tier_runner/manifest.py",
}
PRODUCTION_SCHEMA_PATHS = {
    "activation": "schemas/tier_pilot_activation.schema.json",
    "dispatch": "schemas/tier_pilot_dispatch_receipt.schema.json",
    "provider": "schemas/tier_pilot_production_provider_evidence.schema.json",
    "acceptance": "schemas/tier_pilot_production_acceptance_evidence.schema.json",
    "bridge": "schemas/tier_pilot_production_bridge_receipt.schema.json",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")


class ActivationError(ValueError):
    pass


@dataclass(frozen=True)
class PilotActivation:
    repository: Path
    commit: str
    path: str
    sha256: str
    composition: PilotComposition
    adapter: dict[str, str]
    document: dict[str, Any]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActivationError(f"{label} must be an object")
    if set(value) != expected:
        raise ActivationError(
            f"{label} fields mismatch; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActivationError(f"{label} must be a non-empty string")
    return value


def _digest(value: Any, label: str) -> str:
    value = _string(value, label)
    if not SHA256.fullmatch(value):
        raise ActivationError(f"{label} must be a lowercase SHA-256")
    return value


def _safe_path(value: Any, label: str) -> str:
    value = _string(value, label).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] == ".git":
        raise ActivationError(f"{label} must be a safe repository-relative path")
    return path.as_posix()


def _artifact(value: Any, label: str) -> dict[str, str]:
    obj = _keys(value, {"path", "sha256"}, label)
    return {
        "path": _safe_path(obj["path"], f"{label}.path"),
        "sha256": _digest(obj["sha256"], f"{label}.sha256"),
    }


def _git_bytes(repository: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, text=False
    )
    if check and result.returncode:
        raise ActivationError(
            f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def _blob(repository: Path, commit: str, path: str) -> bytes:
    return _git_bytes(repository, "show", f"{commit}:{path}")


def _open_artifact(repository: Path, commit: str, value: Any, label: str) -> bytes:
    artifact = _artifact(value, label)
    raw = _blob(repository, commit, artifact["path"])
    actual = _sha(raw)
    if actual != artifact["sha256"]:
        raise ActivationError(
            f"{label} hash mismatch: expected {artifact['sha256']}, got {actual}"
        )
    return raw


def _runtime_source(path: str) -> bytes:
    root = Path(__file__).resolve().parents[1]
    raw = (root / path).read_bytes()
    if b"\r\n" in raw:
        raise ActivationError(f"running source is not LF-exact: {path}")
    return raw


def _local_import_paths(raw: bytes, source_path: str) -> set[str]:
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=source_path)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise ActivationError(f"activated source cannot be parsed: {source_path}: {exc}") from exc
    module_parts = list(PurePosixPath(source_path).with_suffix("").parts)
    package = module_parts[:-1]
    imported: set[str] = set()
    for node in ast.walk(tree):
        targets: list[list[str]] = []
        if isinstance(node, ast.ImportFrom):
            module = node.module.split(".") if node.module else []
            if node.level:
                keep = len(package) - node.level + 1
                if keep < 0:
                    raise ActivationError(f"relative import escapes tier_runner: {source_path}")
                base = package[:keep] + module
                if module:
                    targets.append(base)
                else:
                    targets.extend(base + alias.name.split(".") for alias in node.names)
            elif module[:1] == ["tier_runner"]:
                if len(module) > 1:
                    targets.append(module)
                else:
                    targets.extend(module + alias.name.split(".") for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[:1] == ["tier_runner"]:
                    targets.append(parts)
        for parts in targets:
            if parts[:1] != ["tier_runner"] or len(parts) < 2:
                continue
            imported.add(PurePosixPath(*parts).with_suffix(".py").as_posix())
    return imported


def _authenticated_remote_head(repository: Path) -> str:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", REMOTE_DEFAULT_REF],
        cwd=repository,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ActivationError(
            "cannot authenticate the remote default branch: "
            + result.stderr.strip()
        )
    rows = [line.split("\t") for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != REMOTE_DEFAULT_REF:
        raise ActivationError("remote default branch did not resolve to exactly one ref")
    remote_head = rows[0][0]
    if not GIT_SHA.fullmatch(remote_head):
        raise ActivationError("remote default branch did not resolve to a commit SHA")
    fetched = subprocess.run(
        [
            "git", "fetch", "--no-tags", "--no-write-fetch-head",
            "origin", REMOTE_DEFAULT_REF,
        ],
        cwd=repository,
        capture_output=True,
        text=True,
    )
    if fetched.returncode:
        raise ActivationError(
            "cannot fetch authenticated remote default-branch objects: "
            + fetched.stderr.strip()
        )
    opened = subprocess.run(
        ["git", "cat-file", "-e", f"{remote_head}^{{commit}}"],
        cwd=repository,
        capture_output=True,
    )
    if opened.returncode:
        raise ActivationError("authenticated remote default-branch commit did not open")
    return remote_head


def load_official_activation(
    repository: Path,
    commit: str,
    path: str,
) -> PilotActivation:
    repository = repository.resolve()
    if not GIT_SHA.fullmatch(commit):
        raise ActivationError("activation commit must be a full lowercase Git SHA")
    path = _safe_path(path, "activation path")
    raw = _blob(repository, commit, path)
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActivationError(f"activation JSON is invalid: {exc}") from exc
    document = _keys(
        document,
        {
            "schema", "status", "protocol_commit", "executor_identity",
            "composition_manifest", "backend_entry_sha256s", "prompt_templates",
            "sources", "adapter", "production_schemas", "control_repository",
            "guards",
        },
        "activation",
    )
    if document["schema"] != SCHEMA:
        raise ActivationError(f"activation schema must be {SCHEMA}")
    if document["status"] != "OPERATOR_RATIFIED":
        raise ActivationError("activation status must be OPERATOR_RATIFIED")
    if document["protocol_commit"] != PROTOCOL_COMMIT:
        raise ActivationError("activation protocol commit drifted from registered v1.3")
    if document["executor_identity"] != EXECUTOR_IDENTITY:
        raise ActivationError("activation executor identity is not code-owned")

    control = _keys(
        document["control_repository"],
        {"remote_url", "default_ref", "evidence_root"},
        "control_repository",
    )
    remote_url = _string(control["remote_url"], "control_repository.remote_url")
    if remote_url != CONTROL_REMOTE_URL:
        raise ActivationError("activation control repository is not tier-bench origin")
    if control["default_ref"] != DEFAULT_REF:
        raise ActivationError(f"control_repository.default_ref must be {DEFAULT_REF}")
    _safe_path(control["evidence_root"], "control_repository.evidence_root")
    actual_remote = _git_bytes(repository, "remote", "get-url", "origin").decode().strip()
    if actual_remote != remote_url:
        raise ActivationError("activation control-repository remote identity drifted")
    remote_head = _authenticated_remote_head(repository)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, remote_head],
        cwd=repository, capture_output=True,
    )
    if ancestor.returncode != 0:
        raise ActivationError("activation commit is not on the authenticated remote default branch")

    sources = _keys(document["sources"], set(SOURCE_PATHS), "sources")
    opened_sources: dict[str, bytes] = {}
    for name, expected_path in SOURCE_PATHS.items():
        artifact = _artifact(sources[name], f"sources.{name}")
        if artifact["path"] != expected_path:
            raise ActivationError(f"sources.{name}.path must be {expected_path}")
        committed = _open_artifact(repository, commit, artifact, f"sources.{name}")
        if committed != _runtime_source(expected_path):
            raise ActivationError(f"running {name} bytes differ from the activated source")
        opened_sources[expected_path] = committed
    imported_paths = set().union(*(
        _local_import_paths(raw, path) for path, raw in opened_sources.items()
    ))
    missing_sources = imported_paths - set(SOURCE_PATHS.values())
    if missing_sources:
        raise ActivationError(
            f"activated transitive source closure is incomplete: {sorted(missing_sources)}"
        )

    composition_artifact = _artifact(document["composition_manifest"], "composition_manifest")
    composition_raw = _open_artifact(
        repository, commit, composition_artifact, "composition_manifest"
    )
    composition_path = (repository / composition_artifact["path"]).resolve()

    def git_reader(item: Path) -> bytes:
        try:
            relative = item.resolve().relative_to(repository).as_posix()
        except ValueError as exc:
            raise ActivationError("composition artifact escaped the control repository") from exc
        return _blob(repository, commit, relative)

    composition = load_pilot_composition(composition_path, read_bytes=git_reader)
    if composition.sha256 != _sha(composition_raw):
        raise ActivationError("composition loader did not open the activated bytes")
    composition_value = json.loads(composition_raw)
    expected_backends = {
        name: _sha(_canonical(value))
        for name, value in composition_value["backends"].items()
    }
    backend_hashes = _keys(
        document["backend_entry_sha256s"], set(expected_backends),
        "backend_entry_sha256s",
    )
    for name, expected in expected_backends.items():
        if _digest(backend_hashes[name], f"backend_entry_sha256s.{name}") != expected:
            raise ActivationError(f"backend entry {name!r} drifted from the composition")

    prompt_values = document["prompt_templates"]
    if not isinstance(prompt_values, list):
        raise ActivationError("prompt_templates must be an array")
    opened_prompts: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(prompt_values):
        obj = _keys(item, {"name", "path", "sha256"}, f"prompt_templates[{index}]")
        name = _string(obj["name"], f"prompt_templates[{index}].name")
        if name in opened_prompts:
            raise ActivationError(f"duplicate prompt template {name!r}")
        artifact = _artifact(
            {"path": obj["path"], "sha256": obj["sha256"]},
            f"prompt_templates[{index}]",
        )
        _open_artifact(repository, commit, artifact, f"prompt_templates[{index}]")
        opened_prompts[name] = (artifact["path"], artifact["sha256"])
    expected_prompts = {
        name: (
            template.path.resolve().relative_to(repository).as_posix(),
            template.sha256,
        )
        for name, template in composition.templates.items()
    }
    if opened_prompts != expected_prompts:
        raise ActivationError("prompt-template bindings differ from the composition")

    adapter = _keys(
        document["adapter"],
        {
            "identity", "version", "binary", "cli_version", "help_sha256",
            "provider_result_schema",
        },
        "adapter",
    )
    if adapter["identity"] != ADAPTER_IDENTITY or adapter["version"] != ADAPTER_VERSION:
        raise ActivationError("adapter identity/version drifted from code-owned values")
    if adapter["provider_result_schema"] != PROVIDER_RESULT_SCHEMA:
        raise ActivationError("adapter provider-result schema drifted")
    for key in ("binary", "cli_version"):
        _string(adapter[key], f"adapter.{key}")
    _digest(adapter["help_sha256"], "adapter.help_sha256")

    schemas = _keys(
        document["production_schemas"], set(PRODUCTION_SCHEMA_PATHS),
        "production_schemas",
    )
    for name, expected_path in PRODUCTION_SCHEMA_PATHS.items():
        artifact = _artifact(schemas[name], f"production_schemas.{name}")
        if artifact["path"] != expected_path:
            raise ActivationError(
                f"production_schemas.{name}.path must be {expected_path}"
            )
        _open_artifact(repository, commit, artifact, f"production_schemas.{name}")

    guards = _keys(
        document["guards"],
        {
            "production_entrypoint_requires_activation",
            "canary_requires_separate_operator_authorization",
            "pilot_task_disclosure_authorized",
            "scientific_verdict_minted",
        },
        "guards",
    )
    if guards != {
        "production_entrypoint_requires_activation": True,
        "canary_requires_separate_operator_authorization": True,
        "pilot_task_disclosure_authorized": False,
        "scientific_verdict_minted": False,
    }:
        raise ActivationError("activation guards do not preserve the launch boundary")

    return PilotActivation(
        repository=repository,
        commit=commit,
        path=path,
        sha256=_sha(raw),
        composition=composition,
        adapter={key: str(value) for key, value in adapter.items()},
        document=document,
    )
