"""Shared contracts for the MENACE edge qualification campaign."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

MANIFEST_SCHEMA = "tier-bench/menace-edge-campaign@1"
PLAN_SCHEMA = "tier-bench/menace-edge-plan@1"
OBSERVATION_SCHEMA = "tier-bench/menace-edge-observation@1"
REPORT_SCHEMA = "tier-bench/menace-edge-report@1"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

MANDATORY_METRICS = (
    "wall_energy_mwh",
    "gpu_energy_mwh",
    "elapsed_ms",
    "time_to_first_useful_ms",
    "human_active_ms",
    "external_bytes_in",
    "external_bytes_avoided",
    "accepted_products",
    "rejected_products",
    "consequential_misses",
    "role_seconds_served",
    "average_wall_power_mw",
    "model_calls",
    "operator_interventions",
    "recovery_ms",
)

MANDATORY_OUTCOMES = (
    "useful_product_produced",
    "human_accepted",
    "survival_floor_retained",
    "authority_widened",
    "history_preserved",
    "conflict_disclosed",
    "human_disposition_recorded",
    "gpu_required_for_basic_state",
    "wan_required_for_basic_state",
)

BASE_STREAM_ENVELOPE_FIELDS = {
    "event_id",
    "source_identity",
    "source_type",
    "observed_at",
    "received_at",
    "payload_schema",
    "payload_digest",
    "freshness",
    "lineage",
    "transport",
    "authority_scope",
}


class EdgeError(ValueError):
    """The campaign, plan, observation, or report violated its contract."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def need_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EdgeError(f"{label} must be an object")
    return value


def need_array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise EdgeError(f"{label} must be an array{suffix}")
    return value


def need_text(value: Any, label: str, *, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise EdgeError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def optional_text(value: Any, label: str, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    return need_text(value, label, limit=limit)


def safe_id(value: Any, label: str, *, limit: int = 160) -> str:
    result = need_text(value, label, limit=limit)
    if not SAFE_ID.fullmatch(result):
        raise EdgeError(
            f"{label} contains unsafe characters; allowed: letters, digits, dot, underscore, "
            "colon, slash, and dash"
        )
    return result


def need_integer(value: Any, label: str, low: int = 0, high: int = 10**15) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise EdgeError(f"{label} must be an integer between {low} and {high}")
    return value


def need_boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EdgeError(f"{label} must be boolean")
    return value


def need_digest(value: Any, label: str) -> str:
    result = need_text(value, label, limit=64)
    if not SHA256.fullmatch(result):
        raise EdgeError(f"{label} must be lowercase SHA-256")
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
        raise EdgeError(f"{label} is missing required keys: {missing}")
    if extra:
        raise EdgeError(f"{label} contains unknown keys: {extra}")


def unique_by_id(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        if identifier in result:
            raise EdgeError(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EdgeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    except OSError as exc:
        raise EdgeError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EdgeError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def fraction_record(numerator: int, denominator: int, unit: str) -> dict[str, Any] | None:
    if denominator <= 0:
        return None
    reduced = Fraction(numerator, denominator)
    return {
        "numerator": reduced.numerator,
        "denominator": reduced.denominator,
        "unit": unit,
    }


@dataclass(frozen=True)
class TreatmentTotals:
    planned_cells: int
    measured_cells: int
    accepted_products: int
    rejected_products: int
    consequential_misses: int
    wall_energy_mwh: int
    gpu_energy_mwh: int
    human_active_ms: int
    external_bytes_in: int
    external_bytes_avoided: int
    role_seconds_served: int
    operator_interventions: int
    max_recovery_ms: int
