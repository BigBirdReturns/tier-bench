"""Campaign schema, validation, and scheduler-bound control hooks."""
from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any
import uuid

from .desk_common import (
    DeskError, as_bool, as_int, canonical, committed_blob, normalize_files, now
)
from .residue_common import (
    CAMPAIGN_MODES, CAMPAIGN_SCHEMA, CAMPAIGN_TERMINAL, CAPABILITY_BASES,
    ROUTE_CLASSES, SAFE_ID, SOURCE_ACCESS, normalize_schedule, optional_cost,
    required_text,
)


class ResidueSchemaMixin:
    def init_residue(self) -> None:
        self._residue_thread = threading.local()
        self.db().executescript(
            """
            CREATE TABLE IF NOT EXISTS residue_campaigns(
              id TEXT PRIMARY KEY,
              schema_version TEXT NOT NULL,
              title TEXT NOT NULL,
              mode TEXT NOT NULL,
              state TEXT NOT NULL,
              k INTEGER NOT NULL,
              max_trials_per_route INTEGER NOT NULL,
              base_task_json TEXT NOT NULL,
              policy_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT,
              result_json TEXT,
              last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS residue_routes(
              campaign_id TEXT NOT NULL,
              position INTEGER NOT NULL,
              route_id TEXT NOT NULL,
              label TEXT NOT NULL,
              manifest TEXT NOT NULL,
              arm TEXT NOT NULL,
              execution_class TEXT NOT NULL,
              source_access TEXT NOT NULL,
              capability_basis TEXT NOT NULL,
              estimated_max_cost_usd REAL,
              binding_json TEXT NOT NULL,
              state TEXT NOT NULL,
              evidence_json TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(campaign_id, position),
              UNIQUE(campaign_id, route_id),
              FOREIGN KEY(campaign_id) REFERENCES residue_campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS residue_trials(
              id TEXT PRIMARY KEY,
              campaign_id TEXT NOT NULL,
              route_position INTEGER NOT NULL,
              trial_number INTEGER NOT NULL,
              sequence INTEGER NOT NULL,
              task_id TEXT NOT NULL UNIQUE,
              state TEXT NOT NULL,
              outcome TEXT,
              result_json TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(campaign_id, route_position, trial_number),
              UNIQUE(campaign_id, sequence),
              FOREIGN KEY(campaign_id, route_position)
                REFERENCES residue_routes(campaign_id, position) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS residue_candidates(
              id TEXT PRIMARY KEY,
              campaign_id TEXT NOT NULL,
              winning_position INTEGER NOT NULL,
              kind TEXT NOT NULL,
              state TEXT NOT NULL,
              evidence_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(campaign_id, winning_position),
              FOREIGN KEY(campaign_id, winning_position)
                REFERENCES residue_routes(campaign_id, position) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_residue_campaign_state
              ON residue_campaigns(state, created_at);
            CREATE INDEX IF NOT EXISTS idx_residue_trial_task
              ON residue_trials(task_id);
            CREATE INDEX IF NOT EXISTS idx_residue_trial_campaign
              ON residue_trials(campaign_id, sequence);
            """
        )
        self._recover_preparing_trials()

    def settings(self) -> dict[str, Any]:
        settings = super().settings()
        if getattr(self._residue_thread, "suppress_stop_once", False):
            self._residue_thread.suppress_stop_once = False
            settings = {**settings, "stop_on_failure": False}
        return settings

    def transition(self, task_id: str, action: str) -> dict[str, Any]:
        if self.campaign_manages_task(task_id) and action in {"arm", "hold", "retry"}:
            raise DeskError(
                "campaign-managed trial tasks cannot be manually armed, held, or retried; "
                "change the campaign rather than rewriting its evidence sequence"
            )
        return super().transition(task_id, action)

    def complete(self, run_id: str, result: Any) -> bool:
        row = self.db().execute("SELECT task_id FROM runs WHERE id=?", (run_id,)).fetchone()
        task_id = row["task_id"] if row else None
        managed = bool(task_id and self.campaign_manages_task(task_id))
        completed = super().complete(run_id, result)
        if completed and managed and result.state in {"REJECTED", "ERROR"}:
            # DeskScheduler asks settings() immediately after complete(). Suppress
            # exactly that one global pause check: the campaign controller, not the
            # generic scheduler, owns expected wall/error handling for this task.
            self._residue_thread.suppress_stop_once = True
        return completed

    def ready(self, limit: int) -> list[dict[str, Any]]:
        # The Desk calls ready() only after global pause and daily-budget gates.
        # Driving campaigns here keeps the refinery a client of the existing
        # scheduler rather than a second scheduler.
        self.tick_residue_campaigns(allow_dispatch=True)
        return super().ready(limit)

    @property
    def residue_root(self) -> Path:
        root = self.db_path.parent / "residue"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _manifest_binding(self, manifest_value: Any, arm: str) -> tuple[str, dict[str, Any]]:
        manifest_input = Path(str(manifest_value or "pilot_backends.json").strip())
        manifest_path = (
            manifest_input.resolve()
            if manifest_input.is_absolute()
            else (self.repo / manifest_input).resolve()
        )
        try:
            relative = manifest_path.relative_to(self.repo).as_posix()
        except ValueError as exc:
            raise DeskError(
                "route backend manifest must live inside the managed repository"
            ) from exc
        try:
            raw = json.loads(committed_blob(self.repo, relative, "route backend manifest"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeskError(f"committed route backend manifest is invalid JSON: {exc}") from exc
        arms = raw.get("arms") if isinstance(raw, dict) else None
        if not isinstance(arms, dict) or arm not in arms:
            raise DeskError(f"route backend manifest does not define {arm}")
        value = arms[arm]
        value = value if isinstance(value, dict) else {}
        binding = {
            "manifest_schema": raw.get("schema") if isinstance(raw, dict) else None,
            "model_id": value.get("model_id"),
            "effort": value.get("effort"),
            "surface": value.get("surface"),
            "cost_basis": value.get("cost_basis"),
            "account": value.get("account"),
            "tier": value.get("tier"),
        }
        return relative, binding

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DeskError("campaign payload must be a JSON object")
        schema = payload.get("schema", CAMPAIGN_SCHEMA)
        if schema != CAMPAIGN_SCHEMA:
            raise DeskError(f"campaign schema must be {CAMPAIGN_SCHEMA}")
        title = required_text(payload.get("title"), "campaign title", 160)
        mode = str(payload.get("mode", "local_first")).strip()
        if mode not in CAMPAIGN_MODES:
            raise DeskError(f"campaign mode must be one of {sorted(CAMPAIGN_MODES)}")
        k = as_int(payload.get("k", 1), "k", 1, 10)
        max_trials = as_int(
            payload.get("max_trials_per_route", max(3 * k, k + 2)),
            "max_trials_per_route",
            k,
            100,
        )
        task_input = payload.get("task")
        if not isinstance(task_input, dict):
            raise DeskError("campaign task must be an object")
        base_task = {
            "task": required_text(task_input.get("task"), "campaign task.task", 12_000),
            "files": normalize_files(task_input.get("files")),
            "acceptance": required_text(
                task_input.get("acceptance"), "campaign task.acceptance", 8_000
            ),
            "priority": as_int(task_input.get("priority", 50), "campaign task.priority", 0, 100),
            "scheduled_for": normalize_schedule(task_input.get("scheduled_for")),
        }
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, list) or not 1 <= len(raw_routes) <= 32:
            raise DeskError("campaign routes must be an array of one to 32 routes")
        routes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for position, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise DeskError(f"campaign route {position} must be an object")
            route_id = required_text(raw.get("id"), f"campaign route {position}.id", 40)
            if not SAFE_ID.fullmatch(route_id):
                raise DeskError(f"campaign route {position}.id contains unsafe characters")
            if route_id in seen:
                raise DeskError(f"duplicate campaign route id: {route_id}")
            seen.add(route_id)
            label = required_text(
                raw.get("label", route_id), f"campaign route {route_id}.label", 120
            )
            arm = str(raw.get("arm", "arm_b")).strip()
            if arm not in {"arm_a", "arm_b", "arm_c"}:
                raise DeskError(f"campaign route {route_id}.arm is invalid")
            execution_class = str(raw.get("execution_class", "remote_unknown")).strip()
            if execution_class not in ROUTE_CLASSES:
                raise DeskError(
                    f"campaign route {route_id}.execution_class must be one of "
                    f"{sorted(ROUTE_CLASSES)}"
                )
            source_access = str(raw.get("source_access", "unknown")).strip()
            if source_access not in SOURCE_ACCESS:
                raise DeskError(
                    f"campaign route {route_id}.source_access must be one of "
                    f"{sorted(SOURCE_ACCESS)}"
                )
            capability_basis = str(raw.get("capability_basis", "unmeasured")).strip()
            if capability_basis not in CAPABILITY_BASES:
                raise DeskError(
                    f"campaign route {route_id}.capability_basis must be one of "
                    f"{sorted(CAPABILITY_BASES)}"
                )
            estimate = optional_cost(
                raw.get("estimated_max_cost_usd"),
                f"campaign route {route_id}.estimated_max_cost_usd",
            )
            if estimate is None and execution_class == "local":
                estimate = 0.0
            manifest, binding = self._manifest_binding(raw.get("manifest"), arm)
            routes.append(
                {
                    "position": position,
                    "route_id": route_id,
                    "label": label,
                    "manifest": manifest,
                    "arm": arm,
                    "execution_class": execution_class,
                    "source_access": source_access,
                    "capability_basis": capability_basis,
                    "estimated_max_cost_usd": estimate,
                    "binding": binding,
                }
            )
        raw_policy = payload.get("policy") or {}
        if not isinstance(raw_policy, dict):
            raise DeskError("campaign policy must be an object")
        max_total_cost = optional_cost(
            raw_policy.get("max_total_cost_usd"), "campaign policy.max_total_cost_usd"
        )
        max_remote_trials = raw_policy.get("max_remote_trials")
        if max_remote_trials is not None:
            max_remote_trials = as_int(
                max_remote_trials, "campaign policy.max_remote_trials", 0, 10_000
            )
        policy = {
            "max_total_cost_usd": max_total_cost,
            "max_remote_trials": max_remote_trials,
            "materialize_candidates": as_bool(
                raw_policy.get("materialize_candidates", True),
                "campaign policy.materialize_candidates",
            ),
        }
        queue_now = as_bool(payload.get("queue_now", False), "campaign queue_now")
        campaign_id = str(payload.get("id", "")).strip() or "fr-" + uuid.uuid4().hex[:12]
        if len(campaign_id) > 56 or not SAFE_ID.fullmatch(campaign_id):
            raise DeskError(
                "campaign id must be at most 56 characters and contain only letters, "
                "digits, dot, underscore, and dash"
            )
        state = "ACTIVE" if queue_now else "DRAFT"
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("SELECT 1 FROM residue_campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise DeskError(f"campaign already exists: {campaign_id}")
            db.execute(
                """INSERT INTO residue_campaigns(
                  id,schema_version,title,mode,state,k,max_trials_per_route,
                  base_task_json,policy_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    campaign_id,
                    CAMPAIGN_SCHEMA,
                    title,
                    mode,
                    state,
                    k,
                    max_trials,
                    canonical(base_task),
                    canonical(policy),
                    stamp,
                    stamp,
                ),
            )
            for route in routes:
                db.execute(
                    """INSERT INTO residue_routes(
                      campaign_id,position,route_id,label,manifest,arm,execution_class,
                      source_access,capability_basis,estimated_max_cost_usd,binding_json,
                      state,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        campaign_id,
                        route["position"],
                        route["route_id"],
                        route["label"],
                        route["manifest"],
                        route["arm"],
                        route["execution_class"],
                        route["source_access"],
                        route["capability_basis"],
                        route["estimated_max_cost_usd"],
                        canonical(route["binding"]),
                        "unmeasured",
                        stamp,
                        stamp,
                    ),
                )
            self.event(
                "residue.campaign.created",
                detail={"campaign_id": campaign_id, "state": state, "mode": mode, "k": k},
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        campaign = self.get_campaign(campaign_id)
        assert campaign is not None
        self._write_campaign_projection(campaign)
        return campaign

    def start_campaign(self, campaign_id: str) -> dict[str, Any]:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT state FROM residue_campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
            if row is None:
                raise DeskError(f"unknown campaign: {campaign_id}")
            if row["state"] != "DRAFT":
                raise DeskError("only a draft campaign can be started")
            stamp = now()
            db.execute(
                "UPDATE residue_campaigns SET state='ACTIVE',updated_at=?,"
                "last_error=NULL WHERE id=?",
                (stamp, campaign_id),
            )
            self.event(
                "residue.campaign.started", detail={"campaign_id": campaign_id}, db=db
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        campaign = self.get_campaign(campaign_id)
        assert campaign is not None
        self._write_campaign_projection(campaign)
        return campaign

    def cancel_campaign(self, campaign_id: str) -> dict[str, Any]:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT state FROM residue_campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
            if row is None:
                raise DeskError(f"unknown campaign: {campaign_id}")
            if row["state"] in CAMPAIGN_TERMINAL:
                raise DeskError("campaign is already terminal")
            stamp = now()
            db.execute(
                """UPDATE residue_campaigns SET state='CANCELED',updated_at=?,completed_at=?,
                   last_error='canceled by operator' WHERE id=?""",
                (stamp, stamp, campaign_id),
            )
            self.event(
                "residue.campaign.canceled", detail={"campaign_id": campaign_id}, db=db
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        campaign = self.get_campaign(campaign_id)
        assert campaign is not None
        self._write_campaign_projection(campaign)
        return campaign

    def campaign_active_task(self, campaign_id: str) -> str | None:
        row = self.db().execute(
            """SELECT rt.task_id FROM residue_trials rt
               JOIN tasks t ON t.id=rt.task_id
               WHERE rt.campaign_id=? AND t.state IN ('DRAFT','QUEUED','RUNNING')
               ORDER BY rt.sequence DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
        return row["task_id"] if row else None

    def campaign_manages_task(self, task_id: str) -> bool:
        return self.db().execute(
            "SELECT 1 FROM residue_trials WHERE task_id=?", (task_id,)
        ).fetchone() is not None
