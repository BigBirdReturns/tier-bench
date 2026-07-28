"""Canonical storage and append-only evidence helpers for Playwright computers."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVENT_SCHEMA = "tier-bench/playwright-computer-event@1"


class PlaywrightComputerError(RuntimeError):
    """The browser computer violated its declared execution contract."""


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaywrightComputerError(f"cannot read JSON {path}: {exc}") from exc


def atomic_bytes(path: Path, value: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_bytes(value)
    if mode is not None and os.name != "nt":
        temporary.chmod(mode)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any, *, mode: int | None = None) -> None:
    atomic_bytes(path, canonical(value), mode=mode)


def safe_id(value: Any, label: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PlaywrightComputerError(
            f"{label} must be a non-empty string of at most {limit} characters"
        )
    result = value.strip()
    if not SAFE_ID.fullmatch(result):
        raise PlaywrightComputerError(f"{label} contains unsafe characters")
    return result


def safe_relative_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PlaywrightComputerError(f"{label} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise PlaywrightComputerError(f"{label} must be relative to the computer root")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PlaywrightComputerError(f"{label} escapes the computer root") from exc
    return resolved


def without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field, None)
    return result


class EventLedger:
    """Single-writer, hash-chained JSONL event history for one browser computer."""

    def __init__(self, path: Path, computer_id: str):
        self.path = path
        self.computer_id = safe_id(computer_id, "computer_id")
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PlaywrightComputerError(
                    f"event ledger line {number} is invalid JSON"
                ) from exc
            if not isinstance(value, dict):
                raise PlaywrightComputerError(f"event ledger line {number} is not an object")
            rows.append(value)
        return rows

    def append(
        self,
        kind: str,
        *,
        state_id: str | None = None,
        action_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind = safe_id(kind, "event kind")
        with self.lock:
            rows = self._rows()
            previous = rows[-1]["event_sha256"] if rows else None
            event: dict[str, Any] = {
                "schema": EVENT_SCHEMA,
                "seq": len(rows) + 1,
                "ts": now_utc(),
                "computer_id": self.computer_id,
                "kind": kind,
                "state_id": state_id,
                "action_id": action_id,
                "detail": detail or {},
                "previous_event_sha256": previous,
            }
            event["event_sha256"] = hash_json(event)
            with self.path.open("ab") as handle:
                handle.write(canonical(event))
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def verify(self) -> dict[str, Any]:
        rows = self._rows()
        errors: list[str] = []
        previous: str | None = None
        for index, row in enumerate(rows, 1):
            if row.get("schema") != EVENT_SCHEMA:
                errors.append(f"event {index} has the wrong schema")
            if row.get("seq") != index:
                errors.append(f"event {index} has a non-contiguous sequence")
            if row.get("computer_id") != self.computer_id:
                errors.append(f"event {index} belongs to another computer")
            if row.get("previous_event_sha256") != previous:
                errors.append(f"event {index} has the wrong previous hash")
            observed = row.get("event_sha256")
            expected = hash_json(without_hash(row, "event_sha256"))
            if observed != expected:
                errors.append(f"event {index} hash does not verify")
            previous = observed
        return {
            "ok": not errors,
            "events": len(rows),
            "head_sha256": previous,
            "errors": errors,
        }

    def after(self, sequence: int) -> list[dict[str, Any]]:
        if sequence < 0:
            raise PlaywrightComputerError("event sequence must be non-negative")
        return [row for row in self._rows() if int(row.get("seq", 0)) > sequence]


class ExclusiveLease:
    """A fail-closed process lease used by the browser daemon and human takeover."""

    def __init__(self, path: Path):
        self.path = path

    def claim(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise PlaywrightComputerError(f"lease is already held: {self.path}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(canonical(value))
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.path.unlink(missing_ok=True)
            raise

    def replace(self, value: dict[str, Any]) -> None:
        if not self.path.exists():
            raise PlaywrightComputerError(f"lease does not exist: {self.path}")
        atomic_json(self.path, value, mode=0o600)

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        value = load_json(self.path)
        return value if isinstance(value, dict) else None

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


def append_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        for row in rows:
            handle.write(canonical(row))
        handle.flush()
        os.fsync(handle.fileno())
