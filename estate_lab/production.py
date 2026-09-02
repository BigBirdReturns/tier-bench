"""Production hardening, release, and diagnostics for Surface Interop.

The public protocol remains small and reimplementable.  This module hardens the
reference Python implementation around that protocol without changing semantic
identity.  It provides bounded subprocess execution, secret-minimizing process
environments, pinned adapter entrypoints, crash-safe receipt publication,
deterministic release archives, SPDX file inventories, offline verification,
and support diagnostics that disclose hashes rather than user content.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_json_bytes, load_json, sha256_hex, stable_id
from .errors import FloorProtocolError

PRODUCTION_POLICY_FORMAT = "surface-interop-production-policy/1"
DOCTOR_FORMAT = "surface-interop-doctor/1"
RELEASE_FORMAT = "surface-interop-release/1"
RELEASE_VALIDATION_FORMAT = "surface-interop-release-validation/1"
SUPPORT_FORMAT = "surface-interop-support/1"

DEFAULT_MAX_REQUEST_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_CAPTURE_BYTES = 256 * 1024
DEFAULT_MAX_RELEASE_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_RELEASE_BYTES = 256 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60

_SECRET_NAME_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTHORIZATION|COOKIE)",
    re.IGNORECASE,
)
_ALLOWED_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
)
_RELEASE_SOURCE_NAMES = (
    "ADAPTER_CONTRACT.md",
    "ADOPTING_FLOOR.md",
    "CHANGELOG.md",
    "COMMODITY_SWEEP.md",
    "CONTINUITY.md",
    "DESIGN.md",
    "FLOOR_BINDINGS.md",
    "FLOOR_CONFORMANCE.md",
    "FLOOR_GOVERNANCE.md",
    "FLOOR_SPECIFICATION.md",
    "OPERATIONS.md",
    "PRODUCTION_READINESS.md",
    "SECURITY.md",
    "SUPPORT.md",
    "VERSION",
    "canonical.py",
    "errors.py",
    "floor.py",
    "floor_gaps.py",
    "production.py",
    "production_cli.py",
)


class ProductionError(RuntimeError):
    """A production boundary refused an unsafe or unverifiable operation."""

    def __init__(self, reason: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})


@dataclass(frozen=True)
class ProductionPolicy:
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES
    max_release_file_bytes: int = DEFAULT_MAX_RELEASE_FILE_BYTES
    max_release_bytes: int = DEFAULT_MAX_RELEASE_BYTES
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    require_pinned_entrypoint: bool = True
    strip_secret_environment: bool = True

    def validate(self) -> "ProductionPolicy":
        integer_fields = {
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "max_capture_bytes": self.max_capture_bytes,
            "max_release_file_bytes": self.max_release_file_bytes,
            "max_release_bytes": self.max_release_bytes,
            "timeout_seconds": self.timeout_seconds,
        }
        for name, value in integer_fields.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ProductionError("production_policy_invalid", {"field": name, "value": value})
        for name in ("require_pinned_entrypoint", "strip_secret_environment"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise ProductionError("production_policy_invalid", {"field": name, "value": value})
        if self.timeout_seconds > 300:
            raise ProductionError(
                "production_policy_invalid",
                {"field": "timeout_seconds", "reason": "exceeds 300 seconds"},
            )
        if self.max_release_file_bytes > self.max_release_bytes:
            raise ProductionError(
                "production_policy_invalid",
                {"field": "max_release_file_bytes", "reason": "exceeds max_release_bytes"},
            )
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"format": PRODUCTION_POLICY_FORMAT, **asdict(self)}


@dataclass(frozen=True)
class ProcessReceipt:
    argv_sha256: str
    cwd_sha256: str
    environment_keys: tuple[str, ...]
    exit_code: int
    duration_ms: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class DoctorCheck:
    check_id: str
    status: str
    detail: str
    evidence: dict[str, Any]


def load_production_policy(path: Path | None = None) -> ProductionPolicy:
    if path is None:
        return ProductionPolicy().validate()
    try:
        raw = strict_load_json(path, max_bytes=64 * 1024)
    except (OSError, ValueError, ProductionError) as exc:
        raise ProductionError("production_policy_unreadable", {"path": str(path)}) from exc
    if not isinstance(raw, dict) or raw.get("format") != PRODUCTION_POLICY_FORMAT:
        raise ProductionError("production_policy_format", {"path": str(path)})
    allowed = {field.name for field in ProductionPolicy.__dataclass_fields__.values()}
    unknown = set(raw) - allowed - {"format"}
    if unknown:
        raise ProductionError("production_policy_unknown_fields", {"fields": sorted(unknown)})
    values = {key: raw[key] for key in allowed if key in raw}
    return ProductionPolicy(**values).validate()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def strict_load_json(path: Path, *, max_bytes: int) -> Any:
    if path.is_symlink():
        raise ProductionError("json_symlink_refused", {"path": str(path)})
    if not path.is_file():
        raise ProductionError("json_not_regular_file", {"path": str(path)})
    size = path.stat().st_size
    if size > max_bytes:
        raise ProductionError(
            "json_size_limit",
            {"path": str(path), "size": size, "max_bytes": max_bytes},
        )
    return load_json(path)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int = 0o644) -> None:
    """Publish bytes through same-directory fsync + replace.

    A crash may leave an unreferenced temporary file, but it cannot expose a
    partially written destination as an accepted report or release manifest.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_write_text(path: Path, text: str, *, mode: int = 0o644) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o644) -> None:
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    atomic_write_text(path, text, mode=mode)


