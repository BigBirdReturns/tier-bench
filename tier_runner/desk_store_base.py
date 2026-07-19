from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
import uuid

from .desk_common import (
    DEFAULTS,
    DeskError,
    as_bool,
    as_float,
    as_int,
    canonical,
    committed_blob,
    load_json,
    normalize_dependencies,
    normalize_files,
    now,
)


class DeskStoreBase:
    def __init__(self, db_path: Path, repo: Path):
        self.db_path = db_path
        self.repo = repo
        self.local = threading.local()
        self.init()
        self.recover()

    def db(self) -> sqlite3.Connection:
        connection = getattr(self.local, "db", None)
        if connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            self.local.db = connection
        return connection

    def init(self) -> None:
        db = self.db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY, value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, task TEXT NOT NULL,
              files_json TEXT NOT NULL, acceptance TEXT NOT NULL,
              manifest TEXT NOT NULL, arm TEXT NOT NULL, priority INTEGER NOT NULL,
              state TEXT NOT NULL, scheduled_for TEXT, approval_required INTEGER NOT NULL,
              approved_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0, last_run_id TEXT, last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS dependencies(
              task_id TEXT NOT NULL, depends_on TEXT NOT NULL,
              PRIMARY KEY(task_id, depends_on),
              FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
              FOREIGN KEY(depends_on) REFERENCES tasks(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, attempt INTEGER NOT NULL,
              state TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
              output_dir TEXT NOT NULL, log_path TEXT NOT NULL, receipt_path TEXT,
              receipt_json TEXT, verify_json TEXT, cost_usd REAL NOT NULL DEFAULT 0,
              input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
              cache_read_tokens INTEGER NOT NULL DEFAULT 0,
              cache_write_tokens INTEGER NOT NULL DEFAULT 0,
              pid INTEGER, exit_code INTEGER, error TEXT,
              UNIQUE(task_id, attempt),
              FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL,
              task_id TEXT, run_id TEXT, detail_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_queue
              ON tasks(state, priority DESC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
            """
        )
        for key, value in DEFAULTS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings(key,value_json) VALUES(?,?)",
                (key, canonical(value)),
            )

    def event(
        self,
        kind: str,
        task_id: str | None = None,
        run_id: str | None = None,
        detail: dict[str, Any] | None = None,
        db: sqlite3.Connection | None = None,
    ) -> None:
        (db or self.db()).execute(
            "INSERT INTO events(ts,kind,task_id,run_id,detail_json) VALUES(?,?,?,?,?)",
            (now(), kind, task_id, run_id, canonical(detail or {})),
        )

    def settings(self) -> dict[str, Any]:
        rows = self.db().execute("SELECT key,value_json FROM settings").fetchall()
        return {**DEFAULTS, **{row["key"]: load_json(row["value_json"], None) for row in rows}}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(DEFAULTS)
        if unknown:
            raise DeskError(f"unknown settings: {sorted(unknown)}")
        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            if key in {"paused", "stop_on_failure"}:
                normalized[key] = as_bool(value, key)
            elif key == "pause_reason":
                normalized[key] = str(value)[:500]
            elif key == "max_workers":
                normalized[key] = as_int(value, key, 1, 4)
            elif key == "daily_task_limit":
                normalized[key] = as_int(value, key, 1, 100)
            elif key == "daily_cost_limit_usd":
                normalized[key] = as_float(value, key, 0, 100000)
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            for key, value in normalized.items():
                db.execute(
                    "INSERT OR REPLACE INTO settings(key,value_json) VALUES(?,?)",
                    (key, canonical(value)),
                )
            self.event("settings.updated", detail=normalized, db=db)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return self.settings()

    def pause(self, reason: str) -> None:
        self.update_settings({"paused": True, "pause_reason": reason})

    def resume(self) -> None:
        self.update_settings({"paused": False, "pause_reason": ""})

    def recover(self) -> None:
        rows = (
            self.db().execute("SELECT id,last_run_id FROM tasks WHERE state='RUNNING'").fetchall()
        )
        if not rows:
            return
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            stamp = now()
            for row in rows:
                if row["last_run_id"]:
                    db.execute(
                        "UPDATE runs SET state='INTERRUPTED',completed_at=?,error=? "
                        "WHERE id=? AND state='RUNNING'",
                        (stamp, "desk restarted before run completion", row["last_run_id"]),
                    )
                db.execute(
                    "UPDATE tasks SET state='INTERRUPTED',updated_at=?,last_error=? WHERE id=?",
                    (stamp, "desk restarted before run completion", row["id"]),
                )
                self.event("task.interrupted", row["id"], row["last_run_id"], db=db)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    def exists(self, task_id: str, db: sqlite3.Connection | None = None) -> bool:
        return (db or self.db()).execute(
            "SELECT 1 FROM tasks WHERE id=?", (task_id,)
        ).fetchone() is not None

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title", "")).strip()
        task = str(payload.get("task", "")).strip()
        acceptance = str(payload.get("acceptance", "")).strip()
        if not title or len(title) > 160:
            raise DeskError("title is required and must be at most 160 characters")
        if not task or len(task) > 12000:
            raise DeskError("task is required and must be at most 12,000 characters")
        if not acceptance or len(acceptance) > 8000:
            raise DeskError("acceptance is required and must be at most 8,000 characters")
        files = normalize_files(payload.get("files"))
        dependencies = normalize_dependencies(payload.get("depends_on"))
        priority = as_int(payload.get("priority", 50), "priority", 0, 100)
        queue_now = as_bool(payload.get("queue_now", False), "queue_now")
        approval_required = as_bool(payload.get("approval_required", False), "approval_required")
        arm = str(payload.get("arm", "arm_b")).strip()
        if arm not in {"arm_a", "arm_b", "arm_c"}:
            raise DeskError("arm must be arm_a, arm_b, or arm_c")
        manifest_input = Path(str(payload.get("manifest", "pilot_backends.json")).strip())
        manifest_path = (
            manifest_input.resolve()
            if manifest_input.is_absolute()
            else (self.repo / manifest_input).resolve()
        )
        try:
            manifest = manifest_path.relative_to(self.repo).as_posix()
        except ValueError as exc:
            raise DeskError("backend manifest must live inside the managed repository") from exc
        try:
            manifest_data = json.loads(
                committed_blob(self.repo, manifest, "backend manifest").decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeskError(f"committed backend manifest is invalid JSON: {exc}") from exc
        arms = manifest_data.get("arms") if isinstance(manifest_data, dict) else None
        if not isinstance(arms, dict) or arm not in arms:
            raise DeskError(f"backend manifest does not define {arm}")
        scheduled_for = payload.get("scheduled_for") or None
        if scheduled_for:
            try:
                scheduled = datetime.fromisoformat(str(scheduled_for).replace("Z", "+00:00"))
            except ValueError as exc:
                raise DeskError("scheduled_for must be ISO-8601") from exc
            if scheduled.tzinfo is None:
                raise DeskError("scheduled_for must include a timezone")
            scheduled_for = scheduled.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        task_id = str(payload.get("id", "")).strip() or "mw-" + uuid.uuid4().hex[:12]
        if len(task_id) > 80 or not all(c.isalnum() or c in "._-" for c in task_id):
            raise DeskError("task id may contain only letters, digits, dot, underscore, and dash")
        if task_id in dependencies:
            raise DeskError("a task cannot depend on itself")
        state = "QUEUED" if queue_now and not approval_required else "DRAFT"
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            if self.exists(task_id, db):
                raise DeskError(f"task already exists: {task_id}")
            missing = [item for item in dependencies if not self.exists(item, db)]
            if missing:
                raise DeskError(f"unknown dependencies: {missing}")
            db.execute(
                """INSERT INTO tasks(
                  id,title,task,files_json,acceptance,manifest,arm,priority,state,scheduled_for,
                  approval_required,approved_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    title,
                    task,
                    canonical(files),
                    acceptance,
                    str(manifest),
                    arm,
                    priority,
                    state,
                    scheduled_for,
                    int(approval_required),
                    stamp if state == "QUEUED" else None,
                    stamp,
                    stamp,
                ),
            )
            for dependency in dependencies:
                db.execute(
                    "INSERT INTO dependencies(task_id,depends_on) VALUES(?,?)",
                    (task_id, dependency),
                )
            self.event("task.created", task_id, detail={"state": state}, db=db)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_task(task_id)
        assert result is not None
        return result
