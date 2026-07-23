"""Card witness 4: empty patch presented as success -> not ACCEPTED.

The fixture backend reports outcome="pass" with valid telemetry but touches
no file in the worktree. A backend cannot claim success while producing
nothing; the runner must refuse rather than emit an ACCEPTED empty patch.
"""

from __future__ import annotations

from pathlib import Path

from tier_runner.core import run_task

from .. import common

WITNESS_ID = 4
CARD_TEXT = "Empty patch presented as success -> not ACCEPTED."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(tmp_path, common.backend_source(write_app=False))
    receipt = run_task(
        repo=repo,
        task_id="w4-empty-patch",
        task="claim success without changing anything",
        files=["app.py"],
        acceptance=common.acceptance(1),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=tmp_path / "out",
    )
    assert receipt["state"] != "ACCEPTED", receipt
    return receipt["errors"]
