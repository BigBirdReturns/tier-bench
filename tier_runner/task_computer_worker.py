"""Shared-filesystem worker for independent Task Computer planner and critic seats."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time
from typing import Any

from .playwright_computer_common import (
    PlaywrightComputerError,
    atomic_json,
    canonical,
    hash_file,
    hash_json,
    load_json,
    now_utc,
    safe_id,
    without_hash,
)
from .task_computer_protocol import validate_proposal
from .task_computer_team import (
    CRITIC_REQUEST_SCHEMA,
    validate_critic_response,
)

WORKER_RECEIPT_SCHEMA = "tier-bench/task-computer-worker-receipt@1"


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _exclusive_json(path: Path, value: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def _request_hash_valid(role: str, value: dict[str, Any]) -> bool:
    field = "packet_sha256" if role == "planner" else "request_sha256"
    observed = value.get(field)
    return isinstance(observed, str) and observed == hash_json(without_hash(value, field))


class ExchangeWorker:
    """Claim immutable planner or critic requests and publish one validated response."""

    def __init__(
        self,
        *,
        exchange_root: Path,
        role: str,
        command: str | list[str],
        seat_id: str,
        gpu_attestation: dict[str, Any] | None = None,
        timeout_seconds: float = 600.0,
        reclaim_after_seconds: float = 3600.0,
    ):
        if role not in {"planner", "critic"}:
            raise PlaywrightComputerError("worker role must be planner or critic")
        self.exchange_root = exchange_root.resolve()
        self.role = role
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise PlaywrightComputerError("worker command cannot be empty")
        self.seat_id = safe_id(seat_id, "seat_id")
        self.gpu_attestation = gpu_attestation
        self.timeout_seconds = timeout_seconds
        self.reclaim_after_seconds = reclaim_after_seconds

    def _requests(self) -> list[Path]:
        return sorted(
            path
            for path in self.exchange_root.glob(
                f"*/{self.role}/requests/*.json"
            )
            if path.is_file()
        )

    def _paths(self, request: Path) -> tuple[Path, Path, Path]:
        role_root = request.parent.parent
        stem = request.stem
        return (
            role_root / "claims" / f"{stem}.json",
            role_root / "responses" / f"{stem}.json",
            role_root / "receipts" / f"{stem}-{self.seat_id}.json",
        )

    def _reclaim_if_stale(self, claim: Path) -> None:
        if not claim.exists():
            return
        try:
            value = load_json(claim)
            claimed_at = _parse_time(str(value["claimed_at"]))
        except Exception:
            claimed_at = claim.stat().st_mtime
        if time.time() - claimed_at <= self.reclaim_after_seconds:
            return
        history = claim.parent / "history"
        history.mkdir(parents=True, exist_ok=True)
        os.replace(claim, history / f"{claim.stem}-{time.time_ns()}.json")

    def _claim(self, request: Path, request_value: dict[str, Any]) -> Path | None:
        claim, response, _ = self._paths(request)
        if response.exists():
            return None
        self._reclaim_if_stale(claim)
        value: dict[str, Any] = {
            "schema": "tier-bench/task-computer-worker-claim@1",
            "role": self.role,
            "seat_id": self.seat_id,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "request_path": str(request),
            "request_file_sha256": hash_file(request),
            "request_identity": request_value.get(
                "packet_sha256" if self.role == "planner" else "request_sha256"
            ),
            "claimed_at": now_utc(),
            "gpu_attestation": self.gpu_attestation,
        }
        value["claim_sha256"] = hash_json(value)
        return claim if _exclusive_json(claim, value) else None

    def _invoke(self, request_value: dict[str, Any]) -> dict[str, Any]:
        environment = dict(os.environ)
        environment["TIER_TASK_ROLE"] = self.role
        environment["TIER_TASK_SEAT_ID"] = self.seat_id
        gpu = (self.gpu_attestation or {}).get("gpu")
        if isinstance(gpu, dict) and gpu.get("uuid"):
            environment["CUDA_VISIBLE_DEVICES"] = str(gpu["uuid"])
        try:
            result = subprocess.run(
                self.command,
                input=canonical(request_value),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PlaywrightComputerError(f"worker command failed: {exc}") from exc
        if result.returncode:
            raise PlaywrightComputerError(
                f"worker command exited {result.returncode}: "
                + result.stderr.decode("utf-8", errors="replace")[-4000:]
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PlaywrightComputerError(
                "worker command returned invalid JSON: "
                + result.stdout.decode("utf-8", errors="replace")[-4000:]
            ) from exc
        if not isinstance(value, dict):
            raise PlaywrightComputerError("worker command output must be a JSON object")
        return value

    def _validate_response(
        self, request_value: dict[str, Any], value: dict[str, Any]
    ) -> dict[str, Any]:
        if self.role == "planner":
            return validate_proposal(value, request_value)
        result = validate_critic_response(value, request_value)
        result["seat"] = {
            "seat_id": self.seat_id,
            "hostname": socket.gethostname(),
            "gpu_attestation": self.gpu_attestation,
        }
        result["response_sha256"] = hash_json(
            without_hash(result, "response_sha256")
        )
        return result

    def process(self, request: Path) -> dict[str, Any] | None:
        request_value = load_json(request)
        if not isinstance(request_value, dict) or not _request_hash_valid(
            self.role, request_value
        ):
            raise PlaywrightComputerError(f"request identity does not verify: {request}")
        if self.role == "critic" and request_value.get("schema") != CRITIC_REQUEST_SCHEMA:
            raise PlaywrightComputerError(f"critic request has the wrong schema: {request}")
        claim = self._claim(request, request_value)
        if claim is None:
            return None
        _, response, receipt_path = self._paths(request)
        started = time.perf_counter()
        error: str | None = None
        response_value: dict[str, Any] | None = None
        try:
            response_value = self._validate_response(
                request_value, self._invoke(request_value)
            )
            atomic_json(response, response_value)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        receipt: dict[str, Any] = {
            "schema": WORKER_RECEIPT_SCHEMA,
            "role": self.role,
            "seat_id": self.seat_id,
            "hostname": socket.gethostname(),
            "request_path": str(request),
            "request_file_sha256": hash_file(request),
            "claim_path": str(claim),
            "claim_file_sha256": hash_file(claim),
            "response_path": str(response) if response.exists() else None,
            "response_file_sha256": hash_file(response) if response.exists() else None,
            "response_identity": (
                response_value.get(
                    "proposal_sha256" if self.role == "planner" else "response_sha256"
                )
                if response_value
                else None
            ),
            "gpu_attestation": self.gpu_attestation,
            "completed_at": now_utc(),
            "duration_seconds": round(time.perf_counter() - started, 3),
            "status": "completed" if error is None else "failed",
            "error": error,
        }
        receipt["receipt_sha256"] = hash_json(receipt)
        atomic_json(receipt_path, receipt)
        claim.unlink(missing_ok=True)
        if error is not None:
            raise PlaywrightComputerError(error)
        return receipt

    def process_once(self) -> dict[str, Any]:
        completed: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for request in self._requests():
            try:
                receipt = self.process(request)
                if receipt is not None:
                    completed.append(receipt)
            except Exception as exc:
                failures.append(
                    {"request": str(request), "error": f"{type(exc).__name__}: {exc}"}
                )
        return {
            "ok": not failures,
            "role": self.role,
            "seat_id": self.seat_id,
            "completed": completed,
            "failures": failures,
        }

    def run_loop(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            self.process_once()
            time.sleep(poll_seconds)
