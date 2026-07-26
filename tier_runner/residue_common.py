"""Shared contracts and helpers for Frontier Residue Refinery."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

from .desk_common import DeskError, as_float, canonical

CAMPAIGN_SCHEMA = "tier-bench/frontier-residue-campaign@1"
CANDIDATE_SCHEMA = "tier-bench/frontier-residue-candidate@1"
CAMPAIGN_MODES = {"local_first", "survey"}
CAMPAIGN_TERMINAL = {
    "CLEARED",
    "COMPLETED",
    "EXHAUSTED",
    "INCONCLUSIVE",
    "BUDGET_BLOCKED",
    "CANCELED",
    "ERROR",
}
TASK_TERMINAL = {"ACCEPTED", "REJECTED", "ERROR", "CANCELED", "INTERRUPTED"}
ROUTE_CLASSES = {"local", "remote_open_weight", "remote_closed", "remote_unknown"}
SOURCE_ACCESS = {
    "source_and_weights",
    "weights",
    "runtime_source",
    "api_only",
    "subscription_only",
    "unknown",
}
CAPABILITY_BASES = {"measured", "hypothesis", "unmeasured"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def hash_json(value: Any) -> str:
    return hashlib.sha256((canonical(value) + "\n").encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def required_text(value: Any, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise DeskError(f"{label} is required and must be at most {limit:,} characters")
    return text


def optional_cost(value: Any, label: str) -> float | None:
    if value is None:
        return None
    return as_float(value, label, 0, 1_000_000)


def normalize_schedule(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeskError("scheduled_for must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DeskError("scheduled_for must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def task_outcome(task_state: str) -> str:
    if task_state == "ACCEPTED":
        return "pass"
    if task_state == "REJECTED":
        return "fail"
    return "error"
