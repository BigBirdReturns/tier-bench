"""Read projections and settle campaign trials from verified Desk receipts."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from .desk_common import canonical, load_json, now
from .residue_common import TASK_TERMINAL, file_hash, hash_json, task_outcome
from .residue_policy import rung_evidence


class ResidueQueryMixin:
    def _route_rows(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.db().execute(
            "SELECT * FROM residue_routes WHERE campaign_id=? ORDER BY position",
            (campaign_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["binding"] = load_json(item.pop("binding_json"), {})
            item["evidence"] = load_json(item.pop("evidence_json"), None)
            result.append(item)
        return result

    def _trial_rows(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.db().execute(
            """SELECT rt.*,rr.route_id,rr.label,rr.execution_class,rr.source_access,
                      rr.capability_basis,rr.binding_json
               FROM residue_trials rt JOIN residue_routes rr
               ON rr.campaign_id=rt.campaign_id AND rr.position=rt.route_position
               WHERE rt.campaign_id=? ORDER BY rt.sequence""",
            (campaign_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["result"] = load_json(item.pop("result_json"), None)
            item["binding"] = load_json(item.pop("binding_json"), {})
            result.append(item)
        return result

    def _candidate_rows(
        self, campaign_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if campaign_id is None:
            rows = self.db().execute(
                "SELECT * FROM residue_candidates ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.db().execute(
                "SELECT * FROM residue_candidates WHERE campaign_id=? ORDER BY created_at",
                (campaign_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = load_json(item.pop("evidence_json"), {})
            item["projection_path"] = str(self.residue_root / "candidates" / f"{item['id']}.json")
            result.append(item)
        return result

    def get_residue_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.db().execute(
            "SELECT * FROM residue_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["evidence"] = load_json(item.pop("evidence_json"), {})
        item["projection_path"] = str(self.residue_root / "candidates" / f"{candidate_id}.json")
        return item

    def list_residue_candidates(
        self, limit: int = 200, full: bool = True
    ) -> list[dict[str, Any]]:
        rows = self._candidate_rows(limit=limit)
        if full:
            return rows
        return [
            {
                key: row[key]
                for key in (
                    "id",
                    "campaign_id",
                    "winning_position",
                    "kind",
                    "state",
                    "created_at",
                    "projection_path",
                )
            }
            for row in rows
        ]

    def _serialize_campaign(self, row: sqlite3.Row | dict[str, Any], full: bool) -> dict[str, Any]:
        item = dict(row)
        item["task"] = load_json(item.pop("base_task_json"), {})
        item["policy"] = load_json(item.pop("policy_json"), {})
        item["result"] = load_json(item.pop("result_json"), None)
        routes = self._route_rows(item["id"])
        trials = self._trial_rows(item["id"])
        by_position: dict[int, list[dict[str, Any]]] = {}
        for trial in trials:
            by_position.setdefault(int(trial["route_position"]), []).append(trial)
        for route in routes:
            route_trials = by_position.get(int(route["position"]), [])
            route["trial_count"] = len(route_trials)
            route["trials"] = route_trials if full else route_trials[-1:]
        item["routes"] = routes
        candidates = self._candidate_rows(item["id"])
        item["candidates"] = candidates if full else [
            {
                key: candidate[key]
                for key in (
                    "id",
                    "kind",
                    "state",
                    "created_at",
                    "projection_path",
                )
            }
            for candidate in candidates
        ]
        item["active_task_id"] = self.campaign_active_task(item["id"])
        item["projection_path"] = str(
            self.residue_root / "campaigns" / f"{item['id']}.json"
        )
        return item

    def get_campaign(self, campaign_id: str, full: bool = True) -> dict[str, Any] | None:
        row = self.db().execute(
            "SELECT * FROM residue_campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        return self._serialize_campaign(row, full) if row else None

    def list_campaigns(self, limit: int = 100, full: bool = False) -> list[dict[str, Any]]:
        rows = self.db().execute(
            """SELECT * FROM residue_campaigns ORDER BY
               CASE state WHEN 'ACTIVE' THEN 0 WHEN 'DRAFT' THEN 1 ELSE 2 END,
               created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._serialize_campaign(row, full) for row in rows]

    def snapshot(self, cartridges: dict[str, Any] | None, active: list[str]) -> dict[str, Any]:
        result = super().snapshot(cartridges, active)
        result["residue_campaigns"] = self.list_campaigns(limit=100, full=False)
        result["residue_candidates"] = self.list_residue_candidates(
            limit=100, full=False
        )
        return result

    def _policy_trials(self, campaign_id: str) -> list[dict[str, Any]]:
        return [
            {
                "trial_id": row["id"],
                "sequence": row["sequence"],
                "task_id": campaign_id,
                "rung": row["route_id"],
                "verdict": {"outcome": row["outcome"]},
            }
            for row in self._trial_rows(campaign_id)
            if row.get("outcome")
        ]

    def _task_result(self, task: dict[str, Any]) -> dict[str, Any]:
        run = task.get("last_run")
        if run is None and task.get("runs"):
            run = task["runs"][0]
        run = run or {}
        receipt = run.get("receipt")
        verification = run.get("verification")
        output_dir = Path(str(run.get("output_dir", ""))) if run.get("output_dir") else None
        patch = output_dir / "change.patch" if output_dir else None
        receipt_path = Path(str(run.get("receipt_path", ""))) if run.get("receipt_path") else None
        result = {
            "task_id": task["id"],
            "task_state": task["state"],
            "outcome": task_outcome(task["state"]),
            "run_id": run.get("id"),
            "attempt": run.get("attempt"),
            "cost_usd": float(run.get("cost_usd", 0) or 0),
            "input_tokens": int(run.get("input_tokens", 0) or 0),
            "output_tokens": int(run.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(run.get("cache_read_tokens", 0) or 0),
            "cache_write_tokens": int(run.get("cache_write_tokens", 0) or 0),
            "receipt_path": str(receipt_path) if receipt_path else None,
            "receipt_sha256": file_hash(receipt_path) if receipt_path else None,
            "receipt_object_sha256": hash_json(receipt) if receipt is not None else None,
            "verification_sha256": hash_json(verification) if verification is not None else None,
            "patch_path": str(patch) if patch and patch.is_file() else None,
            "patch_sha256": file_hash(patch) if patch and patch.is_file() else None,
            "error": run.get("error") or task.get("last_error"),
            "settled_at": now(),
        }
        return result

    def _recover_preparing_trials(self) -> None:
        # A crash may occur after the trial row is reserved but before the task is
        # created. If the task exists, adopt its visible state. If it does not,
        # remove only the unmaterialized reservation so the deterministic trial id
        # can be recreated on the next scheduler tick.
        rows = self.db().execute(
            "SELECT id,task_id FROM residue_trials WHERE state='PREPARING'"
        ).fetchall()
        for row in rows:
            task = self.get_task(row["task_id"], False)
            if task is None:
                self.db().execute("DELETE FROM residue_trials WHERE id=?", (row["id"],))
            else:
                self.db().execute(
                    "UPDATE residue_trials SET state=?,updated_at=? WHERE id=?",
                    (task["state"], now(), row["id"]),
                )

    def _settle_trials(self, campaign_id: str) -> None:
        rows = self.db().execute(
            """SELECT id,task_id,state FROM residue_trials
               WHERE campaign_id=? AND state IN ('PREPARING','DRAFT','QUEUED','RUNNING')
               ORDER BY sequence""",
            (campaign_id,),
        ).fetchall()
        for row in rows:
            task = self.get_task(row["task_id"], False)
            if task is None:
                if row["state"] == "PREPARING":
                    continue
                self._fail_campaign(campaign_id, f"campaign trial lost task {row['task_id']}")
                return
            if task["state"] not in TASK_TERMINAL:
                if task["state"] != row["state"]:
                    self.db().execute(
                        "UPDATE residue_trials SET state=?,updated_at=? WHERE id=?",
                        (task["state"], now(), row["id"]),
                    )
                continue
            result = self._task_result(task)
            db = self.db()
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """UPDATE residue_trials SET state=?,outcome=?,result_json=?,updated_at=?
                       WHERE id=? AND state NOT IN (
                         'ACCEPTED','REJECTED','ERROR','CANCELED','INTERRUPTED'
                       )""",
                    (
                        task["state"],
                        result["outcome"],
                        canonical(result),
                        now(),
                        row["id"],
                    ),
                )
                self.event(
                    "residue.trial.settled",
                    task_id=task["id"],
                    run_id=result.get("run_id"),
                    detail={
                        "campaign_id": campaign_id,
                        "trial_id": row["id"],
                        "state": task["state"],
                        "outcome": result["outcome"],
                    },
                    db=db,
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def _update_route_evidence(self, campaign: dict[str, Any]) -> dict[str, dict[str, Any]]:
        trials = self._policy_trials(campaign["id"])
        evidence: dict[str, dict[str, Any]] = {}
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            for route in campaign["routes"]:
                value = rung_evidence(trials, route["route_id"], int(campaign["k"]))
                evidence[route["route_id"]] = value
                state = value["state"]
                if route["state"] == "inconclusive":
                    state = "inconclusive"
                if state != route["state"] or value != route.get("evidence"):
                    db.execute(
                        """UPDATE residue_routes SET state=?,evidence_json=?,updated_at=?
                           WHERE campaign_id=? AND position=?""",
                        (state, canonical(value), stamp, campaign["id"], route["position"]),
                    )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return evidence
