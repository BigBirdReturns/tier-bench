"""Executable identity binding for Astra Stage 2 empirical controls.

This module hashes local checkpoint, source, runtime, adapter, quantization, and
hardware evidence into the six digest fields consumed by the existing Stage 2
control manifest. Full path-bearing evidence remains private. Public receipts
carry only immutable coordinates, digests, counts, and bounded status.
"""

from __future__ import annotations

import base64
import copy
import csv
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from .canonical import (
    Stage2Error,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    sha256_object,
    strict_json_load,
    write_json_atomic,
)
from .contracts import bind_empirical_control_manifest, validate_generator_manifest, validate_plan
from .generator import build_calibration_plan, build_generator_manifest, empirical_control_template

SCHEMA_BINDING_INPUT = "tier-bench/astra-stage2-control-binding-input@2"
SCHEMA_PRIVATE_CONTROL = "tier-bench/astra-stage2-executable-control-private@2"
SCHEMA_PUBLIC_CONTROL = "tier-bench/astra-stage2-executable-control-public@2"
SCHEMA_CONTROL_SET = "tier-bench/astra-stage2-executable-control-set@2"
SCHEMA_PRIVATE_SET = "tier-bench/astra-stage2-executable-control-private-set@1"
SCHEMA_HARDWARE_PROBE = "tier-bench/astra-stage2-hardware-probe@2"
SCHEMA_HARDWARE_PLATFORM = "tier-bench/astra-stage2-hardware-platform@1"
SCHEMA_TOPOLOGY_EVIDENCE = "tier-bench/astra-stage2-topology-evidence@1"

LAW_COMMIT_SHA1 = "c36c35bf9b70d879e1e1c9ee2f0296879442df3e"
LAW_TREE_SHA1 = "87bff3320c680e91eaec66c287d7a1ac3b7fe523"
LAW_PATH = "docs/agents/claims/FRR-ASTRA-STAGE2-1.md"
LAW_BLOB_SHA1 = "77abe4e177fc61e4f52f56ea64494b113f9662fc"
SCAFFOLD_HEAD_SHA1 = "9babad4631ef517485c56ea4906aab123e30fad7"
SCAFFOLD_TREE_SHA1 = "720cbf3f26f2e251613acedc52cff08ef33892dc"
STAGE1_JOIN_HEAD_SHA1 = "60bca963d63edca267106bc5c7725c2cc1df8dd7"
GENERATOR_MANIFEST_SHA256 = "2050de80cb4688b182cf9e006a97959da422dce24138c6451774f03320517328"

FROZEN_IMPLEMENTATION_BLOBS = {
    "astra_stage2/generator.py": "45f23fe0c2f7062dccfa9de8b267036a59f53726",
    "astra_stage2/canonical.py": "96f1e61bfe01daba44507a66d5ed231f4c45b9fb",
    "astra_stage2/contracts.py": "ba7516b293d7c16230f8170a9e7932c65892876c",
    "astra_stage2/calibration.py": "fcbdb8bcf3199bde33dea9342c3feff79f464d3d",
    "experiments/astra_kxr/stage2/generator-manifest.index.json": "a7b79543c1c03d43aeaa53471d4f865a809aa4fd",
    "experiments/astra_kxr/stage2/calibration-plan.fixture.index.json": "782f3cb888eb99626575c2c7d82e793fe7c6b21f",
}

CONTROL_ORDER = (
    "lotus_3b_recurrent",
    "loopcoder_v2_7b_parallel",
    "conventional_transformer_negative",
)

PUBLIC_CONTROLS = {
    "lotus_3b_recurrent": {
        "class_label": "recurrent_latent",
        "source_repository": "yingfan-bot/lotus",
        "source_commit_sha1": "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
        "checkpoint_repository": "yingfanbot/gsm-lotus-llama3b",
        "checkpoint_revision_sha1": "b392d2cb7aaa73475b93028221523c47f49f66a2",
    },
    "loopcoder_v2_7b_parallel": {
        "class_label": "parallel_latent",
        "source_repository": "CSJianYang/LoopCoder",
        "source_commit_sha1": "ab0d92d7cc87c4ed0fd30c1db1f2edd685435c4c",
        "checkpoint_repository": "Multilingual-Multimodal-NLP/LoopCoder-V2",
        "checkpoint_revision_sha1": "b87cf3aa2186937b0d0362a684d7d30f234543e3",
    },
    "conventional_transformer_negative": {
        "class_label": "conventional_negative",
        "source_repository": "yingfan-bot/lotus",
        "source_commit_sha1": "eb77e2f7909c5006f58ff0ad7cd6629b942caa9e",
        "checkpoint_repository": "yingfanbot/gsm-cot-llama3b",
        "checkpoint_revision_sha1": "63de1ec1902ed143fe62250b6ddb14cb65f06e1a",
    },
}

BINDING_FIELDS = frozenset(
    {
        "schema",
        "binding_id",
        "law",
        "scaffold",
        "stage1_join_head",
        "generator_manifest_sha256",
        "controls",
    }
)
LAW_FIELDS = frozenset({"commit_sha1", "tree_sha1", "blob_sha1"})
SCAFFOLD_FIELDS = frozenset({"head_sha1", "tree_sha1"})
CONTROL_FIELDS = frozenset(
    {
        "role",
        "class_label",
        "source_repository",
        "source_commit_sha1",
        "source_root",
        "checkpoint_repository",
        "checkpoint_revision_sha1",
        "model_root",
        "revision_marker_path",
        "model_config_paths",
        "tokenizer_paths",
        "weight_index_path",
        "weight_paths",
        "runtime",
        "adapter",
        "quantization",
        "hardware",
        "effort_mapping",
    }
)
RUNTIME_FIELDS = frozenset(
    {
        "root",
        "name",
        "version",
        "build",
        "executable_path",
        "configuration_paths",
        "configuration",
        "probe_args",
        "required_probe_substrings",
        "probe_timeout_seconds",
    }
)
ADAPTER_FIELDS = frozenset({"identity", "root", "paths", "configuration"})
QUANTIZATION_FIELDS = frozenset({"identity", "parameters"})
HARDWARE_FIELDS = frozenset(
    {
        "evidence_root",
        "platform_path",
        "device_query_path",
        "topology_evidence_path",
        "selected_device_indices",
    }
)
PLATFORM_RECORD_FIELDS = frozenset(
    {
        "schema",
        "system",
        "release",
        "version",
        "machine",
        "processor",
        "python_implementation",
        "python_version",
        "selected_device_indices",
        "nvidia_smi_executable_sha256",
        "payload_sha256",
    }
)
LINUX_TOPOLOGY_FIELDS = frozenset(
    {
        "schema",
        "state",
        "platform",
        "method",
        "selected_device_indices",
        "selected_device_query_rows_sha256",
        "device_query_sha256",
        "matrix_stdout_base64",
        "matrix_stdout_sha256",
        "inter_device_topology_claimed",
        "implicit_pooling_claimed",
        "payload_sha256",
    }
)
WINDOWS_TOPOLOGY_FIELDS = frozenset(
    {
        "schema",
        "state",
        "platform",
        "method",
        "selected_device_index",
        "selected_device_query_row_sha256",
        "device_query_sha256",
        "inter_device_topology_claimed",
        "implicit_pooling_claimed",
        "payload_sha256",
    }
)
EFFORT_MAPPING_FIELDS = frozenset({"low", "high"})
EFFORT_FIELDS = frozenset({"arguments", "environment", "configuration"})

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
FORBIDDEN_INPUT_KEYS = {
    "prompt",
    "prompt_text",
    "response",
    "response_text",
    "completion",
    "completion_text",
    "transcript",
    "messages",
    "raw_request",
    "raw_response",
}
FORBIDDEN_PUBLIC_KEYS = {
    "path",
    "paths",
    "root",
    "source_root",
    "model_root",
    "runtime_root",
    "evidence_root",
    "executable_path",
    "configuration_paths",
    "probe_args",
    "stdout",
    "stderr",
    "uuid",
    "pci_bus_id",
}

