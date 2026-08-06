"""Shared contracts for the HALO3 Cell Zero home-lab qualification floor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

LAB_SCHEMA = "tier-bench/halo3-cell-zero-lab@1"
FINGERPRINT_SCHEMA = "tier-bench/model-fingerprint-contract@1"
PLAN_SCHEMA = "tier-bench/halo3-cell-zero-plan@1"
PROOF_MATRIX_SCHEMA = "tier-bench/halo3-cell-zero-proof-matrix@1"
OBSERVATION_SCHEMA = "tier-bench/halo3-cell-zero-observation@1"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Halo3Error(ValueError):
    """A HALO3 lab contract or deterministic product failed closed."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Halo3Error(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    except OSError as exc:
        raise Halo3Error(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise Halo3Error(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(rendered.encode("utf-8"))
    temporary.replace(path)


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Halo3Error(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise Halo3Error(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Halo3Error(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def optional_text(value: Any, label: str, *, limit: int = 4000) -> str | None:
    if value is None:
        return None
    return need_text(value, label, limit=limit)


def safe_id(value: Any, label: str, *, limit: int = 240) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_ID.fullmatch(result):
        raise Halo3Error(
            f"{label} contains unsafe characters; allowed: letters, digits, dot, underscore, "
            "colon, slash, and dash"
        )
    return result


def need_boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise Halo3Error(f"{label} must be boolean")
    return value


def need_integer(value: Any, label: str, low: int = 0, high: int = 10**15) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Halo3Error(f"{label} must be an integer between {low} and {high}")
    return value


def need_number(
    value: Any,
    label: str,
    *,
    low: float | None = None,
    high: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Halo3Error(f"{label} must be numeric")
    result = float(value)
    if low is not None and result < low:
        raise Halo3Error(f"{label} must be >= {low}")
    if high is not None and result > high:
        raise Halo3Error(f"{label} must be <= {high}")
    return result


def need_digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256.fullmatch(result):
        raise Halo3Error(f"{label} must be lowercase SHA-256")
    return result


def exact_keys(
    row: dict[str, Any],
    required: Iterable[str],
    optional: Iterable[str],
    label: str,
) -> None:
    required_set = set(required)
    optional_set = set(optional)
    missing = sorted(required_set - row.keys())
    extra = sorted(row.keys() - required_set - optional_set)
    if missing:
        raise Halo3Error(f"{label} is missing required keys: {missing}")
    if extra:
        raise Halo3Error(f"{label} contains unknown keys: {extra}")


def id_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [safe_id(item, label) for item in rows]
    if len(result) != len(set(result)):
        raise Halo3Error(f"{label} contains duplicates")
    return sorted(result)


def text_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    rows = need_array(value, label, nonempty=nonempty)
    result = [need_text(item, label) for item in rows]
    if len(result) != len(set(result)):
        raise Halo3Error(f"{label} contains duplicates")
    return result


def unique_by_id(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        if identifier in result:
            raise Halo3Error(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result
