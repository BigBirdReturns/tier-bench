"""Adapter execution boundary for semantic events.

Synthetic adapters make the contract executable in CI without pretending that
hardware or sibling repositories were exercised. Command adapters are the real
integration seam: a manifest-owned argv receives one JSON request and must emit
one bounded response whose semantic digest matches the request.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .canonical import load_json, sha256_hex, stable_id, write_json
from .errors import EstateLabError
from .model import AdapterSpec


class AdapterRefused(EstateLabError):
    """An adapter refused or malformed a semantic event."""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


def semantic_projection(event: dict[str, Any]) -> dict[str, Any]:
    """Return the route-independent semantic portion an adapter may not alter."""

    return {
        "semantic_id": event["semantic_id"],
        "subject": event["subject"],
        "operation": event["operation"],
        "state_path": event["state_path"],
        "value": event.get("value"),
        "authority": event["authority"],
    }


def _synthetic_response(
    adapter: AdapterSpec,
    *,
    phase: str,
    event: dict[str, Any],
    fault: str | None,
) -> dict[str, Any]:
    projection = semantic_projection(event)
    if fault == "adapter_semantic_mutation":
        projection = dict(projection)
        projection["value"] = {"mutated": True}
    accepted = fault != "target_refusal"
    response = {
        "format": "axm-adapter-response/1",
        "adapter_id": adapter.adapter_id,
        "phase": phase,
        "accepted": accepted,
        "reason": "injected_target_refusal" if not accepted else None,
        "semantic_digest": sha256_hex(projection),
        "observations": {
            "mode": "synthetic",
            "kind": adapter.kind,
            "evidence_class": adapter.evidence_class,
            "local_only": adapter.local_only,
            "deterministic": adapter.deterministic,
            "replayable": adapter.replayable,
        },
    }
    response["response_id"] = stable_id("adapter1", response, 32)
    return response


def _command_response(
    adapter: AdapterSpec,
    *,
    phase: str,
    event: dict[str, Any],
    repository: Path,
) -> dict[str, Any]:
    if not adapter.command:
        raise AdapterRefused("adapter_command_missing", {"adapter_id": adapter.adapter_id})

    with tempfile.TemporaryDirectory(prefix="axm-estate-adapter-") as temp_dir:
        temp = Path(temp_dir)
        request_path = temp / "request.json"
        response_path = temp / "response.json"
        request = {
            "format": "axm-adapter-request/1",
            "adapter_id": adapter.adapter_id,
            "phase": phase,
            "event": event,
            "semantic_digest": sha256_hex(semantic_projection(event)),
        }
        write_json(request_path, request)

        argv: list[str] = []
        saw_request = False
        saw_response = False
        for token in adapter.command:
            if "{request}" in token:
                saw_request = True
            if "{response}" in token:
                saw_response = True
            argv.append(
                token.replace("{repo}", str(repository))
                .replace("{request}", str(request_path))
                .replace("{response}", str(response_path))
            )
        if not saw_request:
            argv.append(str(request_path))

        executable = argv[0]
        if not os.path.isabs(executable) and shutil.which(executable) is None:
            raise AdapterRefused(
                "adapter_executable_missing",
                {"adapter_id": adapter.adapter_id, "executable": executable},
            )

        try:
            completed = subprocess.run(
                argv,
                cwd=repository,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=adapter.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterRefused(
                "adapter_timeout",
                {"adapter_id": adapter.adapter_id, "timeout_seconds": adapter.timeout_seconds},
            ) from exc

        if completed.returncode != 0:
            raise AdapterRefused(
                "adapter_nonzero_exit",
                {
                    "adapter_id": adapter.adapter_id,
                    "exit_code": completed.returncode,
                    "stdout_sha256": sha256_hex(completed.stdout.encode("utf-8")),
                    "stderr_sha256": sha256_hex(completed.stderr.encode("utf-8")),
                },
            )

        try:
            if saw_response:
                if not response_path.is_file():
                    raise AdapterRefused(
                        "adapter_response_missing",
                        {"adapter_id": adapter.adapter_id, "path": str(response_path)},
                    )
                response = load_json(response_path)
            else:
                response = json.loads(completed.stdout)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise AdapterRefused(
                "adapter_response_malformed",
                {"adapter_id": adapter.adapter_id},
            ) from exc

        if not isinstance(response, dict):
            raise AdapterRefused("adapter_response_not_object", {"adapter_id": adapter.adapter_id})
        response.setdefault("format", "axm-adapter-response/1")
        response.setdefault("adapter_id", adapter.adapter_id)
        response.setdefault("phase", phase)
        response.setdefault("response_id", stable_id("adapter1", response, 32))
        return response


def execute_adapter(
    adapter: AdapterSpec,
    *,
    phase: str,
    event: dict[str, Any],
    repository: Path | None,
    execution_mode: str,
    fault: str | None = None,
) -> dict[str, Any]:
    """Execute one adapter and enforce semantic non-mutation."""

    if execution_mode == "synthetic" or adapter.mode == "synthetic":
        response = _synthetic_response(adapter, phase=phase, event=event, fault=fault)
    elif adapter.mode == "command":
        if repository is None:
            raise AdapterRefused(
                "adapter_repository_missing",
                {"adapter_id": adapter.adapter_id, "organ_id": adapter.organ_id},
            )
        response = _command_response(adapter, phase=phase, event=event, repository=repository)
    elif adapter.mode == "artifact":
        if repository is None:
            raise AdapterRefused(
                "adapter_repository_missing",
                {"adapter_id": adapter.adapter_id, "organ_id": adapter.organ_id},
            )
        response = _synthetic_response(adapter, phase=phase, event=event, fault=fault)
        response["observations"]["mode"] = "artifact-contract"
    elif adapter.mode == "human":
        raise AdapterRefused(
            "human_intervention_required",
            {"adapter_id": adapter.adapter_id},
        )
    else:
        raise AdapterRefused("adapter_mode_unknown", {"adapter_id": adapter.adapter_id})

    if response.get("format") != "axm-adapter-response/1":
        raise AdapterRefused("adapter_response_format", {"adapter_id": adapter.adapter_id})
    if response.get("adapter_id") != adapter.adapter_id:
        raise AdapterRefused("adapter_identity_mismatch", {"adapter_id": adapter.adapter_id})
    if response.get("phase") != phase:
        raise AdapterRefused("adapter_phase_mismatch", {"adapter_id": adapter.adapter_id})
    if response.get("accepted") is not True:
        raise AdapterRefused(
            str(response.get("reason") or "adapter_refused"),
            {"adapter_id": adapter.adapter_id, "response": response},
        )

    expected_digest = sha256_hex(semantic_projection(event))
    if response.get("semantic_digest") != expected_digest:
        raise AdapterRefused(
            "adapter_semantic_mutation",
            {
                "adapter_id": adapter.adapter_id,
                "expected_digest": expected_digest,
                "received_digest": response.get("semantic_digest"),
            },
        )
    return response
