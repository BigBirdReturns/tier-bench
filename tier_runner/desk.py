from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import uuid
import webbrowser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .desk_ui import HTML


DESK_SCHEMA = "tier-bench/monster-wrangler@1"
DATABASE_SCHEMA = "tier-bench/monster-wrangler-db@2"
TASK_STATES = {
    "DRAFT",
    "QUEUED",
    "RUNNING",
    "ACCEPTED",
    "REJECTED",
    "ERROR",
    "CANCELED",
    "INTERRUPTED",
}
TERMINAL_STATES = {"ACCEPTED", "REJECTED", "ERROR", "CANCELED", "INTERRUPTED"}
FAILURE_STATES = {"REJECTED", "ERROR"}
CAPABILITY_BASES = {"measured", "hypothesis", "unmeasured"}
QUOTA_BASES = {"direct", "derived", "operator", "unknown"}
ESCALATION_MODES = {"operator", "next-route-on-error", "next-route-on-failure"}
TANK_KINDS = {"subscription", "api", "local", "manual"}
SETTINGS_DEFAULTS: dict[str, Any] = {
    "paused": False,
    "pause_reason": "",
    "max_workers": 1,
    "daily_task_limit": 8,
    "daily_cost_limit_usd": 10.0,
    "daily_token_limit": 0,
    "stop_on_failure": True,
    "budget_timezone": "America/Los_Angeles",
    "poll_interval_ms": 750,
}
MAX_BODY_BYTES = 2_000_000
MAX_LOG_TAIL_BYTES = 500_000
MAX_TASK_BYTES = 200_000
MAX_ACCEPTANCE_BYTES = 40_000
MAX_ROUTES = 12
MAX_DEPENDENCIES = 100
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SAFE_ARM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class DeskError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteDecision:
    route: dict[str, Any] | None
    statuses: list[dict[str, Any]]
    reason: str


