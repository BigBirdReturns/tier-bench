"""Card witness 6: candidate modified BY the verifier -> refusal (verifier is read-only).

The operator-supplied acceptance command itself writes to app.py while
"verifying" it. The runner diffs the candidate tree before and after
acceptance and refuses rather than emit a patch that does not represent
what acceptance actually tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tier_runner.core import run_task

from .. import common

WITNESS_ID = 6
CARD_TEXT = "Candidate modified BY the verifier -> refusal (verifier is read-only)."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(tmp_path, common.backend_source(write_app=True, app_value=2))
    receipt = run_task(
        repo=repo,
        task_id="w6-acceptance-mutates",
        task="make value return two",
        files=["app.py"],
        acceptance=f'"{sys.executable}" accept_mutate.py',
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=tmp_path / "out",
    )
    assert receipt["state"] == "ERROR", receipt
    return receipt["errors"]
