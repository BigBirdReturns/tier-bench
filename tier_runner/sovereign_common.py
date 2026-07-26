"""Shared contracts for the Sovereign Desktop Execution Plane."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

PLANE_SCHEMA = "tier-bench/sovereign-desktop-plane@1"
PLAN_SCHEMA = "tier-bench/sovereign-desktop-plan@1"
CONTEXT_RECEIPT_SCHEMA = "tier-bench/sovereign-context-pack@1"
CACHE_RECEIPT_SCHEMA = "tier-bench/sovereign-kv-cache-receipt@1"
CAMPAIGN_SCHEMA = "tier-bench/frontier-residue-campaign@1"

RESOURCE_KINDS = {"gpu", "cpu", "ram", "storage", "network", "quota"}
EXECUTION_CLASSES = {"local", "remote_open_weight", "remote_closed", "remote_unknown"}
SOURCE_ACCESS = {
    "source_and_weights",
    "weights",
    "runtime_source",
    "api_only",
    "subscription_only",
    "unknown",
}
PRIVACY_POLICIES = {"local_only", "sovereign_preferred", "any"}
BLOCK_STABILITIES = {"estate", "campaign", "job", "ephemeral"}
BLOCK_STABILITY_ORDER = {"estate": 0, "campaign": 1, "job": 2, "ephemeral": 3}
BLOCK_KINDS = {"source", "instruction", "memory", "tool_schema", "retrieval", "compaction"}
CACHE_TIERS = {"gpu", "ram", "disk", "remote"}
CACHE_MODES = {"none", "prefix", "persistent_slot", "external_kv"}
CAMPAIGN_MODES = {"local_first", "survey"}

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PlaneError(ValueError):
    """A manifest, context pack, cache receipt, or plan violated its contract."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlaneError(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise PlaneError(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PlaneError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def optional_text(value: Any, label: str, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    return need_text(value, label, limit=limit)


def safe_id(value: Any, label: str, *, limit: int = 120) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_ID.fullmatch(result):
        raise PlaneError(
            f"{label} contains unsafe characters; allowed: letters, digits, dot, underscore, "
            "colon, slash, and dash"
        )
    return result


def safe_filename(value: Any, label: str, *, limit: int = 160) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_FILENAME.fullmatch(result):
        raise PlaneError(
            f"{label} must be a basename containing only letters, digits, dot, underscore, and dash"
        )
    return result


def need_integer(value: Any, label: str, low: int = 0, high: int = 10**12) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PlaneError(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(value: Any, label: str, low: float = 0.0, high: float = 10**12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlaneError(f"{label} must be a number")
    result = float(value)
    if not low <= result <= high:
        raise PlaneError(f"{label} must be between {low} and {high}")
    return result


def optional_number(
    value: Any, label: str, low: float = 0.0, high: float = 10**12
) -> float | None:
    if value is None:
        return None
    return need_number(value, label, low, high)


def need_boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PlaneError(f"{label} must be boolean")
    return value


def need_digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256.fullmatch(result):
        raise PlaneError(f"{label} must be lowercase SHA-256")
    return result


def normalize_scope(value: Any, label: str) -> str:
    text = need_text(value, label, limit=500).replace("\\", "/")
    directory = text.endswith("/")
    pure = PurePosixPath(text.rstrip("/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] == ".git":
        raise PlaneError(f"{label} must be a safe repository-relative path")
    return pure.as_posix() + ("/" if directory else "")


def unique_by_id(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        if identifier in result:
            raise PlaneError(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaneError(f"cannot read {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
