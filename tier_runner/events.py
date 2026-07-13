from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


CATEGORIES = {"brief", "clarification", "rescue", "review", "acceptance", "other"}


class InterventionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    for row in rows:
        event = row.get("event")
        iid = row.get("intervention_id")
        if not isinstance(iid, str) or not iid:
            raise InterventionError("every intervention event needs intervention_id")
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
            current = None
        else:
            raise InterventionError(f"unknown intervention event {event!r}")
    return current


def validate_events(path: Path, require_closed: bool = True) -> list[dict]:
    rows = load_events(path)
    current = open_intervention(rows)
    if require_closed and current is not None:
        raise InterventionError(f"unclosed intervention {current['intervention_id']}")
    return rows


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    })
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
    })