def sanitized_environment(
    source: Mapping[str, str] | None = None,
    *,
    strip_secrets: bool = True,
) -> dict[str, str]:
    source = dict(os.environ if source is None else source)
    result: dict[str, str] = {}
    for key, value in source.items():
        if key not in _ALLOWED_ENVIRONMENT:
            continue
        if strip_secrets and _SECRET_NAME_RE.search(key):
            continue
        result[key] = value
    result.update(
        {
            "NO_PROXY": "*",
            "no_proxy": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "SURFACE_INTEROP_EXECUTION": "bounded",
        }
    )
    return result


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        with contextlib.suppress(Exception):
            process.kill()
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    max_capture_bytes: int,
    environment: Mapping[str, str] | None = None,
) -> tuple[ProcessReceipt, bytes, bytes]:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ProductionError("process_argv_invalid")
    if cwd.is_symlink() or not cwd.is_dir():
        raise ProductionError("process_cwd_invalid", {"cwd": str(cwd)})
    creation_flags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    if timeout_seconds < 1 or max_capture_bytes < 1:
        raise ProductionError(
            "process_limits_invalid",
            {"timeout_seconds": timeout_seconds, "max_capture_bytes": max_capture_bytes},
        )
    env = dict(sanitized_environment() if environment is None else environment)
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=start_new_session,
        creationflags=creation_flags,
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = threading.Event()
    reader_errors: list[str] = []

    def reader(name: str, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                remaining = max_capture_bytes - len(buffers[name])
                if remaining <= 0:
                    overflow.set()
                    continue
                buffers[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
        except Exception as exc:  # pragma: no cover - platform pipe failure
            reader_errors.append(f"{name}:{type(exc).__name__}")
            overflow.set()

    assert process.stdout is not None and process.stderr is not None
    threads = [
        threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    while process.poll() is None:
        if overflow.is_set():
            _terminate_process_tree(process)
            break
        if time.monotonic() - started > timeout_seconds:
            timed_out = True
            _terminate_process_tree(process)
            break
        time.sleep(0.01)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=2)
    for stream in (process.stdout, process.stderr):
        with contextlib.suppress(Exception):
            stream.close()
    if any(thread.is_alive() for thread in threads):
        overflow.set()
        reader_errors.append("pipe_reader_did_not_settle")

    stdout = bytes(buffers["stdout"])
    stderr = bytes(buffers["stderr"])
    details = {
        "exit_code": process.returncode,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
    }
    if timed_out:
        raise ProductionError("adapter_timeout", {**details, "timeout_seconds": timeout_seconds})
    if overflow.is_set():
        raise ProductionError(
            "adapter_output_limit",
            {**details, "max_capture_bytes": max_capture_bytes, "reader_errors": reader_errors},
        )
    receipt = ProcessReceipt(
        argv_sha256=sha256_hex(list(argv)),
        cwd_sha256=hashlib.sha256(str(cwd.resolve()).encode("utf-8")).hexdigest(),
        environment_keys=tuple(sorted(env)),
        exit_code=int(process.returncode if process.returncode is not None else -999),
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        stdout_sha256=details["stdout_sha256"],
        stderr_sha256=details["stderr_sha256"],
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
    )
    return receipt, stdout, stderr


def _resolved_local_command_files(adapter: Any, argv: Sequence[str]) -> list[Path]:
    root = adapter.source_path.parent.resolve()
    candidates: list[Path] = []
    for token in argv:
        candidate = Path(token)
        unresolved = candidate if candidate.is_absolute() else root / candidate
        path = unresolved.resolve()
        if not path.is_file():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            # External interpreters and launchers remain outside the adapter
            # supply boundary. Only local adapter artifacts are subject to
            # descriptor pins and symlink refusal.
            continue
        if unresolved.is_symlink():
            raise ProductionError(
                "entrypoint_symlink_refused",
                {"path": str(unresolved)},
            )
        executable_suffixes = {
            ".py", ".pyw", ".js", ".mjs", ".cjs", ".rb", ".pl", ".php",
            ".jar", ".wasm", ".exe", ".cmd", ".bat", ".ps1", ".sh", ".bin",
        }
        if path.suffix.lower() not in executable_suffixes and not os.access(path, os.X_OK):
            continue
        candidates.append(path)
    return candidates


def verify_pinned_entrypoint(adapter: Any, argv: Sequence[str]) -> dict[str, str]:
    root = adapter.source_path.parent.resolve()
    expected: dict[Path, str] = {}
    supply = adapter.raw.get("supply", {})
    for row in supply.get("artifacts", []):
        relative = row.get("path")
        digest = row.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ProductionError("supply_path_escape", {"path": relative}) from exc
        expected[path] = digest
    observed: dict[str, str] = {}
    local_files = _resolved_local_command_files(adapter, argv)
    for path in local_files:
        digest = sha256_file(path)
        observed[path.relative_to(root).as_posix()] = digest
        if path not in expected:
            raise ProductionError(
                "entrypoint_unpinned",
                {"path": path.relative_to(root).as_posix()},
            )
        if digest != expected[path]:
            raise ProductionError(
                "entrypoint_digest_mismatch",
                {
                    "path": path.relative_to(root).as_posix(),
                    "expected": expected[path],
                    "actual": digest,
                },
            )
    if not local_files:
        raise ProductionError("entrypoint_local_artifact_missing")
    return dict(sorted(observed.items()))


def hardened_invoke_floor_adapter(
    adapter: Any,
    request: Mapping[str, Any],
    *,
    policy: ProductionPolicy | None = None,
    receipt_sink: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one floor adapter with production resource and supply controls."""

    from . import floor as floor_module

    policy = (policy or ProductionPolicy()).validate()
    payload = canonical_json_bytes(dict(request))
    if len(payload) > policy.max_request_bytes:
        raise FloorProtocolError("request exceeds production size limit")
    root = adapter.source_path.parent.resolve()
    with tempfile.TemporaryDirectory(prefix="surface-interop-") as temp_dir:
        temporary = Path(temp_dir)
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o700)
        request_path = temporary / "request.json"
        response_path = temporary / "response.json"
        atomic_write_bytes(request_path, payload + b"\n", mode=0o600)
        argv = floor_module._resolve_command(adapter, request_path, response_path)
        if not argv:
            raise FloorProtocolError("adapter command resolved to an empty argv")
        executable = argv[0]
        if not os.path.isabs(executable):
            resolved_executable = shutil.which(executable)
            if resolved_executable is None:
                raise FloorProtocolError(f"adapter executable is unavailable: {executable}")
            argv[0] = str(Path(resolved_executable).resolve())
        elif not Path(executable).is_file():
            raise FloorProtocolError(f"adapter executable is unavailable: {executable}")
        pins: dict[str, str] = {}
        if policy.require_pinned_entrypoint:
            try:
                pins = verify_pinned_entrypoint(adapter, argv)
            except ProductionError as exc:
                raise FloorProtocolError(exc.reason) from exc
        try:
            receipt, stdout, stderr = run_bounded_process(
                argv,
                cwd=root,
                timeout_seconds=min(adapter.timeout_seconds, policy.timeout_seconds),
                max_capture_bytes=policy.max_capture_bytes,
                environment=sanitized_environment(strip_secrets=policy.strip_secret_environment),
            )
        except ProductionError as exc:
            raise FloorProtocolError(exc.reason) from exc
        if receipt.exit_code != 0:
            raise FloorProtocolError(
                "adapter exited nonzero: "
                f"exit={receipt.exit_code} stdout={receipt.stdout_sha256} "
                f"stderr={receipt.stderr_sha256}"
            )
        try:
            if response_path.is_file():
                response = strict_load_json(response_path, max_bytes=policy.max_response_bytes)
            else:
                if len(stdout) > policy.max_response_bytes:
                    raise ProductionError("response_size_limit")
                response = json.loads(stdout)
        except (OSError, ValueError, json.JSONDecodeError, ProductionError) as exc:
            raise FloorProtocolError("adapter emitted malformed or oversized JSON") from exc
        if not isinstance(response, dict):
            raise FloorProtocolError("adapter response must be an object")
        if receipt_sink is not None:
            receipt_sink.append(
                {
                    "format": "surface-interop-execution-receipt/1",
                    "request_id": request.get("request_id"),
                    "adapter_id": adapter.adapter_id,
                    "command_template_sha256": sha256_hex(list(adapter.command)),
                    "pinned_entrypoints": pins,
                    "process": asdict(receipt),
                }
            )
        return dict(response)


_CONFORMANCE_PATCH_LOCK = threading.RLock()


def _checksum_text(root: Path) -> str:
    rows: list[str] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name == "CHECKSUMS.sha256":
            continue
        rows.append(f"{sha256_file(path)}  {path.name}")
    return "\n".join(rows) + "\n"


def _publish_conformance_bundle(
    output_root: Path,
    *,
    spec: Any,
    adapter: Any,
    submission: Any,
    policy: ProductionPolicy,
    execution_receipts: Sequence[Mapping[str, Any]],
) -> Path:
    if output_root.is_symlink():
        raise ProductionError("conformance_output_symlink", {"path": str(output_root)})
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / submission.submission_id
    if final.exists():
        raise ProductionError("conformance_output_exists", {"path": str(final)})
    staging = Path(tempfile.mkdtemp(prefix=".surface-interop-", dir=output_root))
    try:
        atomic_write_json(staging / "submission.json", submission.raw, mode=0o600)
        atomic_write_json(staging / "floor.snapshot.json", spec.raw, mode=0o600)
        atomic_write_json(staging / "adapter.snapshot.json", adapter.raw, mode=0o600)
        atomic_write_json(staging / "production-policy.json", policy.as_dict(), mode=0o600)
        atomic_write_json(
            staging / "execution-receipts.json",
            {
                "format": "surface-interop-execution-receipts/1",
                "submission_id": submission.submission_id,
                "count": len(execution_receipts),
                "receipts": list(execution_receipts),
            },
            mode=0o600,
        )
        from .floor import render_conformance_summary

        atomic_write_text(
            staging / "SUMMARY.md",
            render_conformance_summary(submission.raw),
            mode=0o600,
        )
        atomic_write_text(staging / "CHECKSUMS.sha256", _checksum_text(staging), mode=0o600)
        _fsync_directory(staging)
        os.replace(staging, final)
        _fsync_directory(output_root)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def run_production_conformance(
    spec: Any,
    adapter: Any,
    *,
    output_root: Path | None = None,
    independent_verifier: bool = False,
    substitution_receipt_sha256: str | None = None,
    policy: ProductionPolicy | None = None,
) -> Any:
    """Run public vectors through the hardened execution and publication boundary."""

    from . import floor as floor_module

    active_policy = (policy or ProductionPolicy()).validate()
    execution_receipts: list[dict[str, Any]] = []
    with _CONFORMANCE_PATCH_LOCK:
        original_invoke = floor_module.invoke_floor_adapter
        original_submission = floor_module._submission_from_results

        def production_submission(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raw = original_submission(*args, **kwargs)
            version_path = Path(__file__).resolve().parent / "VERSION"
            version = version_path.read_text(encoding="utf-8").strip()
            raw["verifier"] = {
                "implementation": "surface-interop-python",
                "version": version,
                "execution_boundary": "production-hardened",
                "authority": "conformance only; not semantic truth or deployment approval",
            }
            raw.setdefault("evidence", {})["production_policy_sha256"] = sha256_hex(
                active_policy.as_dict()
            )
            raw["submission_id"] = floor_module.derived_submission_id(raw)
            return raw

        floor_module.invoke_floor_adapter = lambda item, request: hardened_invoke_floor_adapter(
            item,
            request,
            policy=active_policy,
            receipt_sink=execution_receipts,
        )
        floor_module._submission_from_results = production_submission
        try:
            submission = floor_module.run_floor_conformance(
                spec,
                adapter,
                output_root=None,
                independent_verifier=independent_verifier,
                substitution_receipt_sha256=substitution_receipt_sha256,
            )
        finally:
            floor_module.invoke_floor_adapter = original_invoke
            floor_module._submission_from_results = original_submission
    if output_root is not None:
        _publish_conformance_bundle(
            output_root,
            spec=spec,
            adapter=adapter,
            submission=submission,
            policy=active_policy,
            execution_receipts=execution_receipts,
        )
    return submission


def verify_submission_bundle(
    bundle: Path,
    *,
    policy: ProductionPolicy | None = None,
) -> dict[str, Any]:
    """Verify an atomically published conformance bundle without executing code."""

    active_policy = (policy or ProductionPolicy()).validate()
    if bundle.is_symlink() or not bundle.is_dir():
        raise ProductionError("submission_bundle_missing", {"path": str(bundle)})
    expected_names = {
        "submission.json",
        "floor.snapshot.json",
        "adapter.snapshot.json",
        "production-policy.json",
        "execution-receipts.json",
        "SUMMARY.md",
        "CHECKSUMS.sha256",
    }
    actual_names = {path.name for path in bundle.iterdir() if path.is_file()}
    if actual_names != expected_names or any(path.is_dir() for path in bundle.iterdir()):
        raise ProductionError(
            "submission_bundle_shape",
            {"expected": sorted(expected_names), "actual": sorted(actual_names)},
        )
    checksums: dict[str, str] = {}
    for line in (bundle / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if separator != "  " or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProductionError("submission_checksum_row_malformed")
        if name in checksums or name not in expected_names - {"CHECKSUMS.sha256"}:
            raise ProductionError("submission_checksum_path_invalid", {"path": name})
        checksums[name] = digest
    if set(checksums) != expected_names - {"CHECKSUMS.sha256"}:
        raise ProductionError("submission_checksum_coverage")
    for name, expected in checksums.items():
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise ProductionError("submission_file_invalid", {"path": name})
        if path.stat().st_size > active_policy.max_release_file_bytes:
            raise ProductionError("submission_file_size_limit", {"path": name})
        actual = sha256_file(path)
        if actual != expected:
            raise ProductionError(
                "submission_checksum_mismatch",
                {"path": name, "expected": expected, "actual": actual},
            )
    from .floor import (
        derived_adapter_descriptor_id,
        derived_floor_id,
        load_floor_submission,
    )

    submission = load_floor_submission(bundle / "submission.json")
    floor_raw = strict_load_json(bundle / "floor.snapshot.json", max_bytes=active_policy.max_response_bytes)
    adapter_raw = strict_load_json(bundle / "adapter.snapshot.json", max_bytes=active_policy.max_response_bytes)
    policy_raw = strict_load_json(bundle / "production-policy.json", max_bytes=64 * 1024)
    execution_raw = strict_load_json(
        bundle / "execution-receipts.json",
        max_bytes=active_policy.max_release_file_bytes,
    )
    if not all(isinstance(value, dict) for value in (floor_raw, adapter_raw, policy_raw, execution_raw)):
        raise ProductionError("submission_bundle_json_shape")
    if floor_raw.get("floor_id") != derived_floor_id(floor_raw):
        raise ProductionError("submission_floor_identity")
    if adapter_raw.get("descriptor_id") != derived_adapter_descriptor_id(adapter_raw):
        raise ProductionError("submission_adapter_identity")
    if submission.floor_id != floor_raw.get("floor_id"):
        raise ProductionError("submission_floor_binding")
    if submission.descriptor_id != adapter_raw.get("descriptor_id"):
        raise ProductionError("submission_adapter_binding")
    if policy_raw.get("format") != PRODUCTION_POLICY_FORMAT:
        raise ProductionError("submission_policy_format")
    expected_policy_digest = submission.raw.get("evidence", {}).get("production_policy_sha256")
    if expected_policy_digest != sha256_hex(policy_raw):
        raise ProductionError("submission_policy_binding")
    if execution_raw.get("format") != "surface-interop-execution-receipts/1":
        raise ProductionError("submission_execution_receipts_format")
    if execution_raw.get("submission_id") != submission.submission_id:
        raise ProductionError("submission_execution_receipts_binding")
    receipts = execution_raw.get("receipts")
    if not isinstance(receipts, list) or execution_raw.get("count") != len(receipts):
        raise ProductionError("submission_execution_receipts_count")
    return {
        "status": "PASS",
        "submission_id": submission.submission_id,
        "adapter_id": submission.adapter_id,
        "quality_tier": submission.tier,
        "verified_files": len(checksums),
        "execution_receipts": len(receipts),
    }


def _safe_release_relative(path: Path) -> str:
    relative = path.as_posix()
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProductionError("release_path_invalid", {"path": relative})
    if "\\" in relative or "\x00" in relative:
        raise ProductionError("release_path_invalid", {"path": relative})
    return relative


def _iter_release_source_files(source_root: Path) -> tuple[Path, ...]:
    package = source_root / "estate_lab"
    paths: list[Path] = []
    for name in _RELEASE_SOURCE_NAMES:
        path = package / name
        if path.is_file():
            paths.append(path)
    for directory in (
        package / "schemas",
        package / "contracts",
        package / "fixtures" / "floor",
        package / "wit",
    ):
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    for optional in (source_root / "LICENSE", source_root / "NOTICE"):
        if optional.is_file():
            paths.append(optional)
    unique = sorted({path.resolve() for path in paths}, key=lambda item: item.as_posix())
    if not unique:
        raise ProductionError("release_source_empty")
    return tuple(unique)


def _release_file_rows(
    source_root: Path,
    files: Iterable[Path],
    *,
    policy: ProductionPolicy,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    total = 0
    root = source_root.resolve()
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ProductionError("release_non_regular_file", {"path": str(path)})
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ProductionError("release_path_escape", {"path": str(path)}) from exc
        relative_text = _safe_release_relative(relative)
        size = resolved.stat().st_size
        if size > policy.max_release_file_bytes:
            raise ProductionError(
                "release_file_size_limit",
                {"path": relative_text, "size": size},
            )
        total += size
        if total > policy.max_release_bytes:
            raise ProductionError("release_total_size_limit", {"bytes": total})
        mode = 0o755 if os.access(resolved, os.X_OK) else 0o644
        rows.append(
            {
                "path": relative_text,
                "bytes": size,
                "sha256": sha256_file(resolved),
                "mode": f"{mode:04o}",
            }
        )
    return rows, total


def _spdx_document(version: str, release_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    files = []
    relationships = []
    for index, row in enumerate(rows, start=1):
        file_id = f"SPDXRef-File-{index:04d}"
        files.append(
            {
                "SPDXID": file_id,
                "fileName": row["path"],
                "checksums": [{"algorithm": "SHA256", "checksumValue": row["sha256"]}],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-SurfaceInterop",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"surface-interop-{version}",
        "documentNamespace": f"urn:surface-interop:{release_id}",
        "creationInfo": {
            "created": "1980-01-01T00:00:00Z",
            "creators": ["Tool: surface-interop-production"],
        },
        "packages": [
            {
                "name": "surface-interop",
                "SPDXID": "SPDXRef-Package-SurfaceInterop",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        ],
        "files": files,
        "relationships": relationships,
    }


def _zip_entry(name: str, payload: bytes, *, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.flag_bits |= 0x800
    return info


def _generated_release_files(version: str) -> dict[str, tuple[bytes, bool]]:
    pyproject = f'''[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "surface-interop"
version = "{version}"
description = "Vendor-neutral semantic adapter conformance and deterministic release tooling."
readme = "README.md"
requires-python = ">=3.10"
dependencies = []
license = {{text = "MIT"}}
classifiers = [
  "Programming Language :: Python :: 3",
  "Operating System :: OS Independent",
  "Topic :: Software Development :: Testing",
]

[project.scripts]
surface-interop = "estate_lab.production_cli:main"

[tool.setuptools]
packages = ["estate_lab"]
include-package-data = true

[tool.setuptools.package-data]
estate_lab = [
  "*.md",
  "VERSION",
  "schemas/*.json",
  "contracts/*.json",
  "fixtures/floor/*.json",
  "fixtures/floor/vectors/*.json",
  "fixtures/floor/reference-adapter/*.json",
  "fixtures/floor/reference-adapter/*.py",
  "fixtures/floor/reference-adapter/*.md",
  "wit/*.wit",
]
'''.encode("utf-8")
    readme = f'''# Surface Interop {version}

This archive is the deterministic, offline-verifiable distribution of the Surface Interop protocol, hardened conformance runner, schemas, vectors, reference adapter, governance record, and release verifier.

Run it without installation through the path-pinned bootstrap:

```text
python surface-interop.py doctor
python surface-interop.py conform --allow-exec --output conformance
```

An optional local installation uses `python -m pip install --no-build-isolation --no-deps .`. Runtime operation has no third-party Python dependencies.

The conformance result proves the named protocol boundary only. It does not grant domain authority, certify physical safety, or approve deployment.
'''.encode("utf-8")
    package_init = f'''"""Surface Interop production reference implementation."""

from .floor import load_floor_adapter, load_floor_spec, load_floor_submission
from .floor_gaps import load_gap_ledger
from .production import (
    ProductionPolicy,
    build_release_archive,
    production_doctor,
    run_production_conformance,
    verify_release_archive,
    verify_submission_bundle,
)

__all__ = [
    "ProductionPolicy",
    "build_release_archive",
    "load_floor_adapter",
    "load_floor_spec",
    "load_floor_submission",
    "load_gap_ledger",
    "production_doctor",
    "run_production_conformance",
    "verify_release_archive",
    "verify_submission_bundle",
]
__version__ = "{version}"
'''.encode("utf-8")
    package_main = b"from .production_cli import main\n\nraise SystemExit(main())\n"
    python_launcher = (
        b'"""Path-pinned no-install Surface Interop bootstrap."""\n'
        b'from __future__ import annotations\n\n'
        b'import sys\n'
        b'from pathlib import Path\n\n'
        b'ROOT = Path(__file__).resolve().parent\n'
        b'sys.path.insert(0, str(ROOT))\n'
        b'from estate_lab.production_cli import main  # noqa: E402\n\n'
        b'raise SystemExit(main())\n'
    )
    shell_launcher = (
        b'#!/usr/bin/env sh\n'
        b'set -eu\n'
        b'ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        b'exec "${PYTHON:-python3}" "$ROOT/surface-interop.py" "$@"\n'
    )
    powershell_launcher = (
        b'param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)\n'
        b'$ErrorActionPreference = "Stop"\n'
        b'$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }\n'
        b'$launcher = Join-Path $PSScriptRoot "surface-interop.py"\n'
        b'& $python $launcher @Arguments\n'
        b'exit $LASTEXITCODE\n'
    )
    return {
        "pyproject.toml": (pyproject, False),
        "README.md": (readme, False),
        "estate_lab/__init__.py": (package_init, False),
        "estate_lab/__main__.py": (package_main, False),
        "surface-interop.py": (python_launcher, False),
        "surface-interop": (shell_launcher, True),
        "surface-interop.ps1": (powershell_launcher, False),
    }


def _memory_file_rows(files: Mapping[str, tuple[bytes, bool]]) -> list[dict[str, Any]]:
    rows = []
    for name, (payload, executable) in sorted(files.items()):
        _safe_release_relative(Path(name))
        rows.append(
            {
                "path": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mode": "0755" if executable else "0644",
            }
        )
    return rows


def build_release_archive(
    source_root: Path,
    output_zip: Path,
    *,
    version: str,
    policy: ProductionPolicy | None = None,
) -> dict[str, Any]:
    active_policy = (policy or ProductionPolicy()).validate()
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?",
        version,
    ):
        raise ProductionError("release_version_invalid", {"version": version})
    source_root = source_root.resolve()
    version_file = source_root / "estate_lab" / "VERSION"
    if not version_file.is_file() or version_file.read_text(encoding="utf-8").strip() != version:
        raise ProductionError("release_version_drift", {"version": version})
    files = _iter_release_source_files(source_root)
    source_rows, source_bytes = _release_file_rows(source_root, files, policy=active_policy)
    generated_base = _generated_release_files(version)
    generated_rows = _memory_file_rows(generated_base)
    source_paths = {row["path"] for row in source_rows}
    generated_paths = {row["path"] for row in generated_rows}
    overlap = source_paths.intersection(generated_paths)
    if overlap:
        raise ProductionError("release_generated_path_collision", {"paths": sorted(overlap)})
    release_projection = {
        "format": RELEASE_FORMAT,
        "version": version,
        "source_files": source_rows,
        "generated_files": generated_rows,
        "source_bytes": source_bytes,
        "generated_bytes": sum(row["bytes"] for row in generated_rows),
        "canonicalization": "utf8-sorted-json-sha256-v1",
    }
    release_id = stable_id("surfrelease1", release_projection, length=32)
    manifest = {**release_projection, "release_id": release_id}
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    manifest_row = {
        "path": "RELEASE_MANIFEST.json",
        "bytes": len(manifest_payload),
        "sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "mode": "0644",
    }
    sbom = _spdx_document(version, release_id, [*source_rows, *generated_rows, manifest_row])
    sbom_payload = (
        json.dumps(sbom, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    generated: dict[str, tuple[bytes, bool]] = {
        **generated_base,
        "RELEASE_MANIFEST.json": (manifest_payload, False),
        "SBOM.spdx.json": (sbom_payload, False),
    }
    all_rows = [*source_rows, *_memory_file_rows(generated)]
    total_uncompressed = sum(row["bytes"] for row in all_rows)
    if total_uncompressed > active_policy.max_release_bytes:
        raise ProductionError("release_total_size_limit", {"bytes": total_uncompressed})
    checksums = [
        f"{row['sha256']}  {row['path']}"
        for row in sorted(all_rows, key=lambda row: row["path"])
    ]
    generated["CHECKSUMS.sha256"] = (("\n".join(checksums) + "\n").encode("utf-8"), False)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_zip.name}.", dir=output_zip.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for row in source_rows:
                payload = (source_root / row["path"]).read_bytes()
                archive.writestr(
                    _zip_entry(row["path"], payload, executable=row["mode"] == "0755"),
                    payload,
                )
            for name, (payload, executable) in sorted(generated.items()):
                archive.writestr(_zip_entry(name, payload, executable=executable), payload)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_zip)
        _fsync_directory(output_zip.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    verification = verify_release_archive(output_zip, policy=active_policy)
    zip_sha256 = sha256_file(output_zip)
    atomic_write_text(
        output_zip.with_suffix(output_zip.suffix + ".sha256"),
        f"{zip_sha256}  {output_zip.name}\n",
    )
    validation = {
        "format": RELEASE_VALIDATION_FORMAT,
        "status": "PASS",
        "release_id": release_id,
        "version": version,
        "zip_sha256": zip_sha256,
        "zip_bytes": output_zip.stat().st_size,
        "verified_files": verification["verified_files"],
        "manifest_sha256": verification["manifest_sha256"],
        "sbom_sha256": verification["sbom_sha256"],
    }
    atomic_write_json(output_zip.with_name(output_zip.stem + ".validation.json"), validation)
    return validation


def _strict_json_bytes(payload: bytes, *, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProductionError("release_duplicate_json_key", {"label": label, "key": key})
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionError("release_json_malformed", {"label": label}) from exc


def _validate_manifest_rows(rows: Any, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ProductionError("release_manifest_rows", {"label": label})
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProductionError("release_manifest_row", {"label": label, "index": index})
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("bytes")
        mode = row.get("mode")
        if not isinstance(path, str):
            raise ProductionError("release_manifest_path", {"label": label, "index": index})
        _safe_release_relative(Path(path))
        if path in result:
            raise ProductionError("release_manifest_duplicate_path", {"path": path})
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProductionError("release_manifest_digest", {"path": path})
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ProductionError("release_manifest_size", {"path": path})
        if mode not in {"0644", "0755"}:
            raise ProductionError("release_manifest_mode", {"path": path})
        result[path] = dict(row)
    return result


def verify_release_archive(
    archive_path: Path,
    *,
    policy: ProductionPolicy | None = None,
) -> dict[str, Any]:
    import tomllib

    active_policy = (policy or ProductionPolicy()).validate()
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ProductionError("release_archive_missing", {"path": str(archive_path)})
    if archive_path.stat().st_size > active_policy.max_release_bytes:
        raise ProductionError("release_archive_size_limit", {"bytes": archive_path.stat().st_size})
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except zipfile.BadZipFile as exc:
        raise ProductionError("release_archive_malformed") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ProductionError("release_duplicate_path")
        total_uncompressed = 0
        for info in infos:
            _safe_release_relative(Path(info.filename))
            if info.flag_bits & 0x1:
                raise ProductionError("release_encrypted_entry", {"path": info.filename})
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ProductionError("release_compression_unsupported", {"path": info.filename})
            kind = (info.external_attr >> 16) & 0o170000
            if kind not in {0, stat.S_IFREG} or info.is_dir():
                raise ProductionError("release_non_regular_entry", {"path": info.filename})
            if info.file_size > active_policy.max_release_file_bytes:
                raise ProductionError("release_file_size_limit", {"path": info.filename})
            total_uncompressed += info.file_size
            if total_uncompressed > active_policy.max_release_bytes:
                raise ProductionError("release_total_size_limit", {"bytes": total_uncompressed})
        required = {
            "RELEASE_MANIFEST.json",
            "SBOM.spdx.json",
            "CHECKSUMS.sha256",
            "pyproject.toml",
            "README.md",
            "estate_lab/__init__.py",
            "estate_lab/__main__.py",
            "surface-interop.py",
            "surface-interop",
            "surface-interop.ps1",
        }
        if not required.issubset(names):
            raise ProductionError("release_manifest_missing", {"missing": sorted(required - set(names))})
        manifest_bytes = archive.read("RELEASE_MANIFEST.json")
        if len(manifest_bytes) > active_policy.max_response_bytes:
            raise ProductionError("release_manifest_size_limit")
        manifest = _strict_json_bytes(manifest_bytes, label="RELEASE_MANIFEST.json")
        if not isinstance(manifest, dict) or manifest.get("format") != RELEASE_FORMAT:
            raise ProductionError("release_manifest_format")
        expected_release_id = stable_id(
            "surfrelease1",
            {key: value for key, value in manifest.items() if key != "release_id"},
            length=32,
        )
        if manifest.get("release_id") != expected_release_id:
            raise ProductionError("release_identity_mismatch")
        source_rows = _validate_manifest_rows(manifest.get("source_files"), label="source_files")
        generated_rows = _validate_manifest_rows(manifest.get("generated_files"), label="generated_files")
        if set(source_rows).intersection(generated_rows):
            raise ProductionError("release_manifest_path_overlap")
        checksum_rows: dict[str, str] = {}
        try:
            checksum_text = archive.read("CHECKSUMS.sha256").decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProductionError("release_checksum_encoding") from exc
        for line in checksum_text.splitlines():
            digest, separator, name = line.partition("  ")
            if separator != "  " or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ProductionError("release_checksum_row_malformed", {"line": line[:120]})
            _safe_release_relative(Path(name))
            if name in checksum_rows:
                raise ProductionError("release_duplicate_checksum", {"path": name})
            checksum_rows[name] = digest
        expected_names = set(source_rows) | set(generated_rows) | {
            "RELEASE_MANIFEST.json",
            "SBOM.spdx.json",
            "CHECKSUMS.sha256",
        }
        if set(names) != expected_names:
            raise ProductionError(
                "release_archive_shape",
                {"missing": sorted(expected_names - set(names)), "extra": sorted(set(names) - expected_names)},
            )
        if set(checksum_rows) != expected_names - {"CHECKSUMS.sha256"}:
            raise ProductionError("release_checksum_coverage")
        verified = 0
        for name, expected in sorted(checksum_rows.items()):
            payload = archive.read(name)
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise ProductionError(
                    "release_checksum_mismatch",
                    {"path": name, "expected": expected, "actual": actual},
                )
            row = source_rows.get(name) or generated_rows.get(name)
            if row is not None and (row["bytes"] != len(payload) or row["sha256"] != actual):
                raise ProductionError("release_manifest_file_mismatch", {"path": name})
            verified += 1
        if manifest.get("source_bytes") != sum(row["bytes"] for row in source_rows.values()):
            raise ProductionError("release_source_bytes_mismatch")
        if manifest.get("generated_bytes") != sum(row["bytes"] for row in generated_rows.values()):
            raise ProductionError("release_generated_bytes_mismatch")
        try:
            project = tomllib.loads(archive.read("pyproject.toml").decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ProductionError("release_pyproject_malformed") from exc
        if project.get("project", {}).get("name") != "surface-interop":
            raise ProductionError("release_project_identity")
        if project.get("project", {}).get("version") != manifest.get("version"):
            raise ProductionError("release_project_version")
        version_text = archive.read("estate_lab/VERSION").decode("utf-8").strip()
        if version_text != manifest.get("version"):
            raise ProductionError("release_version_binding")
        sbom_bytes = archive.read("SBOM.spdx.json")
        sbom = _strict_json_bytes(sbom_bytes, label="SBOM.spdx.json")
        if not isinstance(sbom, dict) or sbom.get("spdxVersion") != "SPDX-2.3":
            raise ProductionError("release_sbom_format")
        return {
            "status": "PASS",
            "release_id": expected_release_id,
            "version": manifest.get("version"),
            "verified_files": verified,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "sbom_sha256": hashlib.sha256(sbom_bytes).hexdigest(),
            "archive_sha256": sha256_file(archive_path),
        }

def _check(check_id: str, operation: Any) -> DoctorCheck:
    try:
        value = operation()
        if isinstance(value, tuple):
            detail, evidence = value
        else:
            detail, evidence = str(value), {}
        return DoctorCheck(check_id, "passed", detail, dict(evidence))
    except Exception as exc:
        return DoctorCheck(
            check_id,
            "failed",
            f"{type(exc).__name__}: {exc}",
            {},
        )


def production_doctor(source_root: Path | None = None) -> dict[str, Any]:
    root = (source_root or Path(__file__).resolve().parents[1]).resolve()
    package = root / "estate_lab"

    def python_check() -> tuple[str, dict[str, Any]]:
        version = sys.version_info[:3]
        if version < (3, 10):
            raise ProductionError("python_version_unsupported", {"version": version})
        return platform.python_version(), {"minimum": "3.10"}

    def atomic_check() -> str:
        with tempfile.TemporaryDirectory(prefix="surface-interop-doctor-") as temp_dir:
            path = Path(temp_dir) / "atomic.json"
            atomic_write_json(path, {"status": "PASS"})
            if strict_load_json(path, max_bytes=1024) != {"status": "PASS"}:
                raise ProductionError("atomic_roundtrip_failed")
        return "same-directory fsync and replace passed"

    def spec_check() -> tuple[str, dict[str, Any]]:
        from .floor import load_floor_spec

        spec = load_floor_spec(package / "fixtures" / "floor" / "floor.example.json")
        return spec.floor_version, {"floor_id": spec.floor_id}

    def adapter_check() -> tuple[str, dict[str, Any]]:
        from .floor import load_floor_adapter, load_floor_spec

        spec = load_floor_spec(package / "fixtures" / "floor" / "floor.example.json")
        adapter = load_floor_adapter(
            package / "fixtures" / "floor" / "reference-adapter" / "adapter.json",
            spec,
        )
        argv = [sys.executable, str(adapter.source_path.parent / "adapter.py")]
        pins = verify_pinned_entrypoint(adapter, argv)
        return adapter.adapter_version, {"adapter_id": adapter.adapter_id, "pinned": pins}

    def schema_check() -> tuple[str, dict[str, Any]]:
        schemas = sorted((package / "schemas").glob("*.schema.json"))
        contracts = sorted((package / "contracts").glob("*.schema.json"))
        documents = [*schemas, *contracts]
        if not documents:
            raise ProductionError("schema_set_missing")
        for path in documents:
            strict_load_json(path, max_bytes=2 * 1024 * 1024)
        return (
            f"{len(schemas)} protocol schemas + {len(contracts)} production contracts",
            {"sha256": sha256_hex([sha256_file(path) for path in documents])},
        )

    def version_check() -> tuple[str, dict[str, Any]]:
        version = (package / "VERSION").read_text(encoding="utf-8").strip()
        init_text = (package / "__init__.py").read_text(encoding="utf-8")
        if f'__version__ = "{version}"' not in init_text:
            raise ProductionError("version_drift", {"VERSION": version})
        return version, {}

    def symlink_check() -> str:
        for path in _iter_release_source_files(root):
            if path.is_symlink():
                raise ProductionError("release_symlink", {"path": str(path)})
        return "no public release source is a symlink"

    checks = [
        _check("python-version", python_check),
        _check("atomic-publication", atomic_check),
        _check("floor-specification", spec_check),
        _check("reference-adapter-supply-pin", adapter_check),
        _check("schema-set", schema_check),
        _check("version-consistency", version_check),
        _check("release-source-symlinks", symlink_check),
    ]
    status = "PASS" if all(item.status == "passed" for item in checks) else "FAIL"
    report: dict[str, Any] = {
        "format": DOCTOR_FORMAT,
        "status": status,
        "version": (package / "VERSION").read_text(encoding="utf-8").strip()
        if (package / "VERSION").is_file()
        else "unknown",
        "platform": {
            "system": platform.system().lower(),
            "machine": platform.machine().lower(),
            "python": platform.python_version(),
        },
        "checks": [asdict(item) for item in checks],
    }
    report["report_id"] = stable_id("surfdoctor1", report, length=32)
    return report



def _redact_support_value(value: Any, *, root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _redact_support_value(item, root=root) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_support_value(item, root=root) for item in value]
    if isinstance(value, tuple):
        return [_redact_support_value(item, root=root) for item in value]
    if isinstance(value, str):
        replacements = [
            (str(root), "<source-root>"),
            (str(Path.home()), "<home>"),
            (tempfile.gettempdir(), "<temp>"),
        ]
        result = value
        for needle, replacement in replacements:
            if needle:
                result = result.replace(needle, replacement)
        return result
    return value

def build_support_bundle(
    output_path: Path,
    *,
    source_root: Path | None = None,
    report_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    root = (source_root or Path(__file__).resolve().parents[1]).resolve()
    reports = []
    for path in report_paths:
        if not path.is_file() or path.is_symlink():
            reports.append({"name": path.name, "status": "missing"})
            continue
        reports.append(
            {
                "name": path.name,
                "status": "present",
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload: dict[str, Any] = {
        "format": SUPPORT_FORMAT,
        "doctor": _redact_support_value(production_doctor(root), root=root),
        "reports": reports,
        "disclosure": (
            "No environment values, request bodies, response bodies, absolute source paths, "
            "tokens, or credentials are included."
        ),
    }
    payload["support_id"] = stable_id("surfsupport1", payload, length=32)
    atomic_write_json(output_path, payload, mode=0o600)
    return payload
