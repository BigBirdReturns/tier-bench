"""Shared contracts for the Kimi K3 Open-Weight Observatory."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from typing import Any, Iterator

OBSERVATORY_SCHEMA = "tier-bench/kimi3-observatory@1"
MODEL_SCAN_SCHEMA = "tier-bench/kimi3-model-scan@1"
TENSOR_CENSUS_SCHEMA = "tier-bench/kimi3-tensor-census@1"
DISSECTION_PLAN_SCHEMA = "tier-bench/kimi3-dissection-plan@1"
BASELINE_SCHEMA = "tier-bench/kimi3-frozen-baseline@1"
COMMUNITY_CONFIG_SCHEMA = "tier-bench/kimi3-community-watch@1"
COMMUNITY_ITEM_SCHEMA = "tier-bench/kimi3-community-item@1"
COMMUNITY_SYNC_SCHEMA = "tier-bench/kimi3-community-sync@1"
CLAIM_SCHEMA = "tier-bench/kimi3-community-claim@1"
FUSION_SCHEMA = "tier-bench/kimi3-hypothesis-queue@1"
SCHEDULE_SCHEMA = "tier-bench/kimi3-windows-schedule@1"
EXECUTION_BUNDLE_SCHEMA = "tier-bench/kimi3-execution-bundle@1"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
PARTIAL_SUFFIXES = {
    ".aria2",
    ".crdownload",
    ".download",
    ".incomplete",
    ".part",
    ".partial",
    ".tmp",
}


class KimiObservatoryError(ValueError):
    """A Kimi observatory contract or runtime boundary failed closed."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_stream(path: Path, *, block_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KimiObservatoryError(f"{label} must be a JSON object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise KimiObservatoryError(f"{label} must be a JSON array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise KimiObservatoryError(
            f"{label} must be a non-empty string of at most {limit} characters"
        )
    return value.strip()


def optional_text(value: Any, label: str, *, limit: int = 2000) -> str | None:
    if value is None:
        return None
    return need_text(value, label, limit=limit)


def need_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise KimiObservatoryError(f"{label} must be boolean")
    return value


def need_int(
    value: Any,
    label: str,
    *,
    low: int = 0,
    high: int = 2**63 - 1,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise KimiObservatoryError(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(
    value: Any,
    label: str,
    *,
    low: float = 0.0,
    high: float = 1e30,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KimiObservatoryError(f"{label} must be numeric")
    result = float(value)
    if not low <= result <= high:
        raise KimiObservatoryError(f"{label} must be between {low} and {high}")
    return result


def safe_id(value: Any, label: str) -> str:
    result = need_text(value, label, limit=160)
    if not SAFE_ID_RE.fullmatch(result):
        raise KimiObservatoryError(
            f"{label} contains unsafe characters; allowed: letters, digits, dot, "
            "underscore, colon, slash, and dash"
        )
    return result


def need_digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256_RE.fullmatch(result):
        raise KimiObservatoryError(f"{label} must be lowercase SHA-256")
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KimiObservatoryError(f"cannot read JSON {path}: {exc}") from exc


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_json(path: Path | None, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    if path is None:
        print(payload.decode("utf-8"), end="")
        return
    atomic_write_bytes(path, payload)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise KimiObservatoryError(
                    f"invalid JSONL at {path}:{line_number}: {exc}"
                ) from exc
            rows.append(need_object(value, f"{path}:{line_number}"))
    return rows


def relative_posix(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise KimiObservatoryError(f"{path} is outside {root}") from exc
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise KimiObservatoryError(f"unsafe relative path: {relative}")
    return pure.as_posix()


def is_partial_download(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def stable_file(path: Path, *, stable_age_seconds: int, current_time: float | None = None) -> bool:
    if is_partial_download(path):
        return False
    stat = path.stat()
    current = time.time() if current_time is None else current_time
    return current - stat.st_mtime >= stable_age_seconds


@contextmanager
def exclusive_lock(
    path: Path,
    *,
    stale_after_seconds: int = 12 * 60 * 60,
) -> Iterator[None]:
    """A small cross-platform create-exclusive lock with stale-lock recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "created_at": now_utc(),
        "created_unix": time.time(),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        try:
            existing = load_json(path)
            created = float(existing.get("created_unix", 0.0))
        except (KimiObservatoryError, TypeError, ValueError):
            created = 0.0
        if created and time.time() - created <= stale_after_seconds:
            raise KimiObservatoryError(f"observatory is already locked: {path}")
        path.unlink(missing_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        os.write(descriptor, canonical_bytes(payload))
        os.fsync(descriptor)
        os.close(descriptor)
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
