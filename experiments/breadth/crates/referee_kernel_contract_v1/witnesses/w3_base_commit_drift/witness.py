"""Card witness 3: changed base bytes (repo drifted from frozen commit) -> refusal.

The runner reads the backend manifest as a Git blob at the exact frozen base
commit (HEAD), never from working-tree bytes. Leaving pilot_backends.json
uncommitted means the frozen base has drifted from what the operator
believes is staged -- the runner must refuse before ever invoking a backend.
"""

from __future__ import annotations

from pathlib import Path

from tier_runner.core import RunError, run_task

from .. import common

WITNESS_ID = 3
CARD_TEXT = "Changed base bytes (repo drifted from frozen commit) -> refusal."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(
        tmp_path,
        common.backend_source(write_app=True, app_value=2),
        commit_manifest=False,
    )
    try:
        run_task(
            repo=repo,
            task_id="w3-base-drift",
            task="use an uncommitted manifest",
            files=["app.py"],
            acceptance=common.acceptance(2),
            manifest=repo / "pilot_backends.json",
            arm="arm_b",
            output_dir=tmp_path / "out",
        )
    except RunError as exc:
        return [str(exc)]
    raise AssertionError("run_task accepted a manifest that is not committed at base")
