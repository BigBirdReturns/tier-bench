from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from .adapters.claude_code import (
    _claude_command,
    _help_surface_bytes,
    _runtime_model,
    _subscription_env,
    _usage,
    _usage_evidenced,
)
from .pilot_activation import PilotActivation, PROVIDER_RESULT_SCHEMA
from .pilot_composition import canonical_json


class PilotAdapterError(RuntimeError):
    pass


DISPATCH_FIELDS = {
    "schema", "call_id", "task_id", "arm", "stage", "attempt", "backend",
    "prompt_template", "prompt_sha256", "base_commit", "task_sha256", "files",
    "acceptance_sha256", "composition_manifest_sha256",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotAdapterError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PilotAdapterError(f"{label} must be an object")
    return value, raw


def _pilot_output(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("result")
    if not isinstance(raw, str) or not raw:
        raise PilotAdapterError("provider result must contain a non-empty result string")
    try:
        output = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PilotAdapterError("provider result is not a bare pilot-output JSON object") from exc
    if not isinstance(output, dict) or set(output) != {"outcome", "text"}:
        raise PilotAdapterError("pilot output must contain exactly outcome and text")
    if output.get("outcome") not in {"completed", "question", "error"}:
        raise PilotAdapterError("pilot output outcome is invalid")
    if not isinstance(output.get("text"), str) or not output["text"]:
        raise PilotAdapterError("pilot output text must be non-empty")
    if raw != json.dumps(output, sort_keys=True, separators=(",", ":")):
        raise PilotAdapterError("pilot output must be canonical bare JSON")
    return {"outcome": output["outcome"], "text": output["text"]}


def _stage_bindings(
    activation: PilotActivation, arm_name: str, stage: str, attempt: int
) -> set[tuple[str, str]]:
    if arm_name not in activation.composition.arms:
        raise PilotAdapterError("pilot dispatch arm is not activated")
    arm = activation.composition.arms[arm_name]
    if stage == "driver_plan" and arm.driver is not None:
        return {(arm.driver.backend, arm.driver.prompt_template)}
    if stage == "hands":
        return {(arm.hands.backend, arm.hands.prompt_template)}
    if stage == "repair":
        return {(arm.repair.backend, arm.repair.prompt_template)}
    if stage == "escalation":
        index = attempt - 1
        if index < 0 or index >= len(arm.escalations):
            return set()
        item = arm.escalations[index]
        return {(item.backend, item.prompt_template)}
    if stage == "hands_resume" and arm.question_route is not None:
        return {(arm.hands.backend, arm.question_route.resume_prompt_template)}
    return set()


def run_activated_adapter(
    activation: PilotActivation,
    *,
    backend_name: str,
    dispatch_path: Path,
    prompt_path: Path,
    result_path: Path,
    worktree: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    environment: dict[str, str] | None = None,
) -> int:
    """Run one activated provider call; callers still need separate execution authority."""
    if backend_name not in activation.composition.backends:
        raise PilotAdapterError(f"activation has no backend {backend_name!r}")
    backend = activation.composition.backends[backend_name]
    dispatch, dispatch_raw = _object(dispatch_path, "pilot dispatch")
    if set(dispatch) != DISPATCH_FIELDS:
        raise PilotAdapterError("pilot dispatch fields do not match the production contract")
    if dispatch.get("schema") != "tier-bench/tier-pilot-dispatch-receipt@1":
        raise PilotAdapterError("pilot dispatch schema is not production")
    for field in ("call_id", "task_id", "arm", "stage", "backend"):
        if not isinstance(dispatch.get(field), str) or not dispatch[field]:
            raise PilotAdapterError(f"pilot dispatch {field} must be non-empty")
    if not isinstance(dispatch.get("attempt"), int) or isinstance(
        dispatch["attempt"], bool
    ) or dispatch["attempt"] < 1:
        raise PilotAdapterError("pilot dispatch attempt must be a positive integer")
    if not GIT_SHA.fullmatch(str(dispatch.get("base_commit", ""))):
        raise PilotAdapterError("pilot dispatch base_commit must be a full Git SHA")
    for field in (
        "prompt_sha256", "task_sha256", "acceptance_sha256",
        "composition_manifest_sha256",
    ):
        if not SHA256.fullmatch(str(dispatch.get(field, ""))):
            raise PilotAdapterError(f"pilot dispatch {field} must be a SHA-256")
    if not isinstance(dispatch.get("files"), list) or not dispatch["files"] or not all(
        isinstance(item, str) and item for item in dispatch["files"]
    ):
        raise PilotAdapterError("pilot dispatch files must be a non-empty string array")
    if not isinstance(dispatch.get("prompt_template"), dict) or set(
        dispatch["prompt_template"]
    ) != {"name", "sha256"}:
        raise PilotAdapterError("pilot dispatch prompt_template fields are invalid")
    if dispatch.get("backend") != backend_name:
        raise PilotAdapterError("pilot dispatch backend differs from activated backend")
    if dispatch.get("composition_manifest_sha256") != activation.composition.sha256:
        raise PilotAdapterError("pilot dispatch composition identity drifted")
    template_name = dispatch["prompt_template"].get("name")
    if template_name not in activation.composition.templates:
        raise PilotAdapterError("pilot dispatch prompt template is not activated")
    template = activation.composition.templates[template_name]
    if dispatch["prompt_template"] != {"name": template_name, "sha256": template.sha256}:
        raise PilotAdapterError("pilot dispatch prompt-template identity drifted")
    if (backend_name, template_name) not in _stage_bindings(
        activation, dispatch["arm"], dispatch["stage"], dispatch["attempt"]
    ):
        raise PilotAdapterError("pilot dispatch backend/template is invalid for its arm stage")
    prompt_raw = prompt_path.read_bytes()
    if _sha(prompt_raw) != dispatch.get("prompt_sha256"):
        raise PilotAdapterError("exact rendered prompt bytes differ from dispatch")
    try:
        prompt_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PilotAdapterError("pilot prompt must be UTF-8") from exc
    if result_path.exists():
        raise PilotAdapterError("pilot provider result path already exists")

    binary = activation.adapter["binary"]
    version = runner([binary, "--version"], capture_output=True, text=False)
    if version.returncode:
        raise PilotAdapterError("cannot read activated provider CLI version")
    actual_version = version.stdout.decode(errors="replace").strip()
    if actual_version != activation.adapter["cli_version"]:
        raise PilotAdapterError("activated provider CLI version drifted")
    help_result = runner([binary, "--help"], capture_output=True, text=False)
    if help_result.returncode:
        raise PilotAdapterError("cannot read activated provider CLI help surface")
    if _help_surface_bytes(help_result.stdout) != activation.adapter["help_sha256"]:
        raise PilotAdapterError("activated provider CLI help surface drifted")

    command = _claude_command(
        binary, backend.model_id, backend.effort, worktree, dispatch["files"]
    )
    child_env = _subscription_env(dict(os.environ) if environment is None else environment)
    started = time.monotonic()
    process = runner(
        command,
        cwd=worktree,
        input=prompt_raw,
        capture_output=True,
        text=False,
        env=child_env,
    )
    latency_ms = (time.monotonic() - started) * 1000
    stdout = process.stdout or b""
    stderr = process.stderr or b""
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise PilotAdapterError("provider runner did not preserve raw byte streams")
    raw_path = result_path.with_name("provider.raw.bin")
    stderr_path = result_path.with_name("provider.stderr.bin")
    raw_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    try:
        data = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotAdapterError("provider stdout is not one UTF-8 JSON object") from exc
    if not isinstance(data, dict):
        raise PilotAdapterError("provider stdout must be an object")
    output = _pilot_output(data)
    if (process.returncode != 0 or data.get("is_error") is True) and output["outcome"] != "error":
        raise PilotAdapterError("provider process failure was mislabeled as a completed output")
    usage = _usage(data)
    runtime_model, runtime_model_evidenced = _runtime_model(data, backend.model_id)
    session_id = data.get("session_id")
    telemetry_complete = bool(
        isinstance(session_id, str)
        and session_id
        and runtime_model_evidenced
        and _usage_evidenced(data)
    )
    if not telemetry_complete:
        raise PilotAdapterError("provider telemetry is incomplete")
    ledger_outcome = (
        "error" if output["outcome"] == "error"
        else "partial" if output["outcome"] == "question"
        else "pass"
    )
    call = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": backend.account,
        "model": backend.model_id,
        "tier": backend.tier,
        "task_id": dispatch["task_id"],
        "phase": dispatch["arm"],
        "outcome": ledger_outcome,
        "effort": backend.effort,
        **usage,
        "cost_usd": float(data.get("total_cost_usd", 0) or 0),
        "latency_ms": latency_ms,
        "trial": dispatch["attempt"],
        "note": f"{backend.cost_basis}; provider_rc={process.returncode}",
        "extra": {
            "activation_commit": activation.commit,
            "activation_sha256": activation.sha256,
            "backend_manifest_sha256": activation.composition.sha256,
            "backend_surface": backend.surface,
            "cost_basis": backend.cost_basis,
            "dispatch_receipt_sha256": _sha(dispatch_raw),
            "prompt_template_sha256": template.sha256,
            "rendered_prompt_sha256": _sha(prompt_raw),
            "runtime_model_id": runtime_model,
            "session_id": session_id,
            "telemetry_complete": True,
            # The arm-state and ADMIN validators bind this field to the frozen
            # composition exactly. Adapter/CLI identities are independently
            # activation-bound above and must not silently widen this mapping.
            "tool_versions": activation.composition.tool_versions,
            "raw_result_sha256": _sha(stdout),
            "stderr_sha256": _sha(stderr),
        },
    }
    result = {
        "schema": PROVIDER_RESULT_SCHEMA,
        "calls": [call],
        "pilot_output": output,
        "artifacts": [
            {"name": "provider_raw", "path": raw_path.name, "sha256": _sha(stdout)},
            {"name": "provider_stderr", "path": stderr_path.name, "sha256": _sha(stderr)},
        ],
    }
    result_path.write_bytes(canonical_json(result))
    return process.returncode
