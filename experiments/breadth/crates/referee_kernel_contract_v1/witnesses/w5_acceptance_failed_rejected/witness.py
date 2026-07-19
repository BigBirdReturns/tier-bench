"""Card witness 5: failed acceptance -> REJECTED with the acceptance output preserved.

The backend produces a real change, but the operator's acceptance command
does not pass against it. The run must terminate REJECTED (not ERROR, not
ACCEPTED), and the acceptance stdout/stderr artifacts must survive.
"""

from __future__ import annotations

from pathlib import Path

from tier_runner.core import run_task

from .. import common

WITNESS_ID = 5
CARD_TEXT = "Failed acceptance -> REJECTED with the acceptance output preserved."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(tmp_path, common.backend_source(write_app=True, app_value=2))
    out = tmp_path / "out"
    receipt = run_task(
        repo=repo,
        task_id="w5-acceptance-bad",
        task="make value return two",
        files=["app.py"],
        acceptance=common.acceptance(3),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "REJECTED", receipt
    assert receipt["acceptance"]["returncode"] != 0, receipt
    assert (out / receipt["acceptance"]["stdout_path"]).exists()
    assert (out / receipt["acceptance"]["stderr_path"]).exists()
    assert (out / "change.patch").exists()
    return receipt["errors"]
