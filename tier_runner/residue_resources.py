"""Scarce-resource lanes for Frontier Residue Refinery campaigns.

A route may name a physical GPU, subscription window, API quota, or other
exclusive execution resource. Campaigns sharing a resource key are admitted
through one persistent lane, independent of the Desk's general worker count.
"""
from __future__ import annotations

import copy
from typing import Any

from .desk_common import DeskError, as_bool, as_int, now
from .residue_common import SAFE_RESOURCE


class ResidueResourceMixin:
    def init_residue(self) -> None:
        super().init_residue()
        self.db().executescript(
            """
            CREATE TABLE IF NOT EXISTS residue_resource_lanes(
              campaign_id TEXT NOT NULL,
              route_position INTEGER NOT NULL,
              resource_key TEXT NOT NULL,
              max_concurrency INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(campaign_id, route_position),
              FOREIGN KEY(campaign_id, route_position)
                REFERENCES residue_routes(campaign_id, position) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_residue_resource_key
              ON residue_resource_lanes(resource_key);
            """
        )

    def _normalize_resource_declarations(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, list):
            return []
        declarations: list[dict[str, Any]] = []
        for position, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("resource_key") or "").strip() or None
            if key is not None and (
                len(key) > 80 or not SAFE_RESOURCE.fullmatch(key)
            ):
                raise DeskError(
                    f"campaign route {position}.resource_key must be at most 80 characters "
                    "and contain only letters, digits, dot, underscore, slash, colon, and dash"
                )
            concurrency = as_int(
                raw.get("max_concurrency", 1),
                f"campaign route {position}.max_concurrency",
                1,
                32,
            )
            declarations.append(
                {
                    "position": position,
                    "resource_key": key,
                    "max_concurrency": concurrency,
                }
            )
        return declarations

    @staticmethod
    def _default_resource_key(route: dict[str, Any]) -> str | None:
        if route.get("execution_class") != "local":
            return None
        model_id = str((route.get("binding") or {}).get("model_id") or "").strip()
        candidate = f"local:{model_id}" if model_id else f"local:{route['route_id']}"
        if len(candidate) <= 80 and SAFE_RESOURCE.fullmatch(candidate):
            return candidate
        return f"local:{route['route_id']}"

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise DeskError("campaign payload must be a JSON object")
        declarations = self._normalize_resource_declarations(payload)
        requested_start = as_bool(payload.get("queue_now", False), "campaign queue_now")
        prepared = copy.deepcopy(payload)
        prepared["queue_now"] = False
        campaign = super().create_campaign(prepared)
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            for route, declaration in zip(campaign["routes"], declarations, strict=False):
                key = declaration["resource_key"] or self._default_resource_key(route)
                if not key:
                    continue
                db.execute(
                    """INSERT INTO residue_resource_lanes(
                      campaign_id,route_position,resource_key,max_concurrency,
                      created_at,updated_at
                    ) VALUES(?,?,?,?,?,?)""",
                    (
                        campaign["id"],
                        route["position"],
                        key,
                        declaration["max_concurrency"],
                        stamp,
                        stamp,
                    ),
                )
            self.event(
                "residue.resources.bound",
                detail={
                    "campaign_id": campaign["id"],
                    "resources": sum(
                        1
                        for route, declaration in zip(
                            campaign["routes"], declarations, strict=False
                        )
                        if declaration["resource_key"] or self._default_resource_key(route)
                    ),
                },
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            self.db().execute(
                "DELETE FROM residue_campaigns WHERE id=?", (campaign["id"],)
            )
            projection = self.residue_root / "campaigns" / f"{campaign['id']}.json"
            projection.unlink(missing_ok=True)
            raise
        campaign = self.get_campaign(campaign["id"])
        assert campaign is not None
        self._write_campaign_projection(campaign)
        return self.start_campaign(campaign["id"]) if requested_start else campaign

    def _route_rows(self, campaign_id: str) -> list[dict[str, Any]]:
        routes = super()._route_rows(campaign_id)
        rows = self.db().execute(
            """SELECT route_position,resource_key,max_concurrency
               FROM residue_resource_lanes WHERE campaign_id=?""",
            (campaign_id,),
        ).fetchall()
        by_position = {int(row["route_position"]): dict(row) for row in rows}
        for route in routes:
            lane = by_position.get(int(route["position"]))
            route["resource_key"] = lane["resource_key"] if lane else None
            route["max_concurrency"] = int(lane["max_concurrency"]) if lane else 1
        return routes

    def _resource_available(self, route: dict[str, Any]) -> bool:
        key = route.get("resource_key")
        if not key:
            return True
        row = self.db().execute(
            """SELECT
                 SUM(CASE WHEN t.state IN ('DRAFT','QUEUED','RUNNING') THEN 1 ELSE 0 END)
                   AS active,
                 MIN(rl.max_concurrency) AS lane_limit
               FROM residue_resource_lanes rl
               LEFT JOIN residue_trials rt
                 ON rt.campaign_id=rl.campaign_id
                AND rt.route_position=rl.route_position
               LEFT JOIN tasks t ON t.id=rt.task_id
               WHERE rl.resource_key=?""",
            (key,),
        ).fetchone()
        active = int(row["active"] or 0) if row else 0
        lane_limit = int(row["lane_limit"] or 1) if row else 1
        return active < lane_limit

    def _dispatch_trial(self, campaign: dict[str, Any], route: dict[str, Any]) -> None:
        if not self._resource_available(route):
            return
        super()._dispatch_trial(campaign, route)

    def _campaign_result(
        self,
        campaign: dict[str, Any],
        state: str,
        winner_position: int | None,
        reason: str,
        policy_decision: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = super()._campaign_result(
            campaign, state, winner_position, reason, policy_decision
        )
        routes = {route["route_id"]: route for route in self._route_rows(campaign["id"])}
        winner = result.get("winner")
        if winner:
            route = routes.get(winner.get("route_id"))
            if route:
                winner["resource_key"] = route.get("resource_key")
                winner["max_concurrency"] = route.get("max_concurrency", 1)
        for skipped in result.get("routes_not_called", []):
            route = routes.get(skipped.get("route_id"))
            if route:
                skipped["resource_key"] = route.get("resource_key")
                skipped["max_concurrency"] = route.get("max_concurrency", 1)
        return result