DEFAULT_MODEL_CONFIG_NAMES = (
    "config.json",
    "generation_config.json",
    "model_config.json",
    "params.json",
)
DEFAULT_TOKENIZER_NAMES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "sentencepiece.model",
    "tokenizer.model",
)
DEFAULT_WEIGHT_INDEX_NAMES = (
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
)
DEFAULT_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".gguf", ".pt", ".pth")


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Stage2Error(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage2Error(f"{label} must be an array")
    return value


def _require_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise Stage2Error(f"{label} must be a string")
    if nonempty and not value.strip():
        raise Stage2Error(f"{label} must not be empty")
    return value


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Stage2Error(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise Stage2Error(f"{label} must be >= {minimum}")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise Stage2Error(f"{label} must be a boolean")
    return value


def _require_sha1(value: Any, label: str) -> str:
    value = _require_string(value, label)
    if not SHA1_RE.fullmatch(value):
        raise Stage2Error(f"{label} must be a lowercase 40-hex SHA-1")
    return value


def _require_sha256(value: Any, label: str) -> str:
    value = _require_string(value, label)
    if not SHA256_RE.fullmatch(value):
        raise Stage2Error(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    observed = set(value)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        raise Stage2Error(
            f"{label} property set mismatch: missing={missing}, unexpected={unexpected}"
        )


def _assert_finite_json(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Stage2Error(f"non-finite value at {path}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_finite_json(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise Stage2Error(f"non-string key at {path}")
            if key.lower() in FORBIDDEN_INPUT_KEYS:
                raise Stage2Error(f"forbidden text-bearing key at {path}.{key}")
            _assert_finite_json(child, f"{path}.{key}")
        return
    raise Stage2Error(f"unsupported JSON value at {path}: {type(value).__name__}")


def _run_git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or f"exit {process.returncode}"
        raise Stage2Error(f"git {' '.join(arguments)} failed: {detail}")
    return process.stdout.strip()


def _git_is_ancestor(root: Path, ancestor: str, descendant: str = "HEAD") -> None:
    process = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    )
    if process.returncode == 1:
        raise Stage2Error(f"required ancestor {ancestor} is not reachable from {descendant}")
    if process.returncode != 0:
        raise Stage2Error(f"unable to verify ancestor {ancestor}")


def _normalise_repository_url(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith("git@github.com:"):
        value = value[len("git@github.com:") :]
    for prefix in ("https://github.com/", "http://github.com/", "ssh://git@github.com/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if value.endswith(".git"):
        value = value[:-4]
    return value.strip("/")


def verify_repository_coordinates(repo_root: Path) -> dict[str, Any]:
    repo_root = Path(_run_git(repo_root.resolve(), "rev-parse", "--show-toplevel")).resolve()
    _git_is_ancestor(repo_root, SCAFFOLD_HEAD_SHA1)
    _git_is_ancestor(repo_root, LAW_COMMIT_SHA1)
    if _run_git(repo_root, "rev-parse", f"{SCAFFOLD_HEAD_SHA1}^{{tree}}") != SCAFFOLD_TREE_SHA1:
        raise Stage2Error("qualified scaffold tree differs from the frozen law coordinate")
    if _run_git(repo_root, "rev-parse", f"{LAW_COMMIT_SHA1}^{{tree}}") != LAW_TREE_SHA1:
        raise Stage2Error("released law tree differs from its frozen coordinate")
    law_blob = _run_git(repo_root, "rev-parse", f"HEAD:{LAW_PATH}")
    if law_blob != LAW_BLOB_SHA1:
        raise Stage2Error(f"law blob mismatch: expected {LAW_BLOB_SHA1}, observed {law_blob}")
    observed_blobs: dict[str, str] = {}
    for path, expected in FROZEN_IMPLEMENTATION_BLOBS.items():
        observed = _run_git(repo_root, "rev-parse", f"HEAD:{path}")
        if observed != expected:
            raise Stage2Error(f"frozen implementation blob mismatch for {path}")
        observed_blobs[path] = observed
    generator = build_generator_manifest()
    validate_generator_manifest(generator)
    if generator.get("payload_sha256") != GENERATOR_MANIFEST_SHA256:
        raise Stage2Error("generator manifest digest differs from the released law")
    return {
        "repository_root": str(repo_root),
        "head_sha1": _run_git(repo_root, "rev-parse", "HEAD"),
        "tree_sha1": _run_git(repo_root, "rev-parse", "HEAD^{tree}"),
        "law_blob_sha1": law_blob,
        "implementation_blobs": observed_blobs,
        "generator_manifest_sha256": generator["payload_sha256"],
    }


def _relative_name(value: Any, label: str) -> str:
    raw = _require_string(value, label).replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or raw.startswith("/") or any(part in {"", ".", ".."} for part in pure.parts):
        raise Stage2Error(f"{label} must be a clean relative path")
    return pure.as_posix()


def _resolve_regular_file(root: Path, relative: str, label: str) -> Path:
    root = root.expanduser().resolve()
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise Stage2Error(f"{label} escapes its declared root") from exc
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise Stage2Error(f"{label} traverses a symbolic link: {relative}")
    if not path.is_file():
        raise Stage2Error(f"{label} is not a regular file: {relative}")
    return path




def _inventory_tree(root: Path, label: str) -> dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise Stage2Error(f"{label} root is not a directory")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise Stage2Error(f"{label} contains a symbolic link: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise Stage2Error(f"{label} contains a non-regular filesystem object: {relative}")
        entries.append(
            {
                "name": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not entries:
        raise Stage2Error(f"{label} contains no files")
    return {
        "file_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in entries),
        "files": entries,
        "content_manifest_sha256": sha256_object(entries),
    }

def _file_entry(root: Path, relative: str, label: str) -> dict[str, Any]:
    relative = _relative_name(relative, label)
    path = _resolve_regular_file(root, relative, label)
    return {"name": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _entries(root: Path, raw_paths: Any, label: str, *, require_nonempty: bool = True) -> list[dict[str, Any]]:
    raw = _require_list(raw_paths, label)
    normalised = [_relative_name(item, f"{label}[{index}]") for index, item in enumerate(raw)]
    if len(set(normalised)) != len(normalised):
        raise Stage2Error(f"{label} contains duplicate paths")
    if require_nonempty and not normalised:
        raise Stage2Error(f"{label} must not be empty")
    return [_file_entry(root, path, f"{label}[{index}]") for index, path in enumerate(sorted(normalised))]


def _tracked_source_manifest(source_root: Path, expected_repository: str, expected_commit: str) -> dict[str, Any]:
    source_root = Path(_run_git(source_root.expanduser().resolve(), "rev-parse", "--show-toplevel")).resolve()
    head = _run_git(source_root, "rev-parse", "HEAD")
    if head != expected_commit:
        raise Stage2Error(f"source checkout head mismatch: expected {expected_commit}, observed {head}")
    status = _run_git(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise Stage2Error("source checkout must be clean and contain no untracked files")
    origin = _run_git(source_root, "config", "--get", "remote.origin.url")
    if _normalise_repository_url(origin) != expected_repository:
        raise Stage2Error(
            f"source origin mismatch: expected {expected_repository}, observed {_normalise_repository_url(origin)}"
        )
    raw = subprocess.run(
        ["git", "-C", str(source_root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if raw.returncode != 0:
        raise Stage2Error("unable to enumerate tracked source files")
    names = [item.decode("utf-8") for item in raw.stdout.split(b"\0") if item]
    if not names:
        raise Stage2Error("source checkout contains no tracked files")
    entries = [_file_entry(source_root, name, f"source file {name}") for name in sorted(names)]
    return {
        "repository": expected_repository,
        "commit_sha1": head,
        "tree_sha1": _run_git(source_root, "rev-parse", "HEAD^{tree}"),
        "origin_sha256": sha256_bytes(origin.encode("utf-8")),
        "file_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in entries),
        "files": entries,
        "content_manifest_sha256": sha256_object(entries),
    }


def _checkpoint_revision_evidence(model_root: Path, revision: str, marker: Any) -> dict[str, Any]:
    basename_match = model_root.expanduser().resolve().name == revision
    marker_entry: dict[str, Any] | None = None
    marker_match = False
    if marker is not None:
        marker_name = _relative_name(marker, "revision_marker_path")
        marker_path = _resolve_regular_file(model_root, marker_name, "revision marker")
        data = marker_path.read_bytes()
        marker_entry = {"name": marker_name, "bytes": len(data), "sha256": sha256_bytes(data)}
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise Stage2Error("revision marker must be UTF-8 text") from exc
        marker_match = text == revision
    if not basename_match and not marker_match:
        raise Stage2Error(
            "checkpoint revision is not evidenced by the snapshot directory name or exact revision marker"
        )
    return {
        "revision_sha1": revision,
        "snapshot_directory_name_matches": basename_match,
        "marker_matches": marker_match,
        "marker": marker_entry,
    }


def _validate_weight_index(
    model_root: Path,
    index_name: Any,
    weight_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    if index_name is None:
        return {"identity": "NONE", "entry": None, "weight_map_sha256": None}
    index_name = _relative_name(index_name, "weight_index_path")
    index_path = _resolve_regular_file(model_root, index_name, "weight index")
    index = strict_json_load(index_path)
    if not isinstance(index, dict) or not isinstance(index.get("weight_map"), dict):
        raise Stage2Error("weight index must contain an object-valued weight_map")
    mapped = sorted(set(index["weight_map"].values()))
    for value in mapped:
        _relative_name(value, "weight index shard")
    observed = sorted(item["name"] for item in weight_entries)
    if mapped != observed:
        raise Stage2Error(
            f"weight index shard set mismatch: index={mapped}, configured={observed}"
        )
    return {
        "identity": "INDEXED",
        "entry": _file_entry(model_root, index_name, "weight index"),
        "weight_map_sha256": sha256_object(index["weight_map"]),
    }


def _runtime_manifest(runtime: Any) -> tuple[dict[str, Any], Path]:
    runtime = _require_mapping(runtime, "runtime")
    _require_exact_keys(runtime, RUNTIME_FIELDS, "runtime")
    root = Path(_require_string(runtime["root"], "runtime.root")).expanduser().resolve()
    name = _require_string(runtime["name"], "runtime.name")
    version = _require_string(runtime["version"], "runtime.version")
    build = _require_string(runtime["build"], "runtime.build")
    executable_name = _relative_name(runtime["executable_path"], "runtime.executable_path")
    executable = _resolve_regular_file(root, executable_name, "runtime executable")
    config_entries = _entries(
        root,
        runtime["configuration_paths"],
        "runtime.configuration_paths",
        require_nonempty=False,
    )
    configuration = runtime["configuration"]
    _assert_finite_json(configuration, "runtime.configuration")
    probe_args_raw = _require_list(runtime["probe_args"], "runtime.probe_args")
    probe_args = [_require_string(value, f"runtime.probe_args[{index}]", nonempty=False) for index, value in enumerate(probe_args_raw)]
    required_raw = _require_list(
        runtime["required_probe_substrings"], "runtime.required_probe_substrings"
    )
    required = [
        _require_string(value, f"runtime.required_probe_substrings[{index}]")
        for index, value in enumerate(required_raw)
    ]
    if not required:
        raise Stage2Error("runtime.required_probe_substrings must not be empty")
    timeout = _require_int(runtime["probe_timeout_seconds"], "runtime.probe_timeout_seconds", minimum=1)
    if timeout > 120:
        raise Stage2Error("runtime probe timeout must be <= 120 seconds")
    try:
        process = subprocess.run(
            [str(executable), *probe_args],
            cwd=root,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage2Error(f"runtime probe failed: {exc}") from exc
    if process.returncode != 0:
        raise Stage2Error(f"runtime probe returned nonzero exit status {process.returncode}")
    combined = process.stdout + b"\n" + process.stderr
    combined_text = combined.decode("utf-8", errors="replace")
    for value in required:
        if value not in combined_text:
            raise Stage2Error(f"runtime probe output does not contain required substring {value!r}")
    artifact_inventory = _inventory_tree(root, "runtime")
    manifest = {
        "name": name,
        "version": version,
        "build": build,
        "executable": _file_entry(root, executable_name, "runtime executable"),
        "configuration_files": config_entries,
        "artifact_inventory": artifact_inventory,
        "configuration": configuration,
        "probe": {
            "arguments": probe_args,
            "required_substrings": required,
            "exit_code": process.returncode,
            "stdout_bytes": len(process.stdout),
            "stdout_sha256": sha256_bytes(process.stdout),
            "stderr_bytes": len(process.stderr),
            "stderr_sha256": sha256_bytes(process.stderr),
            "stdout_base64": base64.b64encode(process.stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(process.stderr).decode("ascii"),
        },
    }
    return manifest, root


def _adapter_manifest(adapter: Any) -> tuple[dict[str, Any], Path | None]:
    adapter = _require_mapping(adapter, "adapter")
    _require_exact_keys(adapter, ADAPTER_FIELDS, "adapter")
    identity = _require_string(adapter["identity"], "adapter.identity")
    configuration = adapter["configuration"]
    _assert_finite_json(configuration, "adapter.configuration")
    root_value = adapter["root"]
    paths = _require_list(adapter["paths"], "adapter.paths")
    if identity == "NONE":
        if root_value is not None or paths or configuration != {}:
            raise Stage2Error("adapter NONE requires null root, no paths, and empty configuration")
        return {"identity": "NONE", "files": [], "artifact_inventory": None, "configuration": {}}, None
    root = Path(_require_string(root_value, "adapter.root")).expanduser().resolve()
    entries = _entries(root, paths, "adapter.paths")
    inventory = _inventory_tree(root, "adapter")
    return {
        "identity": identity,
        "files": entries,
        "artifact_inventory": inventory,
        "configuration": configuration,
    }, root


def _quantization_manifest(value: Any) -> dict[str, Any]:
    value = _require_mapping(value, "quantization")
    _require_exact_keys(value, QUANTIZATION_FIELDS, "quantization")
    identity = _require_string(value["identity"], "quantization.identity")
    parameters = value["parameters"]
    _assert_finite_json(parameters, "quantization.parameters")
    if identity == "NONE" and parameters != {}:
        raise Stage2Error("quantization NONE requires empty parameters")
    if identity != "NONE" and not isinstance(parameters, dict):
        raise Stage2Error("quantization parameters must be an object")
    return {"identity": identity, "parameters": parameters}


def _parse_hardware_query_bytes(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Stage2Error("hardware device query must be UTF-8") from exc
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(csv.reader(io.StringIO(text, newline="")), 1):
        if not raw or all(not item.strip() for item in raw):
            continue
        if len(raw) != 6:
            raise Stage2Error(
                f"hardware device query line {line_number} must have six CSV columns"
            )
        index_text, name, uuid, pci_bus_id, memory_text, driver = [item.strip() for item in raw]
        try:
            index = int(index_text)
            memory_mib = int(memory_text)
        except ValueError as exc:
            raise Stage2Error(f"invalid numeric hardware field on line {line_number}") from exc
        if index < 0 or memory_mib <= 0:
            raise Stage2Error("hardware index and memory must be positive-domain values")
        rows.append(
            {
                "index": index,
                "name": _require_string(name, "hardware name"),
                "uuid": _require_string(uuid, "hardware uuid"),
                "pci_bus_id": _require_string(pci_bus_id, "hardware PCI bus id"),
                "memory_mib": memory_mib,
                "driver": _require_string(driver, "hardware driver"),
            }
        )
    if not rows:
        raise Stage2Error("hardware device query contains no devices")
    if len({row["index"] for row in rows}) != len(rows):
        raise Stage2Error("hardware device query contains duplicate indices")
    return rows


def _parse_hardware_query(path: Path) -> list[dict[str, Any]]:
    return _parse_hardware_query_bytes(path.read_bytes())


def _verify_payload_hash(value: dict[str, Any], label: str) -> None:
    observed = _require_sha256(value.get("payload_sha256"), f"{label}.payload_sha256")
    expected = sha256_object(
        {key: child for key, child in value.items() if key != "payload_sha256"}
    )
    if observed != expected:
        raise Stage2Error(f"{label} payload hash mismatch")


def _validate_platform_record(value: Any, selected: list[int]) -> dict[str, Any]:
    record = _require_mapping(value, "hardware platform record")
    _require_exact_keys(record, PLATFORM_RECORD_FIELDS, "hardware platform record")
    if record.get("schema") != SCHEMA_HARDWARE_PLATFORM:
        raise Stage2Error("unexpected hardware platform schema")
    if record.get("system") not in {"Linux", "Windows"}:
        raise Stage2Error("hardware platform must be exactly Linux or Windows")
    if record.get("selected_device_indices") != selected:
        raise Stage2Error("hardware platform selected indices mismatch")
    _require_sha256(
        record.get("nvidia_smi_executable_sha256"),
        "hardware platform nvidia_smi_executable_sha256",
    )
    _verify_payload_hash(record, "hardware platform record")
    return record


def _validate_topology_evidence(
    value: Any,
    *,
    platform_record: dict[str, Any],
    query_entry: dict[str, Any],
    selected: list[int],
    selected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    record = _require_mapping(value, "hardware topology evidence")
    if record.get("schema") != SCHEMA_TOPOLOGY_EVIDENCE:
        raise Stage2Error("unexpected topology-evidence schema")
    system = platform_record["system"]
    if record.get("platform") != system:
        raise Stage2Error("topology-evidence platform does not match platform record")
    if record.get("device_query_sha256") != query_entry["sha256"]:
        raise Stage2Error("topology-evidence device-query digest mismatch")
    _require_bool(
        record.get("inter_device_topology_claimed"),
        "topology-evidence inter_device_topology_claimed",
    )
    if _require_bool(
        record.get("implicit_pooling_claimed"),
        "topology-evidence implicit_pooling_claimed",
    ):
        raise Stage2Error("topology evidence may not claim implicit pooling")
    _verify_payload_hash(record, "hardware topology evidence")

    if system == "Windows":
        _require_exact_keys(record, WINDOWS_TOPOLOGY_FIELDS, "Windows topology evidence")
        if len(selected) != 1:
            raise Stage2Error("Windows topology sentinel requires exactly one selected device")
        if record.get("state") != "NOT_APPLICABLE_SINGLE_SELECTED_DEVICE":
            raise Stage2Error("unexpected Windows topology-evidence state")
        if record.get("method") != "PLATFORM_LIMITATION_SINGLE_DEVICE":
            raise Stage2Error("unexpected Windows topology-evidence method")
        if record.get("selected_device_index") != selected[0]:
            raise Stage2Error("Windows topology-evidence selected index mismatch")
        if record.get("selected_device_query_row_sha256") != sha256_object(selected_rows[0]):
            raise Stage2Error("Windows selected device-query row digest mismatch")
        if record["inter_device_topology_claimed"]:
            raise Stage2Error("Windows single-device sentinel cannot claim inter-device topology")
        return record

    if system == "Linux":
        _require_exact_keys(record, LINUX_TOPOLOGY_FIELDS, "Linux topology evidence")
        if record.get("state") != "OBSERVED":
            raise Stage2Error("unexpected Linux topology-evidence state")
        if record.get("method") != "NVIDIA_SMI_TOPO_MATRIX":
            raise Stage2Error("unexpected Linux topology-evidence method")
        if record.get("selected_device_indices") != selected:
            raise Stage2Error("Linux topology-evidence selected indices mismatch")
        if record.get("selected_device_query_rows_sha256") != sha256_object(selected_rows):
            raise Stage2Error("Linux selected device-query rows digest mismatch")
        encoded = _require_string(record.get("matrix_stdout_base64"), "Linux matrix stdout")
        try:
            matrix = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise Stage2Error("Linux matrix stdout is not valid base64") from exc
        if not matrix.strip():
            raise Stage2Error("Linux topology matrix stdout must be nonempty")
        if record.get("matrix_stdout_sha256") != sha256_bytes(matrix):
            raise Stage2Error("Linux topology matrix stdout digest mismatch")
        if record["inter_device_topology_claimed"] != (len(selected) > 1):
            raise Stage2Error("Linux inter-device topology claim does not match selected scope")
        return record

    raise Stage2Error("unknown hardware platform")


def _hardware_manifest(hardware: Any) -> tuple[dict[str, Any], Path]:
    hardware = _require_mapping(hardware, "hardware")
    _require_exact_keys(hardware, HARDWARE_FIELDS, "hardware")
    root = Path(_require_string(hardware["evidence_root"], "hardware.evidence_root")).expanduser().resolve()
    platform_name = _relative_name(hardware["platform_path"], "hardware.platform_path")
    query_name = _relative_name(hardware["device_query_path"], "hardware.device_query_path")
    topology_name = _relative_name(
        hardware["topology_evidence_path"], "hardware.topology_evidence_path"
    )
    platform_entry = _file_entry(root, platform_name, "hardware platform evidence")
    query_entry = _file_entry(root, query_name, "hardware device query")
    topology_entry = _file_entry(root, topology_name, "hardware topology evidence")
    query_rows = _parse_hardware_query(_resolve_regular_file(root, query_name, "hardware device query"))
    selected_raw = _require_list(hardware["selected_device_indices"], "hardware.selected_device_indices")
    selected = [
        _require_int(value, f"hardware.selected_device_indices[{index}]", minimum=0)
        for index, value in enumerate(selected_raw)
    ]
    if not selected or len(set(selected)) != len(selected):
        raise Stage2Error("selected hardware indices must be a nonempty unique list")
    by_index = {row["index"]: row for row in query_rows}
    if any(index not in by_index for index in selected):
        raise Stage2Error("selected hardware index is absent from the captured query")
    if set(by_index) != set(selected) or len(query_rows) != len(selected):
        raise Stage2Error("selected hardware indices do not exactly match the captured query")
    selected_rows = [by_index[index] for index in selected]
    platform_record = _validate_platform_record(
        strict_json_load(_resolve_regular_file(root, platform_name, "hardware platform evidence")),
        selected,
    )
    topology_evidence = _validate_topology_evidence(
        strict_json_load(_resolve_regular_file(root, topology_name, "hardware topology evidence")),
        platform_record=platform_record,
        query_entry=query_entry,
        selected=selected,
        selected_rows=selected_rows,
    )
    evidence_inventory = _inventory_tree(root, "hardware evidence")
    manifest = {
        "platform": platform_entry,
        "device_query": query_entry,
        "topology_evidence_file": topology_entry,
        "topology_evidence": topology_evidence,
        "evidence_inventory": evidence_inventory,
        "selected_device_indices": selected,
        "device_count": len(selected_rows),
        "device_names": [row["name"] for row in selected_rows],
        "memory_mib": [row["memory_mib"] for row in selected_rows],
        "drivers": sorted({row["driver"] for row in selected_rows}),
        "private_device_rows": selected_rows,
    }
    return manifest, root


def _effort_mapping(value: Any) -> dict[str, Any]:
    value = _require_mapping(value, "effort_mapping")
    _require_exact_keys(value, EFFORT_MAPPING_FIELDS, "effort_mapping")
    output: dict[str, Any] = {}
    for effort in ("low", "high"):
        item = _require_mapping(value[effort], f"effort_mapping.{effort}")
        _require_exact_keys(item, EFFORT_FIELDS, f"effort_mapping.{effort}")
        arguments = _require_list(item["arguments"], f"effort_mapping.{effort}.arguments")
        environment = _require_mapping(item["environment"], f"effort_mapping.{effort}.environment")
        configuration = item["configuration"]
        args = [
            _require_string(arg, f"effort_mapping.{effort}.arguments[{index}]", nonempty=False)
            for index, arg in enumerate(arguments)
        ]
        env: dict[str, str] = {}
        for key, child in environment.items():
            key = _require_string(key, f"effort_mapping.{effort}.environment key")
            env[key] = _require_string(child, f"effort_mapping.{effort}.environment.{key}", nonempty=False)
        _assert_finite_json(configuration, f"effort_mapping.{effort}.configuration")
        if not args and not env and configuration == {}:
            raise Stage2Error(f"effort_mapping.{effort} must contain a nonzero mapping")
        output[effort] = {
            "arguments": args,
            "environment": dict(sorted(env.items())),
            "configuration": configuration,
        }
    if output["low"] == output["high"]:
        raise Stage2Error("low and high effort mappings must differ")
    return output


def _validate_top_coordinates(config: dict[str, Any]) -> None:
    if config.get("schema") != SCHEMA_BINDING_INPUT:
        raise Stage2Error("unexpected control-binding input schema")
    binding_id = _require_string(config.get("binding_id"), "binding_id")
    if not BINDING_ID_RE.fullmatch(binding_id):
        raise Stage2Error("binding_id contains unsupported characters")
    law = _require_mapping(config.get("law"), "law")
    _require_exact_keys(law, LAW_FIELDS, "law")
    if _require_sha1(law["commit_sha1"], "law.commit_sha1") != LAW_COMMIT_SHA1:
        raise Stage2Error("law commit differs from the released coordinate")
    if _require_sha1(law["tree_sha1"], "law.tree_sha1") != LAW_TREE_SHA1:
        raise Stage2Error("law tree differs from the released coordinate")
    if _require_sha1(law["blob_sha1"], "law.blob_sha1") != LAW_BLOB_SHA1:
        raise Stage2Error("law blob differs from the released coordinate")
    scaffold = _require_mapping(config.get("scaffold"), "scaffold")
    _require_exact_keys(scaffold, SCAFFOLD_FIELDS, "scaffold")
    if _require_sha1(scaffold["head_sha1"], "scaffold.head_sha1") != SCAFFOLD_HEAD_SHA1:
        raise Stage2Error("scaffold head differs from the independently audited coordinate")
    if _require_sha1(scaffold["tree_sha1"], "scaffold.tree_sha1") != SCAFFOLD_TREE_SHA1:
        raise Stage2Error("scaffold tree differs from the independently audited coordinate")
    if _require_sha1(config.get("stage1_join_head"), "stage1_join_head") != STAGE1_JOIN_HEAD_SHA1:
        raise Stage2Error("Stage 1 join differs from the frozen coordinate")
    if _require_sha256(config.get("generator_manifest_sha256"), "generator_manifest_sha256") != GENERATOR_MANIFEST_SHA256:
        raise Stage2Error("generator manifest differs from the released law")


def validate_binding_config(value: Any, *, permit_inventory_gaps: bool = False) -> dict[str, Any]:
    config = _require_mapping(value, "binding input")
    _require_exact_keys(config, BINDING_FIELDS, "binding input")
    _assert_finite_json(config)
    _validate_top_coordinates(config)
    controls = _require_list(config.get("controls"), "controls")
    if len(controls) != len(CONTROL_ORDER):
        raise Stage2Error("binding input must contain exactly three controls")
    if [item.get("role") for item in controls if isinstance(item, dict)] != list(CONTROL_ORDER):
        raise Stage2Error("controls must appear in the frozen role order")
    for index, raw_control in enumerate(controls):
        control = _require_mapping(raw_control, f"controls[{index}]")
        _require_exact_keys(control, CONTROL_FIELDS, f"controls[{index}]")
        role = _require_string(control["role"], f"controls[{index}].role")
        expected = PUBLIC_CONTROLS[role]
        for field in (
            "class_label",
            "source_repository",
            "source_commit_sha1",
            "checkpoint_repository",
            "checkpoint_revision_sha1",
        ):
            if control.get(field) != expected[field]:
                raise Stage2Error(f"{role}.{field} differs from the released law")
        _require_string(control["source_root"], f"{role}.source_root")
        _require_string(control["model_root"], f"{role}.model_root")
        if control["revision_marker_path"] is not None:
            _relative_name(control["revision_marker_path"], f"{role}.revision_marker_path")
        for field in ("model_config_paths", "tokenizer_paths", "weight_paths"):
            values = _require_list(control[field], f"{role}.{field}")
            if not permit_inventory_gaps and not values:
                raise Stage2Error(f"{role}.{field} must be populated before binding")
            for path_index, path in enumerate(values):
                _relative_name(path, f"{role}.{field}[{path_index}]")
        if control["weight_index_path"] is not None:
            _relative_name(control["weight_index_path"], f"{role}.weight_index_path")
        runtime = _require_mapping(control["runtime"], f"{role}.runtime")
        _require_exact_keys(runtime, RUNTIME_FIELDS, f"{role}.runtime")
        adapter = _require_mapping(control["adapter"], f"{role}.adapter")
        _require_exact_keys(adapter, ADAPTER_FIELDS, f"{role}.adapter")
        quantization = _require_mapping(control["quantization"], f"{role}.quantization")
        _require_exact_keys(quantization, QUANTIZATION_FIELDS, f"{role}.quantization")
        hardware = _require_mapping(control["hardware"], f"{role}.hardware")
        _require_exact_keys(hardware, HARDWARE_FIELDS, f"{role}.hardware")
        effort = _require_mapping(control["effort_mapping"], f"{role}.effort_mapping")
        _require_exact_keys(effort, EFFORT_MAPPING_FIELDS, f"{role}.effort_mapping")
    return config


def inventory_binding_config(config: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(validate_binding_config(config, permit_inventory_gaps=True))
    for control in config["controls"]:
        root = Path(control["model_root"]).expanduser().resolve()
        if not root.is_dir():
            raise Stage2Error(f"model root is not a directory for {control['role']}")
        if not control["model_config_paths"]:
            control["model_config_paths"] = [
                name for name in DEFAULT_MODEL_CONFIG_NAMES if (root / name).is_file()
            ]
        if not control["tokenizer_paths"]:
            discovered = [name for name in DEFAULT_TOKENIZER_NAMES if (root / name).is_file()]
            discovered.extend(
                path.name
                for path in sorted(root.iterdir())
                if path.is_file()
                and path.name.startswith(("vocab.", "tokenizer."))
                and path.name not in discovered
            )
            control["tokenizer_paths"] = sorted(set(discovered))
        if control["weight_index_path"] is None:
            candidates = [name for name in DEFAULT_WEIGHT_INDEX_NAMES if (root / name).is_file()]
            if len(candidates) > 1:
                raise Stage2Error(f"multiple weight indexes found for {control['role']}")
            if candidates:
                control["weight_index_path"] = candidates[0]
        if not control["weight_paths"]:
            if control["weight_index_path"] is not None:
                index = strict_json_load(root / control["weight_index_path"])
                if not isinstance(index, dict) or not isinstance(index.get("weight_map"), dict):
                    raise Stage2Error("discovered weight index lacks weight_map")
                control["weight_paths"] = sorted(set(index["weight_map"].values()))
            else:
                control["weight_paths"] = sorted(
                    path.name
                    for path in root.iterdir()
                    if path.is_file()
                    and path.suffix.lower() in DEFAULT_WEIGHT_SUFFIXES
                    and not path.name.startswith(("optimizer", "training_args"))
                )
    return validate_binding_config(config)


def _component_file_keys(private_control: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    inventories: list[tuple[str, dict[str, Any] | None]] = [
        ("source", {"files": private_control["source"]["files"]}),
        ("checkpoint", private_control["checkpoint"]["artifact_inventory"]),
        ("runtime", private_control["runtime"]["artifact_inventory"]),
        ("adapter", private_control["adapter"]["artifact_inventory"]),
        ("hardware", private_control["hardware"]["evidence_inventory"]),
    ]
    for category, inventory in inventories:
        if inventory is None:
            continue
        for item in inventory["files"]:
            entries.append(
                {
                    "category": category,
                    "name": item["name"],
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                }
            )
    return sorted(entries, key=lambda item: (item["category"], item["name"]))


def _bind_one(control: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    role = control["role"]
    expected = PUBLIC_CONTROLS[role]
    source_root = Path(control["source_root"]).expanduser().resolve()
    model_root = Path(control["model_root"]).expanduser().resolve()
    if not model_root.is_dir():
        raise Stage2Error(f"model root is not a directory for {role}")
    source = _tracked_source_manifest(
        source_root, expected["source_repository"], expected["source_commit_sha1"]
    )
    revision_evidence = _checkpoint_revision_evidence(
        model_root, expected["checkpoint_revision_sha1"], control["revision_marker_path"]
    )
    checkpoint_inventory = _inventory_tree(model_root, f"{role} checkpoint")
    model_entries = _entries(model_root, control["model_config_paths"], f"{role}.model_config_paths")
    tokenizer_entries = _entries(model_root, control["tokenizer_paths"], f"{role}.tokenizer_paths")
    weight_entries = _entries(model_root, control["weight_paths"], f"{role}.weight_paths")
    weight_index = _validate_weight_index(model_root, control["weight_index_path"], weight_entries)
    runtime, runtime_root = _runtime_manifest(control["runtime"])
    adapter, adapter_root = _adapter_manifest(control["adapter"])
    quantization = _quantization_manifest(control["quantization"])
    hardware, hardware_root = _hardware_manifest(control["hardware"])
    effort = _effort_mapping(control["effort_mapping"])

    private_roots = {
        "source_root": str(source_root),
        "model_root": str(model_root),
        "runtime_root": str(runtime_root),
        "adapter_root": None if adapter_root is None else str(adapter_root),
        "hardware_evidence_root": str(hardware_root),
    }
    locator_sha256 = sha256_object(private_roots)

    checkpoint = {
        "repository": expected["checkpoint_repository"],
        "revision_sha1": expected["checkpoint_revision_sha1"],
        "revision_evidence": revision_evidence,
        "artifact_inventory": checkpoint_inventory,
    }
    model = {"configuration_files": model_entries}
    tokenizer = {"files": tokenizer_entries}
    weights = {"index": weight_index, "files": weight_entries}

    model_revision_sha256 = sha256_object(
        {
            "checkpoint": checkpoint,
            "source_tree_sha1": source["tree_sha1"],
            "source_content_manifest_sha256": source["content_manifest_sha256"],
            "model_configuration_files": model_entries,
            "quantization": quantization,
        }
    )
    weights_sha256 = sha256_object(weights)
    tokenizer_sha256 = sha256_object(tokenizer)
    runtime_sha256 = sha256_object(
        {
            "name": runtime["name"],
            "version": runtime["version"],
            "build": runtime["build"],
            "executable": runtime["executable"],
            "configuration_files": runtime["configuration_files"],
            "artifact_inventory": runtime["artifact_inventory"],
            "configuration": runtime["configuration"],
            "probe": {
                key: value
                for key, value in runtime["probe"].items()
                if key not in {"stdout_base64", "stderr_base64"}
            },
            "effort_mapping": effort,
        }
    )
    adapter_sha256 = sha256_object(adapter)
    hardware_sha256 = sha256_object(hardware)

    private_control: dict[str, Any] = {
        "schema": SCHEMA_PRIVATE_CONTROL,
        "evidence_class": "empirical_local",
        "binding_status": "BOUND_EXECUTABLE_IDENTITY",
        "role": role,
        "class_label": expected["class_label"],
        "public_source": {
            "repository": expected["source_repository"],
            "commit_sha1": expected["source_commit_sha1"],
        },
        "checkpoint": checkpoint,
        "source": source,
        "model": model,
        "tokenizer": tokenizer,
        "weights": weights,
        "runtime": runtime,
        "adapter": adapter,
        "quantization": quantization,
        "hardware": hardware,
        "effort_mapping": effort,
        "private_locator": private_roots,
        "private_locator_sha256": locator_sha256,
        "component_digests": {
            "model_revision_sha256": model_revision_sha256,
            "weights_sha256": weights_sha256,
            "tokenizer_sha256": tokenizer_sha256,
            "runtime_sha256": runtime_sha256,
            "adapter_sha256": adapter_sha256,
            "hardware_sha256": hardware_sha256,
        },
    }
    file_entries = _component_file_keys(private_control)
    private_control["local_artifact_set"] = {
        "file_count": len(file_entries),
        "total_bytes": sum(item["bytes"] for item in file_entries),
        "files_sha256": sha256_object(file_entries),
        "files": file_entries,
    }
    private_control["local_artifact_set_sha256"] = sha256_object(
        {
            "role": role,
            "checkpoint": checkpoint,
            "component_digests": private_control["component_digests"],
            "quantization": quantization,
            "effort_mapping": effort,
            "file_manifest": file_entries,
        }
    )
    private_control["private_manifest_sha256"] = sha256_object(private_control)

    public_control: dict[str, Any] = {
        "schema": SCHEMA_PUBLIC_CONTROL,
        "evidence_class": "empirical_local",
        "binding_status": "BOUND_EXECUTABLE_IDENTITY",
        "role": role,
        "class_label": expected["class_label"],
        "source_repository": expected["source_repository"],
        "source_commit_sha1": expected["source_commit_sha1"],
        "checkpoint_repository": expected["checkpoint_repository"],
        "checkpoint_revision_sha1": expected["checkpoint_revision_sha1"],
        "component_digests": copy.deepcopy(private_control["component_digests"]),
        "hardware_topology": {
            "schema": SCHEMA_TOPOLOGY_EVIDENCE,
            "state": hardware["topology_evidence"]["state"],
            "platform": hardware["topology_evidence"]["platform"],
            "method": hardware["topology_evidence"]["method"],
            "selected_device_count": hardware["device_count"],
            "inter_device_topology_claimed": hardware["topology_evidence"][
                "inter_device_topology_claimed"
            ],
            "implicit_pooling_claimed": hardware["topology_evidence"][
                "implicit_pooling_claimed"
            ],
            "topology_evidence_sha256": hardware["topology_evidence_file"]["sha256"],
        },
        "local_artifact_set_sha256": private_control["local_artifact_set_sha256"],
        "private_manifest_sha256": private_control["private_manifest_sha256"],
        "private_locator_sha256": locator_sha256,
        "file_count": private_control["local_artifact_set"]["file_count"],
        "total_bytes": private_control["local_artifact_set"]["total_bytes"],
    }
    public_control["public_receipt_sha256"] = sha256_object(public_control)
    return private_control, public_control, private_control["component_digests"]


def _assert_public_safe(value: Any, private_roots: Iterable[str], path: str = "$") -> None:
    roots = [root.replace("\\", "/").rstrip("/") for root in private_roots if root]
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_PUBLIC_KEYS:
                raise Stage2Error(f"public receipt contains forbidden key at {path}.{key}")
            _assert_public_safe(child, roots, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_public_safe(child, roots, f"{path}[{index}]")
    elif isinstance(value, str):
        normalised = value.replace("\\", "/")
        for root in roots:
            if root and root in normalised:
                raise Stage2Error(f"public receipt leaks a private root at {path}")


def bind_control_set(config: dict[str, Any], *, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    config = validate_binding_config(config)
    repo_coordinates = verify_repository_coordinates(repo_root)
    generator = build_generator_manifest()
    if generator["payload_sha256"] != config["generator_manifest_sha256"]:
        raise Stage2Error("binding input generator digest differs from the reconstructed generator")

    private_controls: list[dict[str, Any]] = []
    public_controls: list[dict[str, Any]] = []
    component_digests: dict[str, dict[str, str]] = {}
    private_roots: list[str] = []
    for control in config["controls"]:
        private_control, public_control, digests = _bind_one(control)
        private_controls.append(private_control)
        public_controls.append(public_control)
        component_digests[control["role"]] = digests
        private_roots.extend(
            value for value in private_control["private_locator"].values() if isinstance(value, str)
        )

    control_template = empirical_control_template()
    for control in control_template["controls"]:
        for field, digest in component_digests[control["control_id"]].items():
            control["identity"][field] = digest
    bound_control_manifest = bind_empirical_control_manifest(control_template)
    plan = build_calibration_plan(generator, bound_control_manifest)
    validate_plan(plan, generator, bound_control_manifest)
    if plan.get("observation_count") != 648:
        raise Stage2Error("bound control plan does not contain the complete 648-row denominator")

    private_set: dict[str, Any] = {
        "schema": SCHEMA_PRIVATE_SET,
        "binding_id": config["binding_id"],
        "repository": {
            "head_sha1": repo_coordinates["head_sha1"],
            "tree_sha1": repo_coordinates["tree_sha1"],
        },
        "law": {
            "commit_sha1": LAW_COMMIT_SHA1,
            "tree_sha1": LAW_TREE_SHA1,
            "blob_sha1": LAW_BLOB_SHA1,
        },
        "scaffold": {
            "head_sha1": SCAFFOLD_HEAD_SHA1,
            "tree_sha1": SCAFFOLD_TREE_SHA1,
        },
        "stage1_join_head": STAGE1_JOIN_HEAD_SHA1,
        "generator_manifest_sha256": generator["payload_sha256"],
        "control_manifest_sha256": bound_control_manifest["payload_sha256"],
        "calibration_plan_sha256": plan["payload_sha256"],
        "controls": private_controls,
        "private_manifest_set_sha256": sha256_object(
            [item["private_manifest_sha256"] for item in private_controls]
        ),
    }
    private_set["private_set_receipt_sha256"] = sha256_object(private_set)

    public_set: dict[str, Any] = {
        "schema": SCHEMA_CONTROL_SET,
        "binding_id": config["binding_id"],
        "binding_status": "BOUND_EXECUTABLE_IDENTITIES",
        "repository_head_sha1": repo_coordinates["head_sha1"],
        "repository_tree_sha1": repo_coordinates["tree_sha1"],
        "law_commit_sha1": LAW_COMMIT_SHA1,
        "law_tree_sha1": LAW_TREE_SHA1,
        "law_blob_sha1": LAW_BLOB_SHA1,
        "scaffold_head_sha1": SCAFFOLD_HEAD_SHA1,
        "scaffold_tree_sha1": SCAFFOLD_TREE_SHA1,
        "stage1_join_head_sha1": STAGE1_JOIN_HEAD_SHA1,
        "generator_manifest_sha256": generator["payload_sha256"],
        "control_manifest_sha256": bound_control_manifest["payload_sha256"],
        "calibration_plan_sha256": plan["payload_sha256"],
        "control_count": len(public_controls),
        "observation_count": plan["observation_count"],
        "controls": public_controls,
        "private_set_receipt_sha256": private_set["private_set_receipt_sha256"],
        "provider_or_model_calls": 0,
        "empirical_observations": 0,
        "numeric_stage2_freeze": "NOT_ISSUED",
        "callable_astra_identity": "UNBOUND",
        "live_provider_dispatch": "PROHIBITED",
        "optional_24_call_block": "DISABLED",
    }
    public_set["public_set_receipt_sha256"] = sha256_object(public_set)
    _assert_public_safe(public_controls, private_roots)
    _assert_public_safe(public_set, private_roots)

    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise Stage2Error("output directory must be absent or empty")
    private_dir = output_dir / "private"
    public_dir = output_dir / "public"
    private_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    for item in private_controls:
        write_json_atomic(private_dir / f"{item['role']}.json", item)
    for item in public_controls:
        write_json_atomic(public_dir / f"{item['role']}.json", item)
    write_json_atomic(private_dir / "control-set-private.json", private_set)
    write_json_atomic(public_dir / "control-set-public.json", public_set)
    write_json_atomic(output_dir / "control-manifest.json", bound_control_manifest)
    write_json_atomic(output_dir / "calibration-plan.json", plan)
    write_json_atomic(output_dir / "generator-manifest.json", generator)

    sums: list[str] = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        sums.append(f"{sha256_file(path)}  {relative}")
    (output_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    return public_set


def verify_control_set(
    config: dict[str, Any],
    *,
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    expected = strict_json_load(output_dir / "public" / "control-set-public.json")
    with tempfile.TemporaryDirectory(prefix="astra-stage2-control-verify-") as temporary:
        observed = bind_control_set(
            config,
            repo_root=repo_root,
            output_dir=Path(temporary) / "recomputed",
        )
    if observed != expected:
        raise Stage2Error("bound control set does not reproduce from the current private evidence")
    return observed


def _run_nvidia_command(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        raise Stage2Error(f"unable to execute nvidia-smi command: {exc}") from exc


def probe_hardware(
    *,
    output_dir: Path,
    nvidia_smi: str | None = None,
    device_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise Stage2Error("hardware probe output directory must be absent or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = nvidia_smi or shutil.which("nvidia-smi")
    if not executable:
        raise Stage2Error("nvidia-smi was not found; pass --nvidia-smi explicitly")
    indices = list(device_indices or [])
    if not indices:
        raise Stage2Error("at least one selected device index is required")
    if any(
        isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in indices
    ) or len(set(indices)) != len(indices):
        raise Stage2Error("device indices must be unique nonnegative integers")
    selector = ["-i", ",".join(str(index) for index in indices)]
    query_command = [
        executable,
        *selector,
        "--query-gpu=index,name,uuid,pci.bus_id,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    query = _run_nvidia_command(query_command)
    if query.returncode != 0:
        raise Stage2Error(f"nvidia-smi device query failed with exit {query.returncode}")
    query_rows = _parse_hardware_query_bytes(query.stdout)
    by_index = {row["index"]: row for row in query_rows}
    if set(by_index) != set(indices) or len(query_rows) != len(indices):
        raise Stage2Error("selected device indices do not exactly match the device query")
    selected_rows = [by_index[index] for index in indices]
    system = platform.system()
    if system not in {"Linux", "Windows"}:
        raise Stage2Error(f"unsupported hardware platform: {system!r}")
    if system == "Windows" and len(indices) != 1:
        raise Stage2Error(
            "Windows multi-device binding requires an independently qualified topology source"
        )

    if system == "Linux":
        topology_command = [executable, "topo", "-m"]
        topology = _run_nvidia_command(topology_command)
        if topology.returncode != 0:
            raise Stage2Error(f"nvidia-smi topology query failed with exit {topology.returncode}")
        if not topology.stdout.strip():
            raise Stage2Error("nvidia-smi topology query returned empty stdout")
        topology_record: dict[str, Any] = {
            "schema": SCHEMA_TOPOLOGY_EVIDENCE,
            "state": "OBSERVED",
            "platform": "Linux",
            "method": "NVIDIA_SMI_TOPO_MATRIX",
            "selected_device_indices": indices,
            "selected_device_query_rows_sha256": sha256_object(selected_rows),
            "device_query_sha256": sha256_bytes(query.stdout),
            "matrix_stdout_base64": base64.b64encode(topology.stdout).decode("ascii"),
            "matrix_stdout_sha256": sha256_bytes(topology.stdout),
            "inter_device_topology_claimed": len(indices) > 1,
            "implicit_pooling_claimed": False,
        }
    else:
        topology_record = {
            "schema": SCHEMA_TOPOLOGY_EVIDENCE,
            "state": "NOT_APPLICABLE_SINGLE_SELECTED_DEVICE",
            "platform": "Windows",
            "method": "PLATFORM_LIMITATION_SINGLE_DEVICE",
            "selected_device_index": indices[0],
            "selected_device_query_row_sha256": sha256_object(selected_rows[0]),
            "device_query_sha256": sha256_bytes(query.stdout),
            "inter_device_topology_claimed": False,
            "implicit_pooling_claimed": False,
        }
    topology_record["payload_sha256"] = sha256_object(topology_record)
    platform_record = {
        "schema": SCHEMA_HARDWARE_PLATFORM,
        "system": system,
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "selected_device_indices": indices,
        "nvidia_smi_executable_sha256": sha256_file(Path(executable).resolve()),
    }
    platform_record["payload_sha256"] = sha256_object(platform_record)
    write_json_atomic(output_dir / "platform.json", platform_record)
    (output_dir / "nvidia-query.csv").write_bytes(query.stdout)
    write_json_atomic(output_dir / "nvidia-topology.json", topology_record)
    receipt = {
        "schema": SCHEMA_HARDWARE_PROBE,
        "platform_sha256": sha256_file(output_dir / "platform.json"),
        "device_query_sha256": sha256_file(output_dir / "nvidia-query.csv"),
        "topology_evidence_sha256": sha256_file(output_dir / "nvidia-topology.json"),
        "selected_device_indices": indices,
    }
    receipt["payload_sha256"] = sha256_object(receipt)
    write_json_atomic(output_dir / "probe-receipt.json", receipt)
    return receipt


def binding_template() -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    for role in CONTROL_ORDER:
        public = PUBLIC_CONTROLS[role]
        controls.append(
            {
                "role": role,
                "class_label": public["class_label"],
                "source_repository": public["source_repository"],
                "source_commit_sha1": public["source_commit_sha1"],
                "source_root": f"C:/REPLACE/source/{role}",
                "checkpoint_repository": public["checkpoint_repository"],
                "checkpoint_revision_sha1": public["checkpoint_revision_sha1"],
                "model_root": f"C:/REPLACE/models/{public['checkpoint_revision_sha1']}",
                "revision_marker_path": None,
                "model_config_paths": [],
                "tokenizer_paths": [],
                "weight_index_path": None,
                "weight_paths": [],
                "runtime": {
                    "root": "C:/REPLACE/runtime",
                    "name": "REPLACE",
                    "version": "REPLACE",
                    "build": "REPLACE",
                    "executable_path": "REPLACE.exe",
                    "configuration_paths": [],
                    "configuration": {"deterministic": True},
                    "probe_args": ["--version"],
                    "required_probe_substrings": ["REPLACE"],
                    "probe_timeout_seconds": 30,
                },
                "adapter": {
                    "identity": "NONE",
                    "root": None,
                    "paths": [],
                    "configuration": {},
                },
                "quantization": {"identity": "NONE", "parameters": {}},
                "hardware": {
                    "evidence_root": "C:/REPLACE/hardware",
                    "platform_path": "platform.json",
                    "device_query_path": "nvidia-query.csv",
                    "topology_evidence_path": "nvidia-topology.json",
                    "selected_device_indices": [0],
                },
                "effort_mapping": {
                    "low": {
                        "arguments": ["--effort", "low"],
                        "environment": {},
                        "configuration": {},
                    },
                    "high": {
                        "arguments": ["--effort", "high"],
                        "environment": {},
                        "configuration": {},
                    },
                },
            }
        )
    return {
        "schema": SCHEMA_BINDING_INPUT,
        "binding_id": "astra-stage2-controls-REPLACE",
        "law": {
            "commit_sha1": LAW_COMMIT_SHA1,
            "tree_sha1": LAW_TREE_SHA1,
            "blob_sha1": LAW_BLOB_SHA1,
        },
        "scaffold": {
            "head_sha1": SCAFFOLD_HEAD_SHA1,
            "tree_sha1": SCAFFOLD_TREE_SHA1,
        },
        "stage1_join_head": STAGE1_JOIN_HEAD_SHA1,
        "generator_manifest_sha256": GENERATOR_MANIFEST_SHA256,
        "controls": controls,
    }
