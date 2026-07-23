"""Card witness 2: scope escape (write outside declared files) -> refusal.

The fixture backend writes outside.py, which was never in --files, so the
candidate sees a restricted packet but the runner still catches the escape
when it syncs the worktree back.
"""

from __future__ import annotations

from pathlib import Path

from tier_runner.core import run_task

from .. import common

WITNESS_ID = 2
CARD_TEXT = "Scope escape (write outside declared files) -> refusal."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(
        tmp_path, common.backend_source(write_app=True, write_outside=True, app_value=2)
    )
    receipt = run_task(
        repo=repo,
        task_id="w2-scope-bad",
        task="attempt scope escape",
        files=["app.py"],
        acceptance=common.acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=tmp_path / "out",
    )
    assert receipt["state"] == "ERROR", receipt
    assert receipt["changes"]["scope_violations"] == ["outside.py"], receipt
    return receipt["errors"]
