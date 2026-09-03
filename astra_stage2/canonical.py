"""Strict JSON, canonical serialization, hashing, and atomic file helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


class Stage2Error(ValueError):
    """Raised when a Stage 2 object violates a fail-closed contract."""


def _reject_constant(value: str) -> None:
    raise Stage2Error(f"non-finite JSON constant is forbidden: {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise Stage2Error(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def strict_json_loads(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise Stage2Error(f"invalid JSON: {exc}") from exc


def strict_json_load(path: Path) -> Any:
    return strict_json_loads(path.read_text(encoding="utf-8"))


def strict_jsonl_load(path: Path) -> list[Any]:
    rows: list[Any] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(strict_json_loads(line))
            except Stage2Error as exc:
                raise Stage2Error(f"{path}:{line_number}: {exc}") from exc
    return rows


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise Stage2Error(f"non-finite number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_finite(child, f"{path}[{index}]")


def canonical_json_bytes(value: Any) -> bytes:
    _assert_finite(value)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise Stage2Error(f"object is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    _assert_finite(value)
    return (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_object(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324, Git object identity


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path: Path, value: Any, *, pretty: bool = True) -> None:
    write_bytes_atomic(path, pretty_json_bytes(value) if pretty else canonical_json_bytes(value) + b"\n")


def write_jsonl_atomic(path: Path, rows: Iterable[Any]) -> None:
    write_bytes_atomic(path, b"".join(canonical_json_bytes(row) + b"\n" for row in rows))


def without_field(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key != field}
