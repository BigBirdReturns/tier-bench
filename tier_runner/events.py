from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


CATEGORIES = {"brief", "clarification", "rescue", "review", "acceptance", "other"}
ARMS = {"arm_a", "arm_b", "arm_c"}
EVENT_FIELDS = {
    "arm", "category", "event", "event_sha256", "intervention_id",
    "previous_event_sha256", "task_id", "ts",
}


class InterventionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(row: dict) -> bytes:
    return (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()


def event_hash(row: dict) -> str:
    unsigned = {key: value for key, value in row.items() if key != "event_sha256"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InterventionError(f"invalid event JSON at line {number}") from exc
        if not isinstance(row, dict):
            raise InterventionError(f"event line {number} is not an object")
        rows.append(row)
    return rows


def open_intervention(rows: list[dict]) -> dict | None:
    current: dict | None = None
    seen: set[str] = set()
    previous_hash: str | None = None
    previous_ts: datetime | None = None
    for row in rows:
        if set(row) != EVENT_FIELDS:
            raise InterventionError("intervention event fields do not match the frozen schema")
        event = row.get("event")
        iid = row.get("intervention_id")
        try:
            uuid.UUID(iid)
        except (AttributeError, ValueError) as exc:
            raise InterventionError(
                "every intervention event needs a UUID intervention_id"
            ) from exc
        if row.get("arm") not in ARMS or row.get("category") not in CATEGORIES:
            raise InterventionError("intervention arm/category is invalid")
        if not isinstance(row.get("task_id"), str) or not row["task_id"]:
            raise InterventionError("intervention task_id must be a non-empty string")
        try:
            timestamp = datetime.fromisoformat(str(row.get("ts", "")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise InterventionError("intervention timestamp must be ISO-8601") from exc
        if timestamp.tzinfo is None:
            raise InterventionError("intervention timestamp must include a timezone")
        if previous_ts is not None and timestamp < previous_ts:
            raise InterventionError("intervention timestamps are out of order")
        if row.get("previous_event_sha256") != previous_hash:
            raise InterventionError("intervention event hash chain is broken")
        if row.get("event_sha256") != event_hash(row):
            raise InterventionError("intervention event hash is invalid")
        if event == "start":
            if current is not None or iid in seen:
                raise InterventionError("overlapping or reused intervention start")
            current = row
            seen.add(iid)
        elif event == "stop":
            if current is None or current["intervention_id"] != iid:
                raise InterventionError("stop does not name the globally open intervention")
            if row.get("task_id") != current.get("task_id") or row.get("arm") != current.get("arm"):
                raise InterventionError("stop task/arm does not match start")
            if row.get("category") != current.get("category"):
                raise InterventionError("stop category does not match start")
            current = None
        else:
            raise InterventionError(f"unknown intervention event {event!r}")
        previous_hash = row["event_sha256"]
        previous_ts = timestamp
    return current


def validate_events(path: Path, require_closed: bool = True) -> list[dict]:
    rows = load_events(path)
    current = open_intervention(rows)
    if require_closed and current is not None:
        raise InterventionError(f"unclosed intervention {current['intervention_id']}")
    return rows


def _append(path: Path, row: dict, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row["previous_event_sha256"] = rows[-1]["event_sha256"] if rows else None
    row["event_sha256"] = event_hash(row)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def start(path: Path, task_id: str, arm: str, category: str) -> str:
    if category not in CATEGORIES:
        raise InterventionError(f"category must be one of {sorted(CATEGORIES)}")
    rows = load_events(path)
    if open_intervention(rows) is not None:
        raise InterventionError("another intervention is already open")
    iid = str(uuid.uuid4())
    _append(path, {
        "arm": arm,
        "category": category,
        "event": "start",
        "intervention_id": iid,
        "task_id": task_id,
        "ts": _now(),
    }, rows)
    return iid


def stop(path: Path, intervention_id: str) -> None:
    rows = load_events(path)
    current = open_intervention(rows)
    if current is None or current["intervention_id"] != intervention_id:
        raise InterventionError("intervention_id is not the globally open intervention")
    _append(path, {
        "arm": current["arm"],
        "category": current["category"],
        "event": "stop",
        "intervention_id": intervention_id,
        "task_id": current["task_id"],
        "ts": _now(),
    }, rows)
