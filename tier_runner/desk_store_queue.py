from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .desk_common import SCHEMA, TERMINAL, DeskError, canonical, load_json, now

class DeskStoreQueueMixin:
    def dependencies(self, task_id: str) -> list[dict[str, str]]:
        rows = self.db().execute(
            """SELECT d.depends_on id,t.title,t.state
               FROM dependencies d JOIN tasks t ON t.id=d.depends_on
               WHERE d.task_id=? ORDER BY d.depends_on""",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def serialize_run(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        run = dict(row)
        run["receipt"] = load_json(run.pop("receipt_json", None), None)
        run["verification"] = load_json(run.pop("verify_json", None), None)
        return run

    def runs(self, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db().execute(
            "SELECT * FROM runs WHERE task_id=? ORDER BY attempt DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [self.serialize_run(row) for row in rows]

    def serialize_task(self, row: sqlite3.Row | dict[str, Any], full: bool) -> dict[str, Any]:
        task = dict(row)
        task["files"] = load_json(task.pop("files_json", None), [])
        task["approval_required"] = bool(task["approval_required"])
        deps = self.dependencies(task["id"])
        task["dependencies"] = deps
        task["blocked_by"] = [item for item in deps if item["state"] != "ACCEPTED"]
        if full:
            task["runs"] = self.runs(task["id"])
        elif task.get("last_run_id"):
            last = self.db().execute("SELECT * FROM runs WHERE id=?", (task["last_run_id"],)).fetchone()
            task["last_run"] = self.serialize_run(last) if last else None
        else:
            task["last_run"] = None
        return task

    def get_task(self, task_id: str, full: bool = True) -> dict[str, Any] | None:
        row = self.db().execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self.serialize_task(row, full) if row else None

    def list_tasks(self) -> list[dict[str, Any]]:
        rows = self.db().execute(
            """SELECT * FROM tasks ORDER BY
               CASE state WHEN 'RUNNING' THEN 0 WHEN 'QUEUED' THEN 1 WHEN 'DRAFT' THEN 2 ELSE 3 END,
               priority DESC,created_at DESC LIMIT 500"""
        ).fetchall()
        return [self.serialize_task(row, False) for row in rows]

    def transition(self, task_id: str, action: str) -> dict[str, Any]:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DeskError(f"unknown task: {task_id}")
            current = row["state"]
            stamp = now()
            if action == "arm":
                if current == "RUNNING":
                    raise DeskError("a running task cannot be armed again")
                target = "QUEUED"
                db.execute(
                    "UPDATE tasks SET state=?,approved_at=?,updated_at=?,last_error=NULL WHERE id=?",
                    (target, stamp, stamp, task_id),
                )
            elif action == "hold":
                if current == "RUNNING":
                    raise DeskError("use cancel to stop a running task")
                target = "DRAFT"
                db.execute("UPDATE tasks SET state=?,updated_at=? WHERE id=?", (target, stamp, task_id))
            elif action == "retry":
                if current not in TERMINAL:
                    raise DeskError("only a terminal task can be retried")
                target = "QUEUED"
                db.execute(
                    "UPDATE tasks SET state=?,updated_at=?,last_error=NULL WHERE id=?",
                    (target, stamp, task_id),
                )
            elif action == "cancel":
                if current == "RUNNING":
                    target = current
                else:
                    target = "CANCELED"
                    db.execute(
                        "UPDATE tasks SET state=?,updated_at=?,last_error=? WHERE id=?",
                        (target, stamp, "canceled by operator", task_id),
                    )
            else:
                raise DeskError(f"unknown task action: {action}")
            self.event(
                f"task.{action}", task_id, row["last_run_id"],
                {"from": current, "to": target}, db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_task(task_id)
        assert result is not None
        return result

    def ready(self, limit: int) -> list[dict[str, Any]]:
        rows = self.db().execute(
            """SELECT t.* FROM tasks t
               WHERE t.state='QUEUED'
                 AND (t.scheduled_for IS NULL OR t.scheduled_for<=?)
                 AND NOT EXISTS(
                   SELECT 1 FROM dependencies d JOIN tasks p ON p.id=d.depends_on
                   WHERE d.task_id=t.id AND p.state!='ACCEPTED'
                 )
               ORDER BY t.priority DESC,t.created_at ASC LIMIT ?""",
            (now(), limit),
        ).fetchall()
        return [self.serialize_task(row, False) for row in rows]

    def claim(
        self, task_id: str, runs_dir: Path, logs_dir: Path
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task["state"] != "QUEUED":
                db.execute("ROLLBACK")
                return None
            blocked = db.execute(
                """SELECT COUNT(*) n FROM dependencies d JOIN tasks p ON p.id=d.depends_on
                   WHERE d.task_id=? AND p.state!='ACCEPTED'""",
                (task_id,),
            ).fetchone()["n"]
            if blocked:
                db.execute("ROLLBACK")
                return None
            attempt = int(task["attempt_count"]) + 1
            run_id = f"{task_id}-a{attempt}-{uuid.uuid4().hex[:8]}"
            output_dir = runs_dir / task_id / f"attempt-{attempt:03d}"
            log_path = logs_dir / task_id / f"attempt-{attempt:03d}.log"
            if output_dir.exists():
                raise DeskError(f"run output directory already exists: {output_dir}")
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = now()
            db.execute(
                """INSERT INTO runs(id,task_id,attempt,state,started_at,output_dir,log_path)
                   VALUES(?,?,?,'RUNNING',?,?,?)""",
                (run_id, task_id, attempt, stamp, str(output_dir), str(log_path)),
            )
            db.execute(
                """UPDATE tasks SET state='RUNNING',updated_at=?,attempt_count=?,last_run_id=?,last_error=NULL
                   WHERE id=? AND state='QUEUED'""",
                (stamp, attempt, run_id, task_id),
            )
            self.event("task.claimed", task_id, run_id, {"attempt": attempt}, db)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        current = self.get_task(task_id, False)
        run = self.db().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        assert current is not None and run is not None
        return current, self.serialize_run(run)

    def set_pid(self, run_id: str, pid: int) -> None:
        self.db().execute("UPDATE runs SET pid=? WHERE id=?", (pid, run_id))

    def complete(self, run_id: str, result: "ExecutionResult") -> None:
        if result.state not in TERMINAL:
            raise DeskError(f"invalid terminal state: {result.state}")
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise DeskError(f"unknown run: {run_id}")
            stamp = now()
            db.execute(
                """UPDATE runs SET state=?,completed_at=?,receipt_path=?,receipt_json=?,verify_json=?,
                   cost_usd=?,input_tokens=?,output_tokens=?,cache_read_tokens=?,cache_write_tokens=?,
                   exit_code=?,error=? WHERE id=?""",
                (
                    result.state, stamp, result.receipt_path,
                    canonical(result.receipt) if result.receipt is not None else None,
                    canonical(result.verification) if result.verification is not None else None,
                    result.cost_usd, result.input_tokens, result.output_tokens,
                    result.cache_read_tokens, result.cache_write_tokens,
                    result.exit_code, result.error, run_id,
                ),
            )
            db.execute(
                "UPDATE tasks SET state=?,updated_at=?,last_error=? WHERE id=? AND last_run_id=?",
                (result.state, stamp, result.error, run["task_id"], run_id),
            )
            self.event(
                "task.completed", run["task_id"], run_id,
                {"state": result.state, "cost_usd": result.cost_usd}, db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    def cancel_running(self, task_id: str, reason: str) -> bool:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise DeskError(f"unknown task: {task_id}")
            if task["state"] != "RUNNING":
                db.execute("ROLLBACK")
                return False
            stamp = now()
            if task["last_run_id"]:
                db.execute(
                    "UPDATE runs SET state='CANCELED',completed_at=?,error=? WHERE id=? AND state='RUNNING'",
                    (stamp, reason, task["last_run_id"]),
                )
            db.execute(
                "UPDATE tasks SET state='CANCELED',updated_at=?,last_error=? WHERE id=?",
                (stamp, reason, task_id),
            )
            self.event("task.canceled", task_id, task["last_run_id"], {"reason": reason}, db)
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self.serialize_run(row) if row else None

    def daily_usage(self) -> dict[str, Any]:
        day = datetime.now(timezone.utc).date().isoformat()
        row = self.db().execute(
            """SELECT COUNT(*) tasks,COALESCE(SUM(cost_usd),0) cost_usd,
               COALESCE(SUM(input_tokens),0) input_tokens,
               COALESCE(SUM(output_tokens),0) output_tokens,
               COALESCE(SUM(cache_read_tokens),0) cache_read_tokens,
               COALESCE(SUM(cache_write_tokens),0) cache_write_tokens
               FROM runs WHERE substr(started_at,1,10)=?""",
            (day,),
        ).fetchone()
        return dict(row)

    def stats(self) -> dict[str, Any]:
        counts = {row["state"]: row["n"] for row in self.db().execute(
            "SELECT state,COUNT(*) n FROM tasks GROUP BY state"
        ).fetchall()}
        totals = dict(self.db().execute(
            """SELECT COALESCE(SUM(cost_usd),0) cost_usd,
               COALESCE(SUM(input_tokens),0) input_tokens,
               COALESCE(SUM(output_tokens),0) output_tokens,
               COALESCE(SUM(cache_read_tokens),0) cache_read_tokens,
               COALESCE(SUM(cache_write_tokens),0) cache_write_tokens,
               SUM(CASE WHEN state='ACCEPTED' THEN 1 ELSE 0 END) accepted,
               SUM(CASE WHEN state IN ('ACCEPTED','REJECTED','ERROR') THEN 1 ELSE 0 END) judged
               FROM runs"""
        ).fetchone())
        judged = int(totals.pop("judged") or 0)
        accepted = int(totals.pop("accepted") or 0)
        totals["success_rate"] = accepted / judged if judged else None
        totals["states"] = counts
        totals["daily"] = self.daily_usage()
        return totals

    def events(self) -> list[dict[str, Any]]:
        result = []
        for row in self.db().execute("SELECT * FROM events ORDER BY seq DESC LIMIT 80").fetchall():
            item = dict(row)
            item["detail"] = load_json(item.pop("detail_json"), {})
            result.append(item)
        return result

    def snapshot(self, cartridges: dict[str, Any] | None, active: list[str]) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "repo": str(self.repo),
            "settings": self.settings(),
            "stats": self.stats(),
            "tasks": self.list_tasks(),
            "events": self.events(),
            "cartridges": cartridges,
            "active_runs": active,
            "server_time": now(),
        }
