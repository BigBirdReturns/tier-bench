"""Shared contracts for the Universal Model Floor Observatory."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

REGISTRY_SCHEMA = "tier-bench/model-floor-registry@1"
SOURCE_CONFIG_SCHEMA = "tier-bench/model-floor-sources@1"
OBSERVATION_SCHEMA = "tier-bench/model-floor-observation@1"
SNAPSHOT_SCHEMA = "tier-bench/model-floor-source-snapshot@1"
FLOOR_CONFIG_SCHEMA = "tier-bench/model-floor-config@1"
FLOOR_REPORT_SCHEMA = "tier-bench/model-floor-report@1"
DELTA_REPORT_SCHEMA = "tier-bench/model-delta-report@1"
SYNC_RECEIPT_SCHEMA = "tier-bench/model-floor-sync@1"
IDENTITY_AUDIT_SCHEMA = "tier-bench/model-identity-audit@1"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ModelFloorError(RuntimeError):
    """A model-floor artifact or operation violated its frozen contract."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            payload = handle.read(chunk_bytes)
            if not payload:
                break
            digest.update(payload)
    return digest.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelFloorError(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise ModelFloorError(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ModelFloorError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def optional_text(value: Any, label: str, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    return need_text(value, label, limit=limit)


def safe_id(value: Any, label: str, *, limit: int = 200) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_ID.fullmatch(result):
        raise ModelFloorError(
            f"{label} contains unsafe characters; allowed: letters, digits, dot, "
            "underscore, colon, slash, and dash"
        )
    return result


def need_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ModelFloorError(f"{label} must be boolean")
    return value


def need_int(value: Any, label: str, *, low: int = 0, high: int = 10**12) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ModelFloorError(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(
    value: Any,
    label: str,
    *,
    low: float = -10**18,
    high: float = 10**18,
    allow_none: bool = False,
) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelFloorError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ModelFloorError(f"{label} must be finite and between {low} and {high}")
    return result


def need_digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256.fullmatch(result):
        raise ModelFloorError(f"{label} must be lowercase SHA-256")
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelFloorError(f"cannot read JSON from {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    if missing_ok and not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ModelFloorError(f"cannot read JSONL from {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelFloorError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ModelFloorError(f"{path}:{line_number}: JSONL row must be an object")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    temporary.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    if not materialized:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in materialized:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return len(materialized)


def parse_time(value: Any, label: str) -> datetime:
    text = need_text(value, label, limit=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelFloorError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ModelFloorError(f"{label} must include timezone")
    return parsed


def unique_by_id(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        if identifier in result:
            raise ModelFloorError(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result


def nested_get(value: Any, path: str | None, default: Any = None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return default
            current = current[index]
        else:
            return default
    return current


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
