"""Repository discovery and bounded project probes."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .canonical import sha256_hex
from .model import EstateManifest, ProbeResult


def discover_repositories(manifest: EstateManifest, workspace: Path | None) -> dict[str, Path | None]:
    """Resolve organ repositories below a workspace without guessing outside it."""

    result: dict[str, Path | None] = {}
    if workspace is None:
        return {organ_id: None for organ_id in manifest.organs}

    root = workspace.expanduser().resolve()
    for organ_id, organ in manifest.organs.items():
        found: Path | None = None
        for local_name in organ.local_names:
            candidate = (root / local_name).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_dir():
                found = candidate
                break
        result[organ_id] = found
    return result


def _resolve_command(argv: tuple[str, ...], repo: Path) -> tuple[str, ...]:
    result = []
    for token in argv:
        result.append(token.replace("{repo}", str(repo)))
    return tuple(result)


def run_probes(
    manifest: EstateManifest,
    repositories: dict[str, Path | None],
    *,
    profile: str,
    environment: dict[str, str] | None = None,
) -> tuple[list[ProbeResult], dict[str, dict[str, Any]]]:
    """Run the exact probes selected by profile.

    The function never invokes a shell. Commands come from the human-owned
    manifest and execute with a bounded timeout in the resolved repository.
    """

    results: list[ProbeResult] = []
    logs: dict[str, dict[str, Any]] = {}
    if profile == "none":
        return results, logs

    for organ_id in sorted(manifest.organs):
        organ = manifest.organs[organ_id]
        repo = repositories.get(organ_id)
        selected = [probe for probe in organ.probes if probe.profile == profile or profile == "all"]
        for probe in selected:
            key = f"{organ_id}:{probe.probe_id}"
            if repo is None:
                result = ProbeResult(
                    organ_id=organ_id,
                    probe_id=probe.probe_id,
                    status="missing",
                    evidence_class=probe.evidence_class,
                    exit_code=None,
                    duration_ms=0,
                    stdout_sha256=None,
                    stderr_sha256=None,
                    reason="repository_not_found",
                )
                results.append(result)
                logs[key] = {"result": asdict(result), "stdout": "", "stderr": ""}
                continue

            missing_paths = [relative for relative in probe.required_paths if not (repo / relative).exists()]
            if missing_paths:
                result = ProbeResult(
                    organ_id=organ_id,
                    probe_id=probe.probe_id,
                    status="failed",
                    evidence_class=probe.evidence_class,
                    exit_code=None,
                    duration_ms=0,
                    stdout_sha256=None,
                    stderr_sha256=None,
                    reason=f"required_paths_missing:{','.join(missing_paths)}",
                )
                results.append(result)
                logs[key] = {"result": asdict(result), "stdout": "", "stderr": ""}
                continue

            argv = _resolve_command(probe.command, repo)
            executable = argv[0]
            if not os.path.isabs(executable) and shutil.which(executable) is None:
                result = ProbeResult(
                    organ_id=organ_id,
                    probe_id=probe.probe_id,
                    status="skipped",
                    evidence_class=probe.evidence_class,
                    exit_code=None,
                    duration_ms=0,
                    stdout_sha256=None,
                    stderr_sha256=None,
                    reason=f"executable_not_found:{executable}",
                )
                results.append(result)
                logs[key] = {"result": asdict(result), "stdout": "", "stderr": ""}
                continue

            started = time.monotonic()
            env = os.environ.copy()
            if environment:
                env.update(environment)
            try:
                completed = subprocess.run(
                    list(argv),
                    cwd=repo,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=probe.timeout_seconds,
                    check=False,
                    shell=False,
                )
                duration_ms = int((time.monotonic() - started) * 1000)
                passed = completed.returncode in probe.expected_exit_codes
                result = ProbeResult(
                    organ_id=organ_id,
                    probe_id=probe.probe_id,
                    status="passed" if passed else "failed",
                    evidence_class=probe.evidence_class,
                    exit_code=completed.returncode,
                    duration_ms=duration_ms,
                    stdout_sha256=sha256_hex(completed.stdout.encode("utf-8")),
                    stderr_sha256=sha256_hex(completed.stderr.encode("utf-8")),
                    reason=None if passed else "unexpected_exit_code",
                )
                stdout = completed.stdout
                stderr = completed.stderr
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
                result = ProbeResult(
                    organ_id=organ_id,
                    probe_id=probe.probe_id,
                    status="failed",
                    evidence_class=probe.evidence_class,
                    exit_code=None,
                    duration_ms=duration_ms,
                    stdout_sha256=sha256_hex(stdout.encode("utf-8")),
                    stderr_sha256=sha256_hex(stderr.encode("utf-8")),
                    reason="timeout",
                )
            results.append(result)
            logs[key] = {"result": asdict(result), "stdout": stdout, "stderr": stderr}
    return results, logs


def adapter_status_from_environment(
    manifest: EstateManifest,
    repositories: dict[str, Path | None],
    probe_results: list[ProbeResult],
    *,
    execution_mode: str,
) -> dict[str, str]:
    """Project repository and probe health onto adapter availability."""

    failures_by_organ: dict[str, bool] = {}
    passes_by_organ: dict[str, bool] = {}
    for result in probe_results:
        failures_by_organ[result.organ_id] = failures_by_organ.get(result.organ_id, False) or result.status == "failed"
        passes_by_organ[result.organ_id] = passes_by_organ.get(result.organ_id, False) or result.status == "passed"

    statuses: dict[str, str] = {}
    for adapter_id, adapter in manifest.adapters.items():
        if execution_mode == "synthetic":
            statuses[adapter_id] = adapter.default_status
            continue
        if adapter.mode == "synthetic":
            statuses[adapter_id] = "degraded"
            continue
        repo = repositories.get(adapter.organ_id)
        if adapter.mode in {"command", "artifact"} and repo is None:
            statuses[adapter_id] = "unavailable"
            continue
        if failures_by_organ.get(adapter.organ_id, False):
            statuses[adapter_id] = "unavailable"
            continue
        if passes_by_organ.get(adapter.organ_id, False):
            statuses[adapter_id] = "available"
            continue
        statuses[adapter_id] = "degraded" if adapter.mode == "human" else adapter.default_status
    return statuses
