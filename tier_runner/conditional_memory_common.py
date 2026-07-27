"""Shared canonicalization, hashing, time, and file helpers for the memory lab."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MemoryLabError(ValueError):
    """The conditional-memory experiment violated a declared contract."""


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
        raise MemoryLabError(f"cannot read JSON {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(path)


def append_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical(row).decode("utf-8"))


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoryLabError(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise MemoryLabError(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MemoryLabError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def safe_id(value: Any, label: str, *, limit: int = 120) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_ID.fullmatch(result):
        raise MemoryLabError(f"{label} contains unsafe characters")
    return result


def need_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise MemoryLabError(f"{label} must be boolean")
    return value


def need_int(
    value: Any,
    label: str,
    *,
    low: int = 0,
    high: int = 10**12,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MemoryLabError(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(
    value: Any,
    label: str,
    *,
    low: float = 0.0,
    high: float = 10**18,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryLabError(f"{label} must be a number")
    result = float(value)
    if not low <= result <= high:
        raise MemoryLabError(f"{label} must be between {low} and {high}")
    return result


def choice(value: Any, label: str, allowed: set[str]) -> str:
    result = need_text(value, label, limit=80)
    if result not in allowed:
        raise MemoryLabError(f"{label} must be one of {sorted(allowed)}")
    return result


def digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256.fullmatch(result):
        raise MemoryLabError(f"{label} must be lowercase SHA-256")
    return result


def without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field, None)
    return result
