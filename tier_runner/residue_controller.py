"""Campaign controller and residue candidate materializer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .desk_common import canonical, now
from .residue_common import CANDIDATE_SCHEMA, hash_json
from .residue_policy import decision_for_task, rung_evidence


class ResidueControllerMixin:
    def _spent(self, campaign_id: str) -> float:
        total = 0.0
        for trial in self._trial_rows(campaign_id):
            result = trial.get("result") or {}
            total += float(result.get("cost_usd", 0) or 0)
        return total

    def _remote_trials(self, campaign_id: str) -> int:
        return sum(
            1
            for trial in self._trial_rows(campaign_id)
            if trial["execution_class"] != "local"
        )

    def _budget_allows(self, campaign: dict[str, Any], route: dict[str, Any]) -> tuple[bool, str]:
        policy = campaign["policy"]
        max_remote = policy.get("max_remote_trials")
        if (
            max_remote is not None
            and route["execution_class"] != "local"
            and self._remote_trials(campaign["id"]) >= int(max_remote)
        ):
            return False, "campaign remote-trial ceiling reached"
        cap = policy.get("max_total_cost_usd")
        if cap is None:
            return True, ""
        estimate = route.get("estimated_max_cost_usd")
        if estimate is None:
            return False, "next route has unknown estimated cost under a hard campaign cap"
        spent = self._spent(campaign["id"])
        if spent + float(estimate) > float(cap):
            return False, (
                f"campaign cost cap would be exceeded: spent ${spent:.4f} + "
                f"estimate ${float(estimate):.4f} > ${float(cap):.4f}"
            )
        return True, ""

    def _trial_task_id(self, campaign_id: str, position: int, trial_number: int) -> str:
        digest = hashlib.sha256(f"{campaign_id}:{position}".encode()).hexdigest()[:10]
        return f"rr-{digest}-r{position:02d}-t{trial_number:03d}"

    def _dispatch_trial(self, campaign: dict[str, Any], route: dict[str, Any]) -> None:
        if self.campaign_active_task(campaign["id"]):
            return
        allowed, reason = self._budget_allows(campaign, route)
        if not allowed:
            self._complete_campaign(campaign["id"], "BUDGET_BLOCKED", reason=reason)
            return
        prior = [
            trial
            for trial in self._trial_rows(campaign["id"])
            if int(trial["route_position"]) == int(route["position"])
        ]
        trial_number = len(prior) + 1
        sequence = len(self._trial_rows(campaign["id"])) + 1
        task_id = self._trial_task_id(campaign["id"], int(route["position"]), trial_number)
        trial_id = task_id
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(
                "SELECT state FROM residue_trials WHERE id=?", (trial_id,)
            ).fetchone()
            if existing is None:
                db.execute(
                    """INSERT INTO residue_trials(
                      id,campaign_id,route_position,trial_number,sequence,task_id,state,
                      created_at,updated_at
                    ) VALUES(?,?,?,?,?,?, 'PREPARING',?,?)""",
                    (
                        trial_id,
                        campaign["id"],
                        route["position"],
                        trial_number,
                        sequence,
                        task_id,
                        stamp,
                        stamp,
                    ),
                )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        if not self.exists(task_id):
            try:
                self.create_task(
                    {
                        "id": task_id,
                        "title": (
                            f"[{campaign['title']}] {route['label']} trial {trial_number}"
                        )[:160],
                        "task": campaign["task"]["task"],
                        "files": campaign["task"]["files"],
                        "acceptance": campaign["task"]["acceptance"],
                        "manifest": route["manifest"],
                        "arm": route["arm"],
                        "priority": campaign["task"]["priority"],
                        "scheduled_for": campaign["task"].get("scheduled_for"),
                        "queue_now": True,
                        "approval_required": False,
                    }
                )
            except Exception as exc:
                self.db().execute(
                    """UPDATE residue_trials SET state='ERROR',outcome='error',
                       result_json=?,updated_at=? WHERE id=?""",
                    (
                        canonical(
                            {
                                "task_id": task_id,
                                "outcome": "error",
                                "error": f"trial task creation failed: {type(exc).__name__}: {exc}",
                                "settled_at": now(),
                            }
                        ),
                        now(),
                        trial_id,
                    ),
                )
                return
        task = self.get_task(task_id, False)
        state = task["state"] if task else "ERROR"
        self.db().execute(
            "UPDATE residue_trials SET state=?,updated_at=? WHERE id=?",
            (state, now(), trial_id),
        )
        self.event(
            "residue.trial.dispatched",
            task_id=task_id,
            detail={
                "campaign_id": campaign["id"],
                "route_id": route["route_id"],
                "trial_number": trial_number,
                "sequence": sequence,
            },
        )

    def _set_route_inconclusive(self, campaign_id: str, position: int, evidence: dict) -> None:
        value = {**evidence, "state": "inconclusive", "reason": "trial ceiling reached"}
        self.db().execute(
            """UPDATE residue_routes SET state='inconclusive',evidence_json=?,updated_at=?
               WHERE campaign_id=? AND position=?""",
            (canonical(value), now(), campaign_id, position),
        )

    def _drive_local_first(self, campaign: dict[str, Any], allow_dispatch: bool) -> None:
        rungs = [route["route_id"] for route in campaign["routes"]]
        policy_trials = self._policy_trials(campaign["id"])
        decision = decision_for_task(policy_trials, campaign["id"], rungs, int(campaign["k"]))
        route_by_id = {route["route_id"]: route for route in campaign["routes"]}
        if decision["action"] == "seal":
            route = route_by_id[decision["route_to"]]
            self._complete_campaign(
                campaign["id"],
                "CLEARED",
                winner_position=int(route["position"]),
                reason=decision["reason"],
                policy_decision=decision,
            )
            return
        if decision["action"] == "abstain":
            self._complete_campaign(
                campaign["id"],
                "EXHAUSTED",
                reason=decision["reason"],
                policy_decision=decision,
            )
            return
        route = route_by_id[decision["route_to"]]
        route_trials = [
            trial
            for trial in campaign["routes"][int(route["position"])]["trials"]
        ]
        if len(route_trials) >= int(campaign["max_trials_per_route"]):
            evidence = rung_evidence(policy_trials, route["route_id"], int(campaign["k"]))
            self._set_route_inconclusive(campaign["id"], int(route["position"]), evidence)
            self._complete_campaign(
                campaign["id"],
                "INCONCLUSIVE",
                reason=(
                    f"{route['route_id']} reached max_trials_per_route without a "
                    "K-of-K clear or wall; non-decisive evidence does not buy frontier escalation"
                ),
                policy_decision=decision,
            )
            return
        if allow_dispatch:
            self._dispatch_trial(campaign, route)

    def _drive_survey(self, campaign: dict[str, Any], allow_dispatch: bool) -> None:
        policy_trials = self._policy_trials(campaign["id"])
        all_settled = True
        any_inconclusive = False
        for route in campaign["routes"]:
            evidence = rung_evidence(policy_trials, route["route_id"], int(campaign["k"]))
            if evidence["state"] in {"clears", "wall"}:
                continue
            if len(route["trials"]) >= int(campaign["max_trials_per_route"]):
                self._set_route_inconclusive(campaign["id"], int(route["position"]), evidence)
                any_inconclusive = True
                continue
            all_settled = False
            if allow_dispatch:
                self._dispatch_trial(campaign, route)
            return
        if not all_settled:
            return
        refreshed = self.get_campaign(campaign["id"])
        assert refreshed is not None
        clear_routes = [route for route in refreshed["routes"] if route["state"] == "clears"]
        any_inconclusive = any(
            route["state"] == "inconclusive" for route in refreshed["routes"]
        )
        if clear_routes:
            winner = clear_routes[0]
            self._complete_campaign(
                campaign["id"],
                "COMPLETED" if not any_inconclusive else "INCONCLUSIVE",
                winner_position=int(winner["position"]),
                reason=(
                    "survey completed across every declared route"
                    if not any_inconclusive
                    else "survey found a clearing route but one or more routes remained inconclusive"
                ),
            )
        elif any_inconclusive:
            self._complete_campaign(
                campaign["id"], "INCONCLUSIVE", reason="survey ended with inconclusive routes"
            )
        else:
            self._complete_campaign(
                campaign["id"], "EXHAUSTED", reason="every surveyed route reached a K-of-K wall"
            )

    def _campaign_result(
        self,
        campaign: dict[str, Any],
        state: str,
        winner_position: int | None,
        reason: str,
        policy_decision: dict[str, Any] | None,
    ) -> dict[str, Any]:
        trials = self._trial_rows(campaign["id"])
        routes = self._route_rows(campaign["id"])
        winner = next(
            (route for route in routes if route["position"] == winner_position), None
        )
        selected = None
        if winner is not None:
            accepted = [
                trial
                for trial in trials
                if trial["route_position"] == winner_position and trial["outcome"] == "pass"
            ]
            if accepted:
                selected = accepted[max(0, len(accepted) - int(campaign["k"]))]
        attempted_positions = {int(trial["route_position"]) for trial in trials}
        skipped = [
            {
                "route_id": route["route_id"],
                "position": route["position"],
                "execution_class": route["execution_class"],
                "estimated_max_cost_usd": route["estimated_max_cost_usd"],
            }
            for route in routes
            if int(route["position"]) not in attempted_positions
        ]
        return {
            "schema": "tier-bench/frontier-residue-campaign-result@1",
            "campaign_id": campaign["id"],
            "state": state,
            "mode": campaign["mode"],
            "task_fingerprint": hash_json(campaign["task"]),
            "reason": reason,
            "k": campaign["k"],
            "max_trials_per_route": campaign["max_trials_per_route"],
            "winner": {
                "route_id": winner["route_id"],
                "position": winner["position"],
                "binding": winner["binding"],
                "execution_class": winner["execution_class"],
                "source_access": winner["source_access"],
                "selected_trial": selected,
            }
            if winner
            else None,
            "trials_run": len(trials),
            "local_trials": sum(1 for trial in trials if trial["execution_class"] == "local"),
            "remote_trials": sum(1 for trial in trials if trial["execution_class"] != "local"),
            "observed_cost_usd": sum(
                float((trial.get("result") or {}).get("cost_usd", 0) or 0)
                for trial in trials
            ),
            "routes_not_called": skipped,
            "remote_routes_not_called": sum(
                1 for route in skipped if route["execution_class"] != "local"
            ),
            "estimated_upper_bound_not_spent_usd": sum(
                float(route["estimated_max_cost_usd"] or 0)
                for route in skipped
                if route["estimated_max_cost_usd"] is not None
            ),
            "policy_decision": policy_decision,
            "claim_ceiling": (
                "The exact frozen task and acceptance predicate cleared or failed on the recorded "
                "routes and trials. This result does not establish general model superiority, a "
                "weight-level mechanism, or transfer to untested tasks."
            ),
        }

    def _maybe_candidate(
        self, campaign: dict[str, Any], winner_position: int
    ) -> dict[str, Any] | None:
        if not campaign["policy"].get("materialize_candidates", True) or winner_position <= 0:
            return None
        routes = self._route_rows(campaign["id"])
        winner = next(route for route in routes if route["position"] == winner_position)
        earlier = [route for route in routes if route["position"] < winner_position]
        if any(route["state"] == "clears" for route in earlier):
            return None
        kinds = {route["state"] for route in earlier}
        kind = (
            "capability_residue"
            if kinds and kinds <= {"wall"}
            else "transport_contaminated_residue"
        )
        trials = self._trial_rows(campaign["id"])
        winner_trials = [
            trial for trial in trials if trial["route_position"] == winner_position
        ]
        lower_trials = [
            trial for trial in trials if trial["route_position"] < winner_position
        ]
        capture_mode = (
            "mechanistic"
            if winner["source_access"]
            in {"source_and_weights", "weights", "runtime_source"}
            else "behavioral"
        )
        evidence = {
            "schema": CANDIDATE_SCHEMA,
            "campaign_id": campaign["id"],
            "task_fingerprint": hash_json(campaign["task"]),
            "kind": kind,
            "scope": "exact_frozen_task",
            "k": campaign["k"],
            "evidence_floor": (
                "single_trial_candidate" if int(campaign["k"]) == 1 else "repeated_trial_candidate"
            ),
            "lower_routes": earlier,
            "lower_trials": lower_trials,
            "winning_route": winner,
            "winning_trials": winner_trials,
            "capture_plan": {
                "mode": capture_mode,
                "next_gate": (
                    "produce a reusable artifact, then pass distinct hidden-graded replays through "
                    "the existing capture ledger before claiming amortization"
                ),
                "source_access": winner["source_access"],
            },
            "prohibited_interpretations": [
                "general model superiority",
                "recovered or inferred proprietary weights",
                "mechanism established from behavioral success alone",
                "capture completed without a reusable artifact and replay receipts",
            ],
        }
        candidate_id = "res-" + hashlib.sha256(
            f"{campaign['id']}:{winner_position}:{evidence['task_fingerprint']}".encode()
        ).hexdigest()[:16]
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                """INSERT OR IGNORE INTO residue_candidates(
                  id,campaign_id,winning_position,kind,state,evidence_json,created_at
                ) VALUES(?,?,?,?, 'CANDIDATE',?,?)""",
                (
                    candidate_id,
                    campaign["id"],
                    winner_position,
                    kind,
                    canonical(evidence),
                    stamp,
                ),
            )
            self.event(
                "residue.candidate.created",
                detail={
                    "campaign_id": campaign["id"],
                    "candidate_id": candidate_id,
                    "kind": kind,
                },
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        candidate = self.get_residue_candidate(candidate_id)
        assert candidate is not None
        self._write_candidate_projection(candidate)
        return candidate

    def _complete_campaign(
        self,
        campaign_id: str,
        state: str,
        *,
        winner_position: int | None = None,
        reason: str,
        policy_decision: dict[str, Any] | None = None,
    ) -> None:
        campaign = self.get_campaign(campaign_id)
        if campaign is None or campaign["state"] != "ACTIVE":
            return
        result = self._campaign_result(
            campaign, state, winner_position, reason, policy_decision
        )
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                """UPDATE residue_campaigns SET state=?,result_json=?,updated_at=?,completed_at=?,
                   last_error=? WHERE id=? AND state='ACTIVE'""",
                (
                    state,
                    canonical(result),
                    stamp,
                    stamp,
                    reason if state in {"ERROR", "INCONCLUSIVE", "BUDGET_BLOCKED"} else None,
                    campaign_id,
                ),
            )
            self.event(
                "residue.campaign.completed",
                detail={"campaign_id": campaign_id, "state": state, "reason": reason},
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        refreshed = self.get_campaign(campaign_id)
        assert refreshed is not None
        if winner_position is not None:
            self._maybe_candidate(refreshed, winner_position)
            refreshed = self.get_campaign(campaign_id)
            assert refreshed is not None
        self._write_campaign_projection(refreshed)

    def _fail_campaign(self, campaign_id: str, message: str) -> None:
        self._complete_campaign(campaign_id, "ERROR", reason=message)

    def _write_json_atomic(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _write_campaign_projection(self, campaign: dict[str, Any]) -> None:
        self._write_json_atomic(
            self.residue_root / "campaigns" / f"{campaign['id']}.json", campaign
        )

    def _write_candidate_projection(self, candidate: dict[str, Any]) -> None:
        self._write_json_atomic(
            self.residue_root / "candidates" / f"{candidate['id']}.json", candidate
        )

    def tick_residue_campaigns(self, allow_dispatch: bool = True) -> None:
        rows = self.db().execute(
            "SELECT id FROM residue_campaigns WHERE state='ACTIVE' ORDER BY created_at"
        ).fetchall()
        for row in rows:
            campaign_id = row["id"]
            try:
                self._settle_trials(campaign_id)
                campaign = self.get_campaign(campaign_id)
                if campaign is None or campaign["state"] != "ACTIVE":
                    continue
                self._update_route_evidence(campaign)
                campaign = self.get_campaign(campaign_id)
                assert campaign is not None
                if self.campaign_active_task(campaign_id):
                    self._write_campaign_projection(campaign)
                    continue
                if campaign["mode"] == "local_first":
                    self._drive_local_first(campaign, allow_dispatch)
                else:
                    self._drive_survey(campaign, allow_dispatch)
                refreshed = self.get_campaign(campaign_id)
                if refreshed is not None:
                    self._write_campaign_projection(refreshed)
            except Exception as exc:
                self._fail_campaign(
                    campaign_id,
                    f"residue controller failure: {type(exc).__name__}: {exc}",
                )
