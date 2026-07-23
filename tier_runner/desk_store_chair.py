from __future__ import annotations

import re
from typing import Any

from .desk_common import DeskError, as_bool, canonical, load_json, normalize_files, now


REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")


class DeskStoreChairMixin:
    def register_chair_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id", "")).strip()
        repo = str(payload.get("repo", "")).strip()
        base_sha = str(payload.get("base_sha", "")).strip().lower()
        acceptance = str(payload.get("acceptance", "")).strip()
        if not REQUEST_ID.fullmatch(request_id):
            raise DeskError("request_id must use 1-80 letters, digits, dot, underscore, or dash")
        if not REPOSITORY.fullmatch(repo):
            raise DeskError("repo must be an exact owner/name GitHub repository")
        if not SHA.fullmatch(base_sha):
            raise DeskError("base_sha must be an exact 40-character lowercase commit SHA")
        if not acceptance or len(acceptance) > 8000 or "\n" in acceptance or "\r" in acceptance:
            raise DeskError("acceptance must be one non-empty command line")
        allowed_paths = normalize_files(payload.get("allowed_paths"))
        auto_validate = as_bool(payload.get("auto_validate", False), "auto_validate")
        if auto_validate:
            raise DeskError(
                "Chair auto-validation is disabled until an immutable-head executor exists"
            )
        allow_forks = as_bool(payload.get("allow_forks", False), "allow_forks")
        stamp = now()
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute(
                "SELECT 1 FROM chair_requests WHERE request_id=?", (request_id,)
            ).fetchone():
                raise DeskError(f"chair request already exists: {request_id}")
            db.execute(
                """INSERT INTO chair_requests(
                  request_id,repo,base_sha,allowed_paths_json,acceptance,
                  auto_validate,allow_forks,status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    repo,
                    base_sha,
                    canonical(allowed_paths),
                    acceptance,
                    0,
                    int(allow_forks),
                    "ACTIVE",
                    stamp,
                    stamp,
                ),
            )
            self.event(
                "chair.request.registered",
                detail={"request_id": request_id, "repo": repo, "base_sha": base_sha},
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_chair_request(request_id)
        assert result is not None
        return result

    @staticmethod
    def _chair_request(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["allowed_paths"] = load_json(item.pop("allowed_paths_json"), [])
        item["auto_validate"] = bool(item["auto_validate"])
        item["allow_forks"] = bool(item["allow_forks"])
        return item

    def get_chair_request(self, request_id: str) -> dict[str, Any] | None:
        row = self.db().execute(
            "SELECT * FROM chair_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        return self._chair_request(row) if row else None

    def list_chair_requests(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM chair_requests"
        if active_only:
            sql += " WHERE status='ACTIVE'"
        sql += " ORDER BY created_at,request_id"
        return [self._chair_request(row) for row in self.db().execute(sql).fetchall()]

    def chair_return_seen(self, repo: str, pr_number: int, head_sha: str) -> bool:
        return self.db().execute(
            "SELECT 1 FROM chair_returns WHERE repo=? AND pr_number=? AND head_sha=?",
            (repo, pr_number, head_sha),
        ).fetchone() is not None

    def _insert_chair_return(
        self,
        db: Any,
        *,
        repo: str,
        pr_number: int,
        head_sha: str,
        request_id: str | None,
        base_sha: str | None,
        status: str,
        reason: str | None,
        task_id: str | None,
        detail: dict[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO chair_returns(
              repo,pr_number,head_sha,request_id,base_sha,status,reason,
              task_id,detail_json,observed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                repo,
                pr_number,
                head_sha,
                request_id,
                base_sha,
                status,
                reason,
                task_id,
                canonical(detail),
                now(),
            ),
        )

    def record_chair_return(
        self,
        *,
        repo: str,
        pr_number: int,
        head_sha: str,
        head_repo: str,
        request_id: str | None,
        base_sha: str | None,
        status: str,
        reason: str | None = None,
        task_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(detail or {})
        payload.setdefault("head_repo", head_repo)
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            self._insert_chair_return(
                db,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                request_id=request_id,
                base_sha=base_sha,
                status=status,
                reason=reason,
                task_id=task_id,
                detail=payload,
            )
            self.event(
                f"chair.return.{status.lower()}",
                task_id=task_id,
                detail={
                    "repo": repo,
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "head_repo": head_repo,
                    "request_id": request_id,
                    "reason": reason,
                },
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    def accept_chair_return(
        self,
        *,
        request_id: str,
        repo: str,
        pr_number: int,
        head_sha: str,
        head_repo: str,
        base_sha: str,
        task: dict[str, Any],
        detail: dict[str, Any],
    ) -> dict[str, Any] | None:
        db = self.db()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT status FROM chair_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None or row["status"] != "ACTIVE":
                db.execute("ROLLBACK")
                return None
            stamp = now()
            db.execute(
                """INSERT INTO tasks(
                  id,title,task,files_json,acceptance,manifest,arm,priority,state,scheduled_for,
                  approval_required,approved_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task["id"],
                    task["title"],
                    task["task"],
                    canonical(task["files"]),
                    task["acceptance"],
                    task["manifest"],
                    task["arm"],
                    int(task["priority"]),
                    "DRAFT",
                    None,
                    1,
                    None,
                    stamp,
                    stamp,
                ),
            )
            self._insert_chair_return(
                db,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                request_id=request_id,
                base_sha=base_sha,
                status="ACCEPTED",
                reason=None,
                task_id=task["id"],
                detail=detail,
            )
            updated = db.execute(
                "UPDATE chair_requests SET status='CONSUMED',updated_at=? "
                "WHERE request_id=? AND status='ACTIVE'",
                (stamp, request_id),
            )
            if updated.rowcount != 1:
                raise DeskError("chair request was consumed concurrently")
            self.event(
                "task.created",
                task_id=task["id"],
                detail={"state": "DRAFT", "source": "chair", "approval_required": True},
                db=db,
            )
            self.event(
                "chair.return.accepted",
                task_id=task["id"],
                detail={
                    "repo": repo,
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "head_repo": head_repo,
                    "request_id": request_id,
                    "reason": None,
                },
                db=db,
            )
            self.event(
                "chair.request.consumed",
                task_id=task["id"],
                detail={"request_id": request_id},
                db=db,
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        result = self.get_task(task["id"], False)
        assert result is not None
        return result

    def list_chair_returns(self) -> list[dict[str, Any]]:
        result = []
        rows = self.db().execute(
            "SELECT * FROM chair_returns ORDER BY observed_at DESC,repo,pr_number"
        ).fetchall()
        for row in rows:
            item = dict(row)
            item["detail"] = load_json(item.pop("detail_json"), {})
            result.append(item)
        return result