@dataclass
class ExecutionResult:
    state: str
    receipt: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    receipt_path: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    exit_code: int | None = None
    error: str | None = None
    evidence_complete: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_load(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_timestamp(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value in (None, ""):
        if nullable:
            return None
        raise DeskError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeskError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DeskError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise DeskError(f"{label} must be boolean")


def _parse_int(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise DeskError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DeskError(f"{label} must be an integer") from exc
    if parsed < low or parsed > high:
        raise DeskError(f"{label} must be between {low} and {high}")
    return parsed


def _parse_float(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise DeskError(f"{label} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DeskError(f"{label} must be a number") from exc
    if not low <= parsed <= high:
        raise DeskError(f"{label} must be between {low} and {high}")
    return parsed


def _safe_identifier(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID.fullmatch(text):
        raise DeskError(
            f"{label} must start with an alphanumeric character and contain only "
            "letters, digits, dot, underscore, and dash"
        )
    return text


def _safe_relpath(raw: Any, label: str = "repository path") -> str:
    value = str(raw or "").strip().replace("\\", "/")
    pure = PurePosixPath(value.rstrip("/"))
    if not value or pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise DeskError(f"unsafe {label}: {raw!r}")
    if pure.parts[0] == ".git":
        raise DeskError(f".git cannot be used as {label}")
    return pure.as_posix() + ("/" if value.endswith("/") else "")


def _normalize_files(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace(",", "\n").splitlines()
    elif isinstance(value, list):
        values = value
    else:
        raise DeskError("files must be a list or newline-separated string")
    files = sorted({_safe_relpath(item, "file scope") for item in values if str(item).strip()})
    if not files:
        raise DeskError("at least one file scope is required")
    if len(files) > 100:
        raise DeskError("a task may contain at most 100 file scopes")
    return files


def _normalize_dependencies(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        raise DeskError("depends_on must be a list or comma-separated string")
    dependencies = sorted(
        {
            _safe_identifier(item, "dependency id")
            for item in values
            if str(item).strip()
        }
    )
    if len(dependencies) > MAX_DEPENDENCIES:
        raise DeskError(f"a task may have at most {MAX_DEPENDENCIES} dependencies")
    return dependencies


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise DeskError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def resolve_repo(repo: Path) -> Path:
    result = _run_git(repo.expanduser(), "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _git_common_dir(repo: Path) -> Path:
    value = _run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    path = Path(value)
    return (repo / path).resolve() if not path.is_absolute() else path.resolve()


def resolve_state_dir(repo: Path, state_dir: Path | None) -> Path:
    root = state_dir.expanduser().resolve() if state_dir else _git_common_dir(repo) / "tier-desk"
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_runs_dir(repo: Path) -> Path:
    root = _git_common_dir(repo) / "tier-runs" / "monster-wrangler"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _committed_repo_path(repo: Path, raw: Any, label: str) -> str:
    relative = _safe_relpath(raw, label).rstrip("/")
    path = (repo / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise DeskError(f"{label} must live inside the managed repository") from exc
    if not path.is_file():
        raise DeskError(f"{label} does not exist: {relative}")
    result = _run_git(repo, "cat-file", "-e", f"HEAD:{relative}", check=False)
    if result.returncode:
        raise DeskError(f"{label} must be committed at the repository HEAD: {relative}")
    return relative


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _timezone(value: Any) -> str:
    name = str(value or "").strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise DeskError(f"unknown IANA timezone: {name}") from exc
    return name


class DeskStore:
    def __init__(self, path: Path, repo: Path):
        self.path = path
        self.repo = repo
        self._local = threading.local()
        self._init_database()
        self.recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 30000")
            self._local.connection = connection
        return connection

    def _init_database(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tanks (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                headroom_percent REAL,
                observed_at TEXT,
                snapshot_max_age_seconds INTEGER NOT NULL,
                reset_at TEXT,
                hard_cap_percent REAL NOT NULL,
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                task TEXT NOT NULL,
                files_json TEXT NOT NULL,
                acceptance TEXT NOT NULL,
                routes_json TEXT NOT NULL,
                priority INTEGER NOT NULL,
                state TEXT NOT NULL,
                scheduled_for TEXT,
                approval_required INTEGER NOT NULL DEFAULT 0,
                approved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                escalation_mode TEXT NOT NULL,
                last_run_id TEXT,
                last_error TEXT,
                blocked_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS dependencies (
                task_id TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                PRIMARY KEY (task_id, depends_on),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on) REFERENCES tasks(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                state TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                output_dir TEXT NOT NULL,
                log_path TEXT NOT NULL,
                receipt_path TEXT,
                receipt_json TEXT,
                verify_json TEXT,
                route_json TEXT NOT NULL,
                tank_id TEXT,
                cost_usd REAL NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                pid INTEGER,
                exit_code INTEGER,
                error TEXT,
                evidence_complete INTEGER NOT NULL DEFAULT 0,
                UNIQUE (task_id, attempt),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                task_id TEXT,
                run_id TEXT,
                detail_json TEXT NOT NULL,
                previous_event_sha256 TEXT,
                event_sha256 TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_state_priority
                ON tasks(state, priority DESC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_tank_started ON runs(tank_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq DESC);
            """
        )
        existing = db.execute("SELECT value FROM meta WHERE key='database_schema'").fetchone()
        if existing is not None and existing["value"] == "tier-bench/monster-wrangler-db@1":
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "evidence_complete" not in columns:
                db.execute(
                    "ALTER TABLE runs ADD COLUMN evidence_complete INTEGER NOT NULL DEFAULT 0"
                )
        elif existing is not None and existing["value"] != DATABASE_SCHEMA:
            raise DeskError(
                f"unsupported Monster Wrangler database schema {existing['value']!r}; "
                f"expected {DATABASE_SCHEMA!r}"
            )
        existing_repo = db.execute("SELECT value FROM meta WHERE key='repo'").fetchone()
        if existing_repo is not None and Path(existing_repo["value"]).resolve() != self.repo:
            raise DeskError(
                "Monster Wrangler state belongs to a different repository: "
                f"{existing_repo['value']}"
            )
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('database_schema', ?)",
            (DATABASE_SCHEMA,),
        )
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('repo', ?)",
            (str(self.repo),),
        )
        event_count = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        event_head = db.execute(
            "SELECT event_sha256 FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('event_count', ?)",
            (str(event_count),),
        )
        db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('event_head_sha256', ?)",
            (event_head["event_sha256"] if event_head else "",),
        )
        for key, value in SETTINGS_DEFAULTS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings(key, value_json) VALUES(?, ?)",
                (key, canonical_json(value)),
            )

    def _event(
        self,
        kind: str,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        detail: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        db = connection or self._connect()
        previous_row = db.execute(
            "SELECT event_sha256 FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        previous = previous_row["event_sha256"] if previous_row else None
        event = {
            "ts": utc_now(),
            "kind": kind,
            "task_id": task_id,
            "run_id": run_id,
            "detail": detail or {},
            "previous_event_sha256": previous,
        }
        digest = _sha(event)
        db.execute(
            """
            INSERT INTO events(
                ts, kind, task_id, run_id, detail_json, previous_event_sha256, event_sha256
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["ts"],
                kind,
                task_id,
                run_id,
                canonical_json(event["detail"]),
                previous,
                digest,
            ),
        )
        count = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('event_count', ?)",
            (str(count),),
        )
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('event_head_sha256', ?)",
            (digest,),
        )
        return {**event, "event_sha256": digest}

    def verify_event_chain(self) -> list[str]:
        rows = self._connect().execute("SELECT * FROM events ORDER BY seq ASC").fetchall()
        errors: list[str] = []
        previous: str | None = None
        for row in rows:
            event = {
                "ts": row["ts"],
                "kind": row["kind"],
                "task_id": row["task_id"],
                "run_id": row["run_id"],
                "detail": _json_load(row["detail_json"], {}),
                "previous_event_sha256": row["previous_event_sha256"],
            }
            if row["previous_event_sha256"] != previous:
                errors.append(f"event {row['seq']} has a broken predecessor link")
            expected = _sha(event)
            if row["event_sha256"] != expected:
                errors.append(f"event {row['seq']} hash mismatch")
            previous = row["event_sha256"]
        meta = {
            row["key"]: row["value"]
            for row in self._connect().execute(
                "SELECT key, value FROM meta WHERE key IN ('event_count','event_head_sha256')"
            ).fetchall()
        }
        if meta.get("event_count") != str(len(rows)):
            errors.append("event ledger count does not match its sealed metadata")
        if meta.get("event_head_sha256", "") != (previous or ""):
            errors.append("event ledger head does not match its sealed metadata")
        return errors

    def settings(self) -> dict[str, Any]:
        rows = self._connect().execute("SELECT key, value_json FROM settings").fetchall()
        values = {row["key"]: _json_load(row["value_json"], None) for row in rows}
        return {**SETTINGS_DEFAULTS, **values}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = set(SETTINGS_DEFAULTS)
        unknown = set(patch) - allowed
        if unknown:
            raise DeskError(f"unknown settings: {sorted(unknown)}")
        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            if key in {"paused", "stop_on_failure"}:
                normalized[key] = _parse_bool(value, key)
            elif key == "pause_reason":
                normalized[key] = str(value)[:500]
            elif key == "max_workers":
                normalized[key] = _parse_int(value, key, 1, 8)
            elif key == "daily_task_limit":
                normalized[key] = _parse_int(value, key, 1, 500)
            elif key == "daily_cost_limit_usd":
                normalized[key] = _parse_float(value, key, 0.0, 1_000_000.0)
            elif key == "daily_token_limit":
                normalized[key] = _parse_int(value, key, 0, 10**12)
            elif key == "budget_timezone":
                normalized[key] = _timezone(value)
            elif key == "poll_interval_ms":
                normalized[key] = _parse_int(value, key, 200, 5_000)
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            for key, value in normalized.items():
                db.execute(
                    "INSERT OR REPLACE INTO settings(key, value_json) VALUES(?, ?)",
                    (key, canonical_json(value)),
                )
            self._event("settings.updated", detail=normalized, connection=db)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return self.settings()

    def pause(self, reason: str) -> None:
        self.update_settings({"paused": True, "pause_reason": reason[:500]})

    def resume(self) -> None:
        self.update_settings({"paused": False, "pause_reason": ""})

    def recover_interrupted(self) -> None:
        db = self._connect()
        rows = db.execute("SELECT id, last_run_id FROM tasks WHERE state='RUNNING'").fetchall()
        if not rows:
            return
        now = utc_now()
        db.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                run_id = row["last_run_id"]
                if run_id:
                    db.execute(
                        """
                        UPDATE runs SET state='INTERRUPTED', completed_at=?, error=?
                        WHERE id=? AND state='RUNNING'
                        """,
                        (now, "Monster Wrangler restarted before run completion", run_id),
                    )
                db.execute(
                    """
                    UPDATE tasks SET state='INTERRUPTED', updated_at=?, last_error=?,
                        blocked_reason=NULL WHERE id=?
                    """,
                    (now, "Monster Wrangler restarted before run completion", row["id"]),
                )
                self._event(
                    "task.interrupted",
                    task_id=row["id"],
                    run_id=run_id,
                    detail={"reason": "process restart"},
                    connection=db,
                )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    def _task_exists(self, task_id: str, db: sqlite3.Connection | None = None) -> bool:
        connection = db or self._connect()
        return (
            connection.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
            is not None
        )

    def _normalize_routes(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_routes = payload.get("routes")
        if raw_routes is None:
            raw_routes = [
                {
                    "label": payload.get("route_label") or "Primary route",
                    "manifest": payload.get("manifest", "pilot_backends.json"),
                    "arm": payload.get("arm", "arm_b"),
                    "tank_id": payload.get("tank_id"),
                    "capability_basis": payload.get("capability_basis", "unmeasured"),
                    "quota_basis": payload.get("quota_basis", "unknown"),
                }
            ]
        if not isinstance(raw_routes, list) or not raw_routes:
            raise DeskError("routes must be a non-empty list")
        if len(raw_routes) > MAX_ROUTES:
            raise DeskError(f"a task may have at most {MAX_ROUTES} routes")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_routes, 1):
            if not isinstance(raw, dict):
                raise DeskError(f"route {index} must be an object")
            route_id = _safe_identifier(raw.get("id") or f"route-{index}", f"route {index} id")
            if route_id in seen:
                raise DeskError(f"duplicate route id: {route_id}")
            seen.add(route_id)
            label = str(raw.get("label") or f"Route {index}").strip()
            if not label or len(label) > 120:
                raise DeskError(f"route {index} label must be 1 to 120 characters")
            manifest = _committed_repo_path(
                self.repo,
                raw.get("manifest", "pilot_backends.json"),
                f"route {index} backend manifest",
            )
            arm = str(raw.get("arm", "arm_b")).strip()
            if not SAFE_ARM.fullmatch(arm) or arm not in {"arm_a", "arm_b", "arm_c"}:
                raise DeskError(f"route {index} arm must be arm_a, arm_b, or arm_c")
            try:
                manifest_data = json.loads(
                    _run_git(self.repo, "show", f"HEAD:{manifest}").stdout
                )
            except json.JSONDecodeError as exc:
                raise DeskError(f"route {index} backend manifest is not valid JSON") from exc
            if not isinstance(manifest_data, dict) or manifest_data.get("schema") != (
                "tier-bench/pilot-backends@1"
            ):
                raise DeskError(
                    f"route {index} backend manifest has the wrong schema: {manifest}"
                )
            arms = manifest_data.get("arms")
            if not isinstance(arms, dict) or arm not in arms:
                raise DeskError(f"route {index} backend manifest has no {arm}: {manifest}")
            tank_id_raw = raw.get("tank_id")
            tank_id = (
                None
                if tank_id_raw in (None, "")
                else _safe_identifier(tank_id_raw, "tank id")
            )
            capability_basis = str(raw.get("capability_basis", "unmeasured"))
            if capability_basis not in CAPABILITY_BASES:
                raise DeskError(
                    f"route {index} capability_basis must be one of {sorted(CAPABILITY_BASES)}"
                )
            quota_basis = str(raw.get("quota_basis", "unknown"))
            if quota_basis not in QUOTA_BASES:
                raise DeskError(f"route {index} quota_basis must be one of {sorted(QUOTA_BASES)}")
            estimated = raw.get("estimated_max_cost_usd")
            estimated_cost = (
                None
                if estimated in (None, "")
                else _parse_float(estimated, "estimated_max_cost_usd", 0.0, 1_000_000.0)
            )
            result.append(
                {
                    "id": route_id,
                    "label": label,
                    "manifest": manifest,
                    "arm": arm,
                    "tank_id": tank_id,
                    "capability_basis": capability_basis,
                    "quota_basis": quota_basis,
                    "estimated_max_cost_usd": estimated_cost,
                }
            )
        return result

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title", "")).strip()
        task = str(payload.get("task", "")).strip()
        acceptance = str(payload.get("acceptance", "")).strip()
        if not title or len(title) > 160:
            raise DeskError("title is required and must be at most 160 characters")
        if not task or len(task.encode("utf-8")) > MAX_TASK_BYTES:
            raise DeskError(f"task is required and must be at most {MAX_TASK_BYTES:,} UTF-8 bytes")
        if not acceptance or len(acceptance.encode("utf-8")) > MAX_ACCEPTANCE_BYTES:
            raise DeskError(
                f"acceptance is required and must be at most {MAX_ACCEPTANCE_BYTES:,} UTF-8 bytes"
            )
        files = _normalize_files(payload.get("files"))
        dependencies = _normalize_dependencies(payload.get("depends_on"))
        routes = self._normalize_routes(payload)
        priority = _parse_int(payload.get("priority", 50), "priority", 0, 100)
        queue_now = _parse_bool(payload.get("queue_now", False), "queue_now")
        approval_required = _parse_bool(
            payload.get("approval_required", False), "approval_required"
        )
        escalation_mode = str(payload.get("escalation_mode", "operator"))
        if escalation_mode not in ESCALATION_MODES:
            raise DeskError(f"escalation_mode must be one of {sorted(ESCALATION_MODES)}")
        default_attempts = len(routes) if escalation_mode != "operator" else max(1, len(routes))
        max_attempts = _parse_int(
            payload.get("max_attempts", default_attempts), "max_attempts", 1, MAX_ROUTES
        )
        if max_attempts > len(routes):
            raise DeskError(
                "max_attempts cannot exceed the number of explicit routes; repeat a route "
                "entry to authorize another attempt on the same cartridge"
            )
        scheduled_for = _parse_timestamp(
            payload.get("scheduled_for"), "scheduled_for", nullable=True
        )
        task_id = _safe_identifier(
            payload.get("id") or "mw-" + uuid.uuid4().hex[:12], "task id"
        )
        if task_id in dependencies:
            raise DeskError("a task cannot depend on itself")
        state = "QUEUED" if queue_now and not approval_required else "DRAFT"
        now = utc_now()
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            if self._task_exists(task_id, db):
                raise DeskError(f"task already exists: {task_id}")
            missing = [dep for dep in dependencies if not self._task_exists(dep, db)]
            if missing:
                raise DeskError(f"unknown dependencies: {missing}")
            missing_tanks = [
                route["tank_id"]
                for route in routes
                if route["tank_id"]
                and db.execute("SELECT 1 FROM tanks WHERE id=?", (route["tank_id"],)).fetchone()
                is None
            ]
            if missing_tanks:
                raise DeskError(f"unknown route tanks: {sorted(set(missing_tanks))}")
            db.execute(
                """
                INSERT INTO tasks(
                    id, title, task, files_json, acceptance, routes_json, priority,
                    state, scheduled_for, approval_required, approved_at, created_at,
                    updated_at, max_attempts, escalation_mode
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    title,
                    task,
                    canonical_json(files),
                    acceptance,
                    canonical_json(routes),
                    priority,
                    state,
                    scheduled_for,
                    int(approval_required),
                    None,
                    now,
                    now,
                    max_attempts,
                    escalation_mode,
                ),
            )
            for dependency in dependencies:
                db.execute(
                    "INSERT INTO dependencies(task_id, depends_on) VALUES(?, ?)",
                    (task_id, dependency),
                )
            self._event(
                "task.created",
                task_id=task_id,
                detail={
                    "state": state,
                    "dependencies": dependencies,
                    "routes": [route["id"] for route in routes],
                    "approval_required": approval_required,
                },
                connection=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_task(task_id)
        assert result is not None
        return result

    def _dependencies_for(self, task_id: str) -> list[dict[str, str]]:
        rows = self._connect().execute(
            """
            SELECT d.depends_on AS id, t.state AS state, t.title AS title
            FROM dependencies d JOIN tasks t ON t.id=d.depends_on
            WHERE d.task_id=? ORDER BY d.depends_on
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _runs_for(self, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT * FROM runs WHERE task_id=? ORDER BY attempt DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [self._serialize_run(dict(row)) for row in rows]

    def _serialize_run(self, run: dict[str, Any]) -> dict[str, Any]:
        run["receipt"] = _json_load(run.pop("receipt_json", None), None)
        run["verification"] = _json_load(run.pop("verify_json", None), None)
        run["route"] = _json_load(run.pop("route_json", None), {})
        run["evidence_complete"] = bool(run.get("evidence_complete"))
        return run

    def _tank_map(self) -> dict[str, dict[str, Any]]:
        return {tank["id"]: tank for tank in self.list_tanks()}

    def _route_status(
        self,
        route: dict[str, Any],
        tanks: dict[str, dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        tank_id = route.get("tank_id")
        base = {"route": route, "eligible": True, "reason": "eligible", "tank": None}
        if not tank_id:
            return base
        tank = tanks.get(tank_id)
        base["tank"] = tank
        if tank is None:
            return {**base, "eligible": False, "reason": f"tank {tank_id} is missing"}
        if not tank["enabled"]:
            return {**base, "eligible": False, "reason": f"tank {tank_id} is disabled"}
        if tank["kind"] == "local":
            return base
        if tank["headroom_percent"] is None or tank["observed_at"] is None:
            return {
                **base,
                "eligible": False,
                "reason": f"tank {tank_id} has no current headroom snapshot",
            }
        observed = _timestamp(tank["observed_at"])
        age = (current - observed).total_seconds()
        if age > tank["snapshot_max_age_seconds"]:
            return {
                **base,
                "eligible": False,
                "reason": f"tank {tank_id} snapshot is stale",
            }
        reset_at = tank.get("reset_at")
        if reset_at and _timestamp(reset_at) <= current and observed < _timestamp(reset_at):
            return {
                **base,
                "eligible": False,
                "reason": f"tank {tank_id} reset passed after the last snapshot",
            }
        used_percent = 100.0 - float(tank["headroom_percent"])
        if used_percent >= float(tank["hard_cap_percent"]):
            return {
                **base,
                "eligible": False,
                "reason": (
                    f"tank {tank_id} is at {used_percent:.1f}% used, at or beyond its "
                    f"{tank['hard_cap_percent']:.1f}% cap"
                ),
            }
        return base

    def route_decision(
        self,
        task: dict[str, Any],
        tanks: dict[str, dict[str, Any]] | None = None,
    ) -> RouteDecision:
        routes = task.get("routes") or []
        if not routes:
            return RouteDecision(None, [], "task has no route")
        start = 0
        if int(task.get("attempt_count", 0)) > 0:
            row = self._connect().execute(
                "SELECT route_json FROM runs WHERE task_id=? ORDER BY attempt DESC LIMIT 1",
                (task["id"],),
            ).fetchone()
            last_route = _json_load(row["route_json"], {}) if row else {}
            last_id = last_route.get("id")
            for index, route in enumerate(routes):
                if route.get("id") == last_id:
                    start = index + 1
                    break
            else:
                start = min(int(task.get("attempt_count", 0)), len(routes))
        tank_map = tanks if tanks is not None else self._tank_map()
        statuses = []
        for index, route in enumerate(routes):
            status = self._route_status(route, tank_map)
            status["consumed"] = index < start
            statuses.append(status)
        candidates = statuses[start:]
        for status in candidates:
            if status["eligible"]:
                return RouteDecision(status["route"], statuses, "eligible route selected")
        reason = "; ".join(status["reason"] for status in candidates) or "no route remains"
        return RouteDecision(None, statuses, reason)

    def _serialize_task(
        self,
        task: dict[str, Any],
        include_runs: bool = False,
        tanks: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task["files"] = _json_load(task.pop("files_json", None), [])
        task["routes"] = _json_load(task.pop("routes_json", None), [])
        task["approval_required"] = bool(task["approval_required"])
        dependencies = self._dependencies_for(task["id"])
        task["dependencies"] = dependencies
        task["blocked_by"] = [dep for dep in dependencies if dep["state"] != "ACCEPTED"]
        decision = self.route_decision(task, tanks=tanks)
        task["next_route"] = None if task["state"] == "ACCEPTED" else decision.route
        task["route_statuses"] = decision.statuses
        task["route_blocked_reason"] = (
            decision.reason
            if decision.route is None and task["state"] not in {"ACCEPTED", "CANCELED"}
            else None
        )
        now = utc_now()
        task["schedule_ready"] = not task["scheduled_for"] or task["scheduled_for"] <= now
        task["ready"] = bool(
            task["state"] == "QUEUED"
            and not task["blocked_by"]
            and task["schedule_ready"]
            and decision.route is not None
        )
        if include_runs:
            task["runs"] = self._runs_for(task["id"])
        elif task.get("last_run_id"):
            row = self._connect().execute(
                "SELECT * FROM runs WHERE id=?", (task["last_run_id"],)
            ).fetchone()
            task["last_run"] = self._serialize_run(dict(row)) if row else None
        else:
            task["last_run"] = None
        return task

    def get_task(self, task_id: str, include_runs: bool = True) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return (
            self._serialize_task(
                dict(row), include_runs=include_runs, tanks=self._tank_map()
            )
            if row
            else None
        )

    def list_tasks(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            """
            SELECT * FROM tasks ORDER BY
            CASE state
                WHEN 'RUNNING' THEN 0 WHEN 'QUEUED' THEN 1 WHEN 'DRAFT' THEN 2
                WHEN 'INTERRUPTED' THEN 3 WHEN 'REJECTED' THEN 4 WHEN 'ERROR' THEN 5
                ELSE 6 END,
            priority DESC, created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tanks = self._tank_map()
        return [
            self._serialize_task(dict(row), include_runs=False, tanks=tanks)
            for row in rows
        ]

    def transition_task(self, task_id: str, action: str) -> dict[str, Any]:
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DeskError(f"unknown task: {task_id}")
            current = row["state"]
            now = utc_now()
            state = current
            if action == "approve":
                if current != "DRAFT":
                    raise DeskError("only a draft task can be approved")
                if int(row["attempt_count"]) >= int(row["max_attempts"]):
                    raise DeskError("task has exhausted its configured attempts")
                state = "QUEUED"
                db.execute(
                    """
                    UPDATE tasks SET state=?, approved_at=?, updated_at=?, last_error=NULL,
                        blocked_reason=NULL WHERE id=?
                    """,
                    (state, now, now, task_id),
                )
            elif action == "arm":
                if current != "DRAFT":
                    raise DeskError("only a draft task can be armed")
                if row["approval_required"] and not row["approved_at"]:
                    raise DeskError("task requires explicit approval before it can be armed")
                if int(row["attempt_count"]) >= int(row["max_attempts"]):
                    raise DeskError("task has exhausted its configured attempts")
                state = "QUEUED"
                db.execute(
                    """
                    UPDATE tasks SET state=?, updated_at=?, last_error=NULL, blocked_reason=NULL
                    WHERE id=?
                    """,
                    (state, now, task_id),
                )
            elif action == "hold":
                if current != "QUEUED":
                    raise DeskError("only a queued task can return to draft")
                state = "DRAFT"
                db.execute(
                    "UPDATE tasks SET state=?, updated_at=?, blocked_reason=NULL WHERE id=?",
                    (state, now, task_id),
                )
            elif action == "retry":
                if current not in {"REJECTED", "ERROR", "INTERRUPTED", "CANCELED"}:
                    raise DeskError("only failed, interrupted, or canceled work can be retried")
                if int(row["attempt_count"]) >= int(row["max_attempts"]):
                    raise DeskError("task has exhausted its configured attempts")
                if row["approval_required"] and not row["approved_at"]:
                    raise DeskError("task requires approval before retry")
                state = "QUEUED"
                db.execute(
                    """
                    UPDATE tasks SET state=?, updated_at=?, last_error=NULL, blocked_reason=NULL
                    WHERE id=?
                    """,
                    (state, now, task_id),
                )
            elif action == "cancel":
                if current == "RUNNING":
                    raise DeskError("running task cancellation must go through the scheduler")
                if current not in {"DRAFT", "QUEUED"}:
                    raise DeskError("only draft or queued work can be canceled")
                state = "CANCELED"
                db.execute(
                    """
                    UPDATE tasks SET state=?, updated_at=?, last_error=?, blocked_reason=NULL
                    WHERE id=?
                    """,
                    (state, now, "canceled by operator", task_id),
                )
            else:
                raise DeskError(f"unknown task action: {action}")
            self._event(
                f"task.{action}",
                task_id=task_id,
                run_id=row["last_run_id"],
                detail={"from": current, "to": state},
                connection=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        task = self.get_task(task_id)
        assert task is not None
        return task

    def ready_tasks(self, limit: int) -> list[dict[str, Any]]:
        now = utc_now()
        rows = self._connect().execute(
            """
            SELECT t.* FROM tasks t
            WHERE t.state='QUEUED'
              AND (t.scheduled_for IS NULL OR t.scheduled_for <= ?)
              AND NOT EXISTS (
                  SELECT 1 FROM dependencies d
                  JOIN tasks p ON p.id=d.depends_on
                  WHERE d.task_id=t.id AND p.state!='ACCEPTED'
              )
            ORDER BY t.priority DESC, t.created_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [self._serialize_task(dict(row), include_runs=False) for row in rows]

    def set_blocked_reason(self, task_id: str, reason: str | None) -> None:
        self._connect().execute(
            "UPDATE tasks SET blocked_reason=?, updated_at=? WHERE id=? AND state='QUEUED'",
            (reason[:1000] if reason else None, utc_now(), task_id),
        )

    def claim(
        self,
        task_id: str,
        route: dict[str, Any],
        runs_dir: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None or row["state"] != "QUEUED":
                db.execute("ROLLBACK")
                return None
            blocked = db.execute(
                """
                SELECT COUNT(*) AS n FROM dependencies d JOIN tasks p ON p.id=d.depends_on
                WHERE d.task_id=? AND p.state!='ACCEPTED'
                """,
                (task_id,),
            ).fetchone()["n"]
            if blocked:
                db.execute("ROLLBACK")
                return None
            if row["scheduled_for"] and row["scheduled_for"] > utc_now():
                db.execute("ROLLBACK")
                return None
            attempt = int(row["attempt_count"]) + 1
            if attempt > int(row["max_attempts"]):
                raise DeskError(f"task {task_id} has exhausted its configured attempts")
            run_id = f"{task_id}-a{attempt}-{uuid.uuid4().hex[:8]}"
            output_dir = runs_dir / task_id / f"attempt-{attempt:03d}-{run_id[-8:]}"
            log_path = output_dir.parent / f"{output_dir.name}.desk.log"
            output_dir.mkdir(parents=True, exist_ok=False)
            now = utc_now()
            db.execute(
                """
                INSERT INTO runs(
                    id, task_id, attempt, state, started_at, output_dir, log_path,
                    route_json, tank_id
                ) VALUES(?, ?, ?, 'RUNNING', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    attempt,
                    now,
                    str(output_dir),
                    str(log_path),
                    canonical_json(route),
                    route.get("tank_id"),
                ),
            )
            updated = db.execute(
                """
                UPDATE tasks SET state='RUNNING', updated_at=?, attempt_count=?, last_run_id=?,
                    last_error=NULL, blocked_reason=NULL WHERE id=? AND state='QUEUED'
                """,
                (now, attempt, run_id, task_id),
            )
            if updated.rowcount != 1:
                raise DeskError(f"task {task_id} lost its atomic claim")
            self._event(
                "task.claimed",
                task_id=task_id,
                run_id=run_id,
                detail={"attempt": attempt, "route": route},
                connection=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        task = self.get_task(task_id, include_runs=False)
        run_row = self._connect().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        assert task is not None and run_row is not None
        return task, self._serialize_run(dict(run_row))

    def set_run_pid(self, run_id: str, pid: int) -> None:
        self._connect().execute("UPDATE runs SET pid=? WHERE id=?", (pid, run_id))

    def complete_run(self, run_id: str, result: ExecutionResult) -> bool:
        if result.state not in TERMINAL_STATES:
            raise DeskError(f"invalid terminal run state: {result.state}")
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise DeskError(f"unknown run: {run_id}")
            if run["state"] != "RUNNING":
                db.execute("ROLLBACK")
                return False
            task_id = run["task_id"]
            now = utc_now()
            db.execute(
                """
                UPDATE runs SET state=?, completed_at=?, receipt_path=?, receipt_json=?,
                    verify_json=?,
                    cost_usd=?, input_tokens=?, output_tokens=?, cache_read_tokens=?,
                    cache_write_tokens=?, exit_code=?, error=?, evidence_complete=?
                    WHERE id=? AND state='RUNNING'
                """,
                (
                    result.state,
                    now,
                    result.receipt_path,
                    canonical_json(result.receipt) if result.receipt is not None else None,
                    (
                        canonical_json(result.verification)
                        if result.verification is not None
                        else None
                    ),
                    result.cost_usd,
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_write_tokens,
                    result.exit_code,
                    result.error,
                    int(result.evidence_complete),
                    run_id,
                ),
            )
            db.execute(
                """
                UPDATE tasks SET state=?, updated_at=?, last_error=?, blocked_reason=NULL
                WHERE id=? AND last_run_id=? AND state='RUNNING'
                """,
                (result.state, now, result.error, task_id, run_id),
            )
            self._event(
                "task.completed",
                task_id=task_id,
                run_id=run_id,
                detail={
                    "state": result.state,
                    "cost_usd": result.cost_usd,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                connection=db,
            )
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def requeue_after_failure(self, task_id: str, reason: str) -> bool:
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None or row["state"] not in FAILURE_STATES:
                db.execute("ROLLBACK")
                return False
            if int(row["attempt_count"]) >= int(row["max_attempts"]):
                db.execute("ROLLBACK")
                return False
            now = utc_now()
            db.execute(
                """
                UPDATE tasks SET state='QUEUED', updated_at=?, last_error=?, blocked_reason=NULL
                WHERE id=?
                """,
                (now, reason[:1000], task_id),
            )
            self._event(
                "task.escalated",
                task_id=task_id,
                run_id=row["last_run_id"],
                detail={"reason": reason, "next_attempt": int(row["attempt_count"]) + 1},
                connection=db,
            )
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def mark_canceled(self, task_id: str, reason: str = "canceled by operator") -> bool:
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT state, last_run_id FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise DeskError(f"unknown task: {task_id}")
            if row["state"] != "RUNNING":
                db.execute("ROLLBACK")
                return False
            now = utc_now()
            if row["last_run_id"]:
                db.execute(
                    """
                    UPDATE runs SET state='CANCELED', completed_at=?, error=?
                    WHERE id=? AND state='RUNNING'
                    """,
                    (now, reason, row["last_run_id"]),
                )
            db.execute(
                """
                UPDATE tasks SET state='CANCELED', updated_at=?, last_error=?, blocked_reason=NULL
                WHERE id=?
                """,
                (now, reason, task_id),
            )
            self._event(
                "task.canceled",
                task_id=task_id,
                run_id=row["last_run_id"],
                detail={"reason": reason},
                connection=db,
            )
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def upsert_tank(self, payload: dict[str, Any]) -> dict[str, Any]:
        tank_id = _safe_identifier(payload.get("id"), "tank id")
        existing = self._connect().execute("SELECT * FROM tanks WHERE id=?", (tank_id,)).fetchone()
        label = str(payload.get("label", existing["label"] if existing else tank_id)).strip()
        if not label or len(label) > 120:
            raise DeskError("tank label must be 1 to 120 characters")
        kind = str(payload.get("kind", existing["kind"] if existing else "manual"))
        if kind not in TANK_KINDS:
            raise DeskError(f"tank kind must be one of {sorted(TANK_KINDS)}")
        enabled = _parse_bool(
            payload.get("enabled", bool(existing["enabled"]) if existing else True), "enabled"
        )
        current_headroom = existing["headroom_percent"] if existing else None
        raw_headroom = payload.get("headroom_percent", current_headroom)
        headroom = (
            None
            if raw_headroom in (None, "")
            else _parse_float(raw_headroom, "headroom_percent", 0.0, 100.0)
        )
        current_observed = existing["observed_at"] if existing else None
        observed_at = _parse_timestamp(
            payload.get("observed_at", current_observed), "observed_at", nullable=True
        )
        if headroom is not None and observed_at is None:
            observed_at = utc_now()
        snapshot_max_age = _parse_int(
            payload.get(
                "snapshot_max_age_seconds",
                existing["snapshot_max_age_seconds"] if existing else 1800,
            ),
            "snapshot_max_age_seconds",
            30,
            604_800,
        )
        reset_at = _parse_timestamp(
            payload.get("reset_at", existing["reset_at"] if existing else None),
            "reset_at",
            nullable=True,
        )
        hard_cap = _parse_float(
            payload.get("hard_cap_percent", existing["hard_cap_percent"] if existing else 80.0),
            "hard_cap_percent",
            1.0,
            100.0,
        )
        notes = str(payload.get("notes", existing["notes"] if existing else ""))[:2000]
        now = utc_now()
        created_at = existing["created_at"] if existing else now
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                """
                INSERT OR REPLACE INTO tanks(
                    id, label, kind, enabled, headroom_percent, observed_at,
                    snapshot_max_age_seconds, reset_at, hard_cap_percent, notes,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tank_id,
                    label,
                    kind,
                    int(enabled),
                    headroom,
                    observed_at,
                    snapshot_max_age,
                    reset_at,
                    hard_cap,
                    notes,
                    created_at,
                    now,
                ),
            )
            self._event(
                "tank.updated" if existing else "tank.created",
                detail={
                    "tank_id": tank_id,
                    "kind": kind,
                    "enabled": enabled,
                    "headroom_percent": headroom,
                    "observed_at": observed_at,
                },
                connection=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_tank(tank_id)
        assert result is not None
        return result

    def get_tank(self, tank_id: str) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM tanks WHERE id=?", (tank_id,)).fetchone()
        if row is None:
            return None
        tank = dict(row)
        tank["enabled"] = bool(tank["enabled"])
        status = self._route_status(
            {"id": "tank-status", "tank_id": tank_id}, {tank_id: tank}
        )
        tank["eligible"] = status["eligible"]
        tank["status_reason"] = status["reason"]
        usage = self._connect().execute(
            """
            SELECT COUNT(*) AS runs, COALESCE(SUM(cost_usd), 0) AS cost_usd,
                COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens
            FROM runs WHERE tank_id=?
            """,
            (tank_id,),
        ).fetchone()
        tank["usage"] = dict(usage)
        return tank

    def list_tanks(self) -> list[dict[str, Any]]:
        rows = self._connect().execute("SELECT * FROM tanks ORDER BY label, id").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            tank = dict(row)
            tank["enabled"] = bool(tank["enabled"])
            result.append(tank)
        return result

    def _budget_window(self) -> tuple[str, str]:
        settings = self.settings()
        zone = ZoneInfo(settings["budget_timezone"])
        local_now = datetime.now(zone)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            local_end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def daily_usage(self) -> dict[str, Any]:
        start, end = self._budget_window()
        row = self._connect().execute(
            """
            SELECT COUNT(*) AS tasks, COALESCE(SUM(cost_usd), 0) AS cost_usd,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                   COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens
            FROM runs WHERE started_at >= ? AND started_at < ?
            """,
            (start, end),
        ).fetchone()
        result = dict(row)
        result["window_start"] = start
        result["window_end"] = end
        result["total_tokens"] = (
            int(result["input_tokens"])
            + int(result["output_tokens"])
            + int(result["cache_read_tokens"])
            + int(result["cache_write_tokens"])
        )
        return result

    def stats(self, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = self._connect().execute(
            "SELECT state, COUNT(*) AS n FROM tasks GROUP BY state"
        ).fetchall()
        states = {state: 0 for state in TASK_STATES}
        states.update({row["state"]: row["n"] for row in rows})
        totals = self._connect().execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                   COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                   SUM(CASE WHEN state='ACCEPTED' THEN 1 ELSE 0 END) AS accepted,
                   SUM(
                       CASE WHEN state IN ('ACCEPTED','REJECTED','ERROR') THEN 1 ELSE 0 END
                   ) AS judged
            FROM runs
            """
        ).fetchone()
        result = dict(totals)
        judged = int(result.pop("judged") or 0)
        accepted = int(result.pop("accepted") or 0)
        result["success_rate"] = accepted / judged if judged else None
        result["states"] = states
        result["daily"] = self.daily_usage()
        task_rows = tasks if tasks is not None else self.list_tasks()
        result["ready"] = sum(1 for task in task_rows if task["ready"])
        return result

    def events(self, limit: int = 120) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["detail"] = _json_load(item.pop("detail_json"), {})
            result.append(item)
        return result

    def snapshot(
        self,
        *,
        models: dict[str, Any] | None,
        active_runs: list[str],
        runs_dir: Path,
        started_at: str,
    ) -> dict[str, Any]:
        event_errors = self.verify_event_chain()
        tasks = self.list_tasks()
        tanks = [self.get_tank(tank["id"]) for tank in self.list_tanks()]
        return {
            "schema": DESK_SCHEMA,
            "repo": str(self.repo),
            "database": str(self.path),
            "runs_dir": str(runs_dir),
            "settings": self.settings(),
            "stats": self.stats(tasks),
            "tasks": tasks,
            "events": self.events(),
            "event_chain": {"ok": not event_errors, "errors": event_errors},
            "tanks": tanks,
            "models": models,
            "active_runs": active_runs,
            "started_at": started_at,
            "server_time": utc_now(),
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._serialize_run(dict(row)) if row else None


class TierRunExecutor:
    def __init__(self, repo: Path, store: DeskStore):
        self.repo = repo
        self.store = store
        self.runner_root = Path(__file__).resolve().parents[1]
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    def _invocation_files(
        self, task: dict[str, Any], run: dict[str, Any]
    ) -> tuple[Path, Path, Path, Path]:
        output_dir = Path(run["output_dir"])
        invocation_dir = output_dir.parent / f".{run['id']}.invocation"
        invocation_dir.mkdir(parents=True, exist_ok=False)
        task_path = invocation_dir / "task.txt"
        acceptance_path = invocation_dir / "acceptance.txt"
        files_path = invocation_dir / "files.json"
        task_path.write_text(task["task"], encoding="utf-8")
        acceptance_path.write_text(task["acceptance"], encoding="utf-8")
        files_path.write_text(canonical_json(task["files"]) + "\n", encoding="utf-8")
        return invocation_dir, task_path, acceptance_path, files_path

    def _command(
        self,
        task: dict[str, Any],
        run: dict[str, Any],
        task_path: Path,
        acceptance_path: Path,
        files_path: Path,
    ) -> list[str]:
        route = run["route"]
        return [
            sys.executable,
            "-m",
            "tier_runner.cli",
            "run",
            "--repo",
            str(self.repo),
            "--task-id",
            task["id"],
            "--task-file",
            str(task_path),
            "--acceptance-file",
            str(acceptance_path),
            "--files-file",
            str(files_path),
            "--backend-manifest",
            str(self.repo / route["manifest"]),
            "--arm",
            route["arm"],
            "--output-dir",
            run["output_dir"],
        ]

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
        if process is None or process.poll() is not None:
            return False
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=8)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        return True

    def run(self, task: dict[str, Any], run: dict[str, Any]) -> ExecutionResult:
        output_dir = Path(run["output_dir"])
        log_path = Path(run["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        invocation_dir, task_path, acceptance_path, files_path = self._invocation_files(task, run)
        command = self._command(task, run, task_path, acceptance_path, files_path)
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = str(self.runner_root)
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        process: subprocess.Popen[Any] | None = None
        exit_code: int | None = None
        try:
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                log.write("$ " + json.dumps(command, ensure_ascii=False) + "\n\n")
                log.flush()
                process = subprocess.Popen(
                    command,
                    cwd=self.runner_root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    **popen_kwargs,
                )
                self.store.set_run_pid(run["id"], process.pid)
                with self._lock:
                    self._processes[run["id"]] = process
                exit_code = process.wait()
        finally:
            with self._lock:
                self._processes.pop(run["id"], None)
            shutil.rmtree(invocation_dir, ignore_errors=True)

        receipt_path = output_dir / "receipt.json"
        receipt: dict[str, Any] | None = None
        if receipt_path.is_file():
            try:
                value = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt = value if isinstance(value, dict) else None
            except (OSError, json.JSONDecodeError):
                receipt = None
        if receipt is None:
            return ExecutionResult(
                state="ERROR",
                receipt_path=str(receipt_path) if receipt_path.exists() else None,
                exit_code=exit_code,
                error=f"tier run exited {exit_code} without a readable receipt",
            )

        verify_process = subprocess.run(
            [
                sys.executable,
                "-m",
                "tier_runner.cli",
                "verify",
                "--run-dir",
                str(output_dir),
            ],
            cwd=self.runner_root,
            capture_output=True,
            text=True,
            env=env,
        )
        try:
            verification = json.loads(verify_process.stdout)
        except json.JSONDecodeError:
            verification = {
                "ok": False,
                "errors": [
                    "tier verify returned non-JSON output",
                    verify_process.stdout[-2000:],
                    verify_process.stderr[-2000:],
                ],
            }
        state = str(receipt.get("state", "ERROR"))
        if state not in {"ACCEPTED", "REJECTED", "ERROR"}:
            state = "ERROR"
        if verify_process.returncode or verification.get("ok") is not True:
            state = "ERROR"
        call: dict[str, Any] = {}
        ledger_path = output_dir / "ledger.jsonl"
        if ledger_path.is_file():
            try:
                rows = [
                    line
                    for line in ledger_path.read_text(encoding="utf-8").splitlines()
                    if line
                ]
                if rows:
                    value = json.loads(rows[-1])
                    if isinstance(value, dict):
                        call = value
            except (OSError, json.JSONDecodeError):
                call = {}
        errors = receipt.get("errors") if isinstance(receipt.get("errors"), list) else []
        verify_errors = (
            verification.get("errors")
            if isinstance(verification, dict) and isinstance(verification.get("errors"), list)
            else []
        )
        error = "; ".join(str(item) for item in [*errors, *verify_errors] if item) or None
        return ExecutionResult(
            state=state,
            receipt=receipt,
            verification=verification,
            receipt_path=str(receipt_path),
            cost_usd=float(call.get("cost_usd", 0) or 0),
            input_tokens=int(call.get("input_tokens", 0) or 0),
            output_tokens=int(call.get("output_tokens", 0) or 0),
            cache_read_tokens=int(call.get("cache_read_tokens", 0) or 0),
            cache_write_tokens=int(call.get("cache_write_tokens", 0) or 0),
            exit_code=exit_code,
            error=error,
            evidence_complete=(
                verify_process.returncode == 0
                and verification.get("ok") is True
                and (
                    state in {"ACCEPTED", "REJECTED"}
                    or bool(
                        call
                        and isinstance(call.get("extra"), dict)
                        and call["extra"].get("telemetry_complete") is True
                    )
                )
            ),
        )


class DeskScheduler:
    def __init__(
        self,
        store: DeskStore,
        repo: Path,
        runs_dir: Path,
        executor: TierRunExecutor | Any | None = None,
    ):
        self.store = store
        self.repo = repo
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.executor = executor or TierRunExecutor(repo, store)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._active: dict[str, tuple[str, threading.Thread]] = {}
        self._thread = threading.Thread(
            target=self._loop, name="monster-wrangler-scheduler", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, cancel_running: bool = True) -> None:
        self._stop.set()
        self._wake.set()
        if cancel_running:
            with self._lock:
                run_ids = list(self._active)
            for run_id in run_ids:
                self.executor.cancel(run_id)
        if self._thread.is_alive():
            self._thread.join(timeout=10)

    def wake(self) -> None:
        self._wake.set()

    def active_run_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._active)

    def cancel_task(self, task_id: str) -> bool:
        task = self.store.get_task(task_id, include_runs=False)
        if task is None:
            raise DeskError(f"unknown task: {task_id}")
        run_id = task.get("last_run_id")
        if task["state"] == "RUNNING" and run_id:
            canceled = self.executor.cancel(run_id)
            self.store.mark_canceled(task_id)
            return canceled
        self.store.transition_task(task_id, "cancel")
        return True

    def emergency_stop(self) -> None:
        self.store.pause("emergency stop requested")
        with self._lock:
            active = list(self._active.items())
        for run_id, (task_id, _) in active:
            self.executor.cancel(run_id)
            self.store.mark_canceled(task_id, "emergency stop requested")
        self.wake()

    def _budget_allows(self) -> tuple[bool, str]:
        settings = self.store.settings()
        daily = self.store.daily_usage()
        if int(daily["tasks"]) >= int(settings["daily_task_limit"]):
            return False, "daily task limit reached"
        cost_limit = float(settings["daily_cost_limit_usd"])
        if cost_limit > 0 and float(daily["cost_usd"]) >= cost_limit:
            return False, "daily cost limit reached"
        token_limit = int(settings["daily_token_limit"])
        if token_limit > 0 and int(daily["total_tokens"]) >= token_limit:
            return False, "daily token limit reached"
        return True, ""

    def tick(self) -> None:
        settings = self.store.settings()
        with self._lock:
            active_count = len(self._active)
        if settings["paused"] or active_count >= int(settings["max_workers"]):
            return
        allowed, reason = self._budget_allows()
        if not allowed:
            self.store.pause(reason)
            return
        slots = int(settings["max_workers"]) - active_count
        for task in self.store.ready_tasks(max(slots * 4, slots)):
            if slots <= 0:
                break
            decision = self.store.route_decision(task)
            if decision.route is None:
                self.store.set_blocked_reason(task["id"], decision.reason)
                continue
            self.store.set_blocked_reason(task["id"], None)
            claimed = self.store.claim(task["id"], decision.route, self.runs_dir)
            if claimed is None:
                continue
            claimed_task, run = claimed
            thread = threading.Thread(
                target=self._execute,
                args=(claimed_task, run),
                name=f"monster-wrangler-run-{run['id']}",
                daemon=True,
            )
            with self._lock:
                self._active[run["id"]] = (claimed_task["id"], thread)
            thread.start()
            slots -= 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                try:
                    self.store.pause(f"scheduler error: {exc}")
                except Exception:
                    pass
            timeout = max(0.2, self.store.settings()["poll_interval_ms"] / 1000.0)
            self._wake.wait(timeout=timeout)
            self._wake.clear()

    def _should_escalate(self, task: dict[str, Any], result: ExecutionResult) -> bool:
        mode = task["escalation_mode"]
        if result.state not in FAILURE_STATES or not result.evidence_complete:
            return False
        if int(task["attempt_count"]) >= int(task["max_attempts"]):
            return False
        if mode == "next-route-on-failure":
            return True
        return mode == "next-route-on-error" and result.state == "ERROR"

    def _execute(self, task: dict[str, Any], run: dict[str, Any]) -> None:
        try:
            result = self.executor.run(task, run)
            current = self.store.get_task(task["id"], include_runs=False)
            if current and current["state"] == "CANCELED":
                return
            completed = self.store.complete_run(run["id"], result)
            if not completed:
                return
            current = self.store.get_task(task["id"], include_runs=False)
            if current and self._should_escalate(current, result):
                requeued = self.store.requeue_after_failure(
                    task["id"], f"automatic route escalation after {result.state}"
                )
                if requeued:
                    return
            settings = self.store.settings()
            if result.state in FAILURE_STATES and settings["stop_on_failure"]:
                self.store.pause(f"{task['id']} ended {result.state}; operator review required")
        except Exception as exc:
            result = ExecutionResult(state="ERROR", error=f"desk executor failure: {exc}")
            try:
                self.store.complete_run(run["id"], result)
                if self.store.settings()["stop_on_failure"]:
                    self.store.pause(f"{task['id']} hit an executor error")
            except Exception:
                pass
        finally:
            with self._lock:
                self._active.pop(run["id"], None)
            self.wake()


class DeskApplication:
    def __init__(
        self,
        repo: Path,
        state_dir: Path,
        *,
        executor: Any | None = None,
        allow_remote: bool = False,
    ):
        self.repo = repo
        self.state_dir = state_dir
        self.runs_dir = resolve_runs_dir(repo)
        self.store = DeskStore(state_dir / "monster-wrangler.sqlite3", repo)
        self.scheduler = DeskScheduler(self.store, repo, self.runs_dir, executor=executor)
        self.csrf_token = secrets.token_urlsafe(32)
        self.started_at = utc_now()
        self.allow_remote = allow_remote
        self._models_cache: tuple[float, dict[str, Any] | None] = (0.0, None)

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop(cancel_running=True)

    def model_catalog(self) -> dict[str, Any] | None:
        path = self.repo / "models.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if self._models_cache[0] == mtime:
            return self._models_cache[1]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
        summary = {
            "path": "models.json",
            "models": {
                name: {
                    key: value
                    for key, value in entry.items()
                    if key
                    in {
                        "provider",
                        "input_per_1M",
                        "output_per_1M",
                        "tier_ceiling",
                        "params_B",
                        "measured",
                    }
                }
                for name, entry in models.items()
                if isinstance(entry, dict)
            },
            "roles": raw.get("roles", {}),
            "composites": raw.get("composites", {}),
        }
        self._models_cache = (mtime, summary)
        return summary

    def backend_manifests(self) -> list[dict[str, Any]]:
        head = _run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        cached_head = getattr(self, "_manifest_catalog_head", None)
        if cached_head == head:
            return getattr(self, "_manifest_catalog", [])
        result = _run_git(
            self.repo,
            "grep",
            "-l",
            "tier-bench/pilot-backends@1",
            "HEAD",
            "--",
            "*.json",
            check=False,
        )
        paths: list[str] = []
        if result.returncode in {0, 1}:
            for line in result.stdout.splitlines():
                if line.startswith("HEAD:"):
                    paths.append(line[5:])
        catalog: list[dict[str, Any]] = []
        for relative in sorted(set(paths)):
            try:
                data = json.loads(_run_git(self.repo, "show", f"HEAD:{relative}").stdout)
            except (DeskError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("schema") != "tier-bench/pilot-backends@1":
                continue
            arms = data.get("arms") if isinstance(data.get("arms"), dict) else {}
            catalog.append(
                {
                    "path": relative,
                    "protocol_commit": data.get("protocol_commit"),
                    "arms": {
                        name: {
                            key: entry.get(key)
                            for key in (
                                "model_id",
                                "effort",
                                "surface",
                                "cost_basis",
                                "account",
                                "tier",
                            )
                        }
                        for name, entry in arms.items()
                        if isinstance(entry, dict)
                    },
                }
            )
        self._manifest_catalog_head = head
        self._manifest_catalog = catalog
        return catalog

    def snapshot(self) -> dict[str, Any]:
        snapshot = self.store.snapshot(
            models=self.model_catalog(),
            active_runs=self.scheduler.active_run_ids(),
            runs_dir=self.runs_dir,
            started_at=self.started_at,
        )
        snapshot["backend_manifests"] = self.backend_manifests()
        return snapshot


class DeskHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: DeskApplication):
        super().__init__(address, DeskHandler)
        self.app = app


class DeskHandler(BaseHTTPRequestHandler):
    server: DeskHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("monster-wrangler: " + fmt % args + "\n")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Cache-Control", "no-store")

    def _send_bytes(
        self,
        data: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        disposition: str | None = None,
    ) -> None:
        self.send_response(status.value)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(
            (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise DeskError("POST requests must use application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise DeskError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise DeskError("request body is too large")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise DeskError(f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise DeskError("request body must be a JSON object")
        return value

    def _require_host(self) -> None:
        if self.server.app.allow_remote:
            return
        host_header = self.headers.get("Host", "")
        host = host_header.rsplit(":", 1)[0].strip("[]").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise DeskError("non-loopback Host header refused")

    def _require_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        origin_host = (urlparse(origin).hostname or "").lower()
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").lower()
        if origin_host != host:
            raise DeskError("cross-origin request refused")

    def _require_token(self) -> None:
        supplied = self.headers.get("X-Tier-Desk-Token", "")
        if not secrets.compare_digest(supplied, self.server.app.csrf_token):
            raise DeskError("missing or invalid desk token")

    def _task_route(self, path: str) -> tuple[str, str] | None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
            return parts[2], parts[3]
        return None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            self._require_host()
            if path == "/":
                page = HTML.replace("__TIER_DESK_TOKEN__", self.server.app.csrf_token)
                self._send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/healthz":
                errors = self.server.app.store.verify_event_chain()
                self._json(
                    {
                        "ok": not errors,
                        "schema": DESK_SCHEMA,
                        "time": utc_now(),
                        "event_chain_errors": errors,
                    },
                    HTTPStatus.OK if not errors else HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            if path == "/api/state":
                self._json({"ok": True, "state": self.server.app.snapshot()})
                return
            if path == "/api/export":
                payload = self.server.app.snapshot()
                self._send_bytes(
                    (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                    disposition='attachment; filename="monster-wrangler-state.json"',
                )
                return
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                task = self.server.app.store.get_task(parts[2])
                if task is None:
                    self._error(HTTPStatus.NOT_FOUND, "task not found")
                else:
                    self._json({"ok": True, "task": task})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                run = self.server.app.store.get_run(parts[2])
                if run is None:
                    self._error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                artifact = parts[3]
                if artifact == "log":
                    queries = parse_qs(parsed.query)
                    try:
                        tail = int(queries.get("tail", [MAX_LOG_TAIL_BYTES])[0])
                    except ValueError as exc:
                        raise DeskError("tail must be an integer") from exc
                    tail = max(0, min(tail, MAX_LOG_TAIL_BYTES))
                    path_obj = Path(run["log_path"])
                    if not path_obj.is_file():
                        self._send_bytes(b"", "text/plain; charset=utf-8")
                        return
                    with path_obj.open("rb") as handle:
                        handle.seek(0, os.SEEK_END)
                        size = handle.tell()
                        handle.seek(max(0, size - tail))
                        data = handle.read()
                    self._send_bytes(data, "text/plain; charset=utf-8")
                    return
                if artifact == "receipt":
                    if run.get("receipt") is None:
                        self._error(HTTPStatus.NOT_FOUND, "receipt not available")
                    else:
                        self._json({"ok": True, "receipt": run["receipt"]})
                    return
                if artifact == "patch":
                    patch = Path(run["output_dir"]) / "change.patch"
                    if not patch.is_file():
                        self._error(HTTPStatus.NOT_FOUND, "patch not available")
                    else:
                        self._send_bytes(
                            patch.read_bytes(),
                            "text/x-diff; charset=utf-8",
                            disposition=f'attachment; filename="{parts[2]}.patch"',
                        )
                    return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except (DeskError, ValueError, OSError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            self._require_host()
            self._require_origin()
            self._require_token()
            body = self._body()
            if path == "/api/tasks":
                task = self.server.app.store.create_task(body)
                self.server.app.scheduler.wake()
                self._json({"ok": True, "task": task}, HTTPStatus.CREATED)
                return
            route = self._task_route(path)
            if route:
                task_id, action = route
                if action == "cancel":
                    self.server.app.scheduler.cancel_task(task_id)
                    task = self.server.app.store.get_task(task_id)
                elif action in {"approve", "arm", "hold", "retry"}:
                    task = self.server.app.store.transition_task(task_id, action)
                    self.server.app.scheduler.wake()
                else:
                    self._error(HTTPStatus.NOT_FOUND, "unknown task action")
                    return
                self._json({"ok": True, "task": task})
                return
            if path == "/api/tanks":
                tank = self.server.app.store.upsert_tank(body)
                self.server.app.scheduler.wake()
                self._json({"ok": True, "tank": tank})
                return
            if path == "/api/settings":
                settings = self.server.app.store.update_settings(body)
                self.server.app.scheduler.wake()
                self._json({"ok": True, "settings": settings})
                return
            if path == "/api/control/pause":
                self.server.app.store.pause(str(body.get("reason", "operator paused scheduling")))
                self.server.app.scheduler.wake()
                self._json({"ok": True, "settings": self.server.app.store.settings()})
                return
            if path == "/api/control/resume":
                self.server.app.store.resume()
                self.server.app.scheduler.wake()
                self._json({"ok": True, "settings": self.server.app.store.settings()})
                return
            if path == "/api/control/emergency-stop":
                self.server.app.scheduler.emergency_stop()
                self._json({"ok": True, "settings": self.server.app.store.settings()})
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except DeskError as exc:
            message = str(exc)
            status = (
                HTTPStatus.FORBIDDEN
                if any(term in message for term in ("token", "origin", "Host"))
                else HTTPStatus.BAD_REQUEST
            )
            self._error(status, message)
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _process_start_token(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            try:
                ok = ctypes.windll.kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )
                if not ok:
                    return None
                value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                return f"windows:{value}"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.is_file():
        try:
            raw = stat_path.read_text(encoding="utf-8")
            closing = raw.rfind(")")
            fields = raw[closing + 2 :].split()
            if not fields or fields[0] == "Z":
                return None
            # fields starts at proc field 3; process start time is field 22.
            return f"proc:{fields[19]}"
        except (OSError, IndexError, ValueError):
            return None
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if Path(f"/proc/{pid}/stat").is_file() and _process_start_token(pid) is None:
        return False
    return True


def _read_pid_record(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        pid = int(value.get("pid", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not _pid_alive(pid):
        return None
    expected_token = value.get("process_start_token")
    if expected_token:
        actual_token = _process_start_token(pid)
        if actual_token is not None and actual_token != expected_token:
            return None
    return value


def _read_pid(path: Path) -> int | None:
    record = _read_pid_record(path)
    return int(record["pid"]) if record is not None else None


class _ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError) as exc:
            self.handle.close()
            raise DeskError(
                "another Monster Wrangler process owns this repository control state"
            ) from exc

    def close(self) -> None:
        if self.handle.closed:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()

    def __enter__(self) -> "_ProcessLock":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, required=True, help="repository managed by the desk")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--daemon", action="store_true", help="start detached and return")
    parser.add_argument("--stop", action="store_true", help="stop the detached desk")
    parser.add_argument("--status", action="store_true", help="print detached desk status")
    parser.add_argument("--unsafe-network", action="store_true", help="allow a non-loopback bind")
    parser.add_argument("--max-workers", type=int, choices=range(1, 9))
    parser.add_argument("--foreground-child", action="store_true", help=argparse.SUPPRESS)


def _daemon_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tier_runner.desk",
        "--repo",
        str(args.repo),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-open",
        "--foreground-child",
    ]
    if args.state_dir:
        command.extend(["--state-dir", str(args.state_dir)])
    if args.unsafe_network:
        command.append("--unsafe-network")
    if args.max_workers:
        command.extend(["--max-workers", str(args.max_workers)])
    return command


def _start_daemon(
    args: argparse.Namespace,
    repo: Path,
    state_dir: Path,
    pid_path: Path,
    log_path: Path,
) -> int:
    existing = _read_pid_record(pid_path)
    if existing is not None:
        raise DeskError(f"Monster Wrangler is already running with pid {existing['pid']}")
    pid_path.unlink(missing_ok=True)
    kwargs: dict[str, Any] = {"start_new_session": os.name != "nt"}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    runner_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = (
        runner_root
        if not env.get("PYTHONPATH")
        else runner_root + os.pathsep + env["PYTHONPATH"]
    )
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            _daemon_command(args),
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            **kwargs,
        )
    deadline = time.time() + 8
    record: dict[str, Any] | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise DeskError(
                f"Monster Wrangler exited during startup; inspect {log_path}"
            )
        candidate = _read_pid_record(pid_path)
        if candidate is not None and int(candidate["pid"]) == process.pid:
            record = candidate
            break
        time.sleep(0.05)
    if record is None:
        process.terminate()
        raise DeskError(
            f"Monster Wrangler did not publish a ready PID record; inspect {log_path}"
        )
    print(
        json.dumps(
            {
                "started": True,
                "pid": process.pid,
                "url": record.get("url", f"http://{args.host}:{args.port}/"),
                "log": str(log_path),
                "state_dir": str(state_dir),
                "runs_dir": str(resolve_runs_dir(repo)),
            }
        )
    )
    return 0


def _serve_foreground(
    args: argparse.Namespace,
    repo: Path,
    state_dir: Path,
    pid_path: Path,
) -> int:
    app = DeskApplication(repo, state_dir, allow_remote=args.unsafe_network)
    if args.max_workers:
        app.store.update_settings({"max_workers": args.max_workers})
    server = DeskHTTPServer((args.host, args.port), app)
    actual_host, actual_port = server.server_address[:2]
    url_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{url_host}:{actual_port}/"
    pid_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "repo": str(repo),
                "started_at": utc_now(),
                "url": url,
                "process_start_token": _process_start_token(os.getpid()),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    shutdown_once = threading.Event()

    def shutdown_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        if shutdown_once.is_set():
            return
        shutdown_once.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, shutdown_handler)
    app.start()
    print(f"Monster Wrangler is running at {url}")
    print(f"Control state: {state_dir}")
    print(f"Verified run evidence: {app.runs_dir}")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    finally:
        server.server_close()
        app.stop()
        try:
            current = _read_pid_record(pid_path)
            if current is None or int(current["pid"]) == os.getpid():
                pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def run_cli(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    state_dir = resolve_state_dir(repo, args.state_dir)
    pid_path = state_dir / "monster-wrangler.pid.json"
    log_path = state_dir / "server.log"
    if args.status:
        record = _read_pid_record(pid_path)
        if record is None:
            pid_path.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "running": record is not None,
                    "pid": int(record["pid"]) if record else None,
                    "url": record.get("url") if record else None,
                    "started_at": record.get("started_at") if record else None,
                    "state_dir": str(state_dir),
                    "runs_dir": str(resolve_runs_dir(repo)),
                }
            )
        )
        return 0 if record else 1
    if args.stop:
        record = _read_pid_record(pid_path)
        if record is None:
            pid_path.unlink(missing_ok=True)
            print("monster-wrangler: no running desk found", file=sys.stderr)
            return 1
        pid = int(record["pid"])
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 8
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.1)
        if _pid_alive(pid):
            print(f"monster-wrangler: process {pid} did not stop", file=sys.stderr)
            return 2
        pid_path.unlink(missing_ok=True)
        print(json.dumps({"stopped": True, "pid": pid}))
        return 0
    if not _is_loopback(args.host) and not args.unsafe_network:
        raise DeskError("non-loopback binding requires --unsafe-network")
    if args.daemon and not args.foreground_child:
        return _start_daemon(args, repo, state_dir, pid_path, log_path)

    with _ProcessLock(state_dir / "monster-wrangler.lock"):
        existing = _read_pid_record(pid_path)
        if existing is not None and int(existing["pid"]) != os.getpid():
            raise DeskError(
                f"Monster Wrangler is already running with pid {existing['pid']}"
            )
        if existing is None:
            pid_path.unlink(missing_ok=True)
        return _serve_foreground(args, repo, state_dir, pid_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tierdesk",
        description="Monster Wrangler: persistent, controlled agent work for a Git repository",
    )
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return run_cli(_parser().parse_args(argv))
    except (DeskError, OSError, ValueError) as exc:
        print(f"monster-wrangler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
