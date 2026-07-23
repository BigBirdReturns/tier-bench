"""Card witness 1: acceptance-command mutation between freeze and evaluation -> refusal.

Freezes a run to ACCEPTED (acceptance command bound into the dispatch
receipt's acceptance_sha256), then tampers only receipt.json's
acceptance_command after the fact and re-evaluates with `tier verify`.
"""

from __future__ import annotations

import json
from pathlib import Path

from tier_runner.core import run_task, verify_run

from .. import common

WITNESS_ID = 1
CARD_TEXT = "Acceptance-command mutation between freeze and evaluation -> refusal."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(tmp_path, common.backend_source(write_app=True, app_value=2))
    out = tmp_path / "out"
    receipt = run_task(
        repo=repo,
        task_id="w1-accepted",
        task="make value return two",
        files=["app.py"],
        acceptance=common.acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED", receipt

    receipt_path = out / "receipt.json"
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    on_disk["acceptance_command"] = on_disk["acceptance_command"] + " # tampered post-freeze"
    receipt_path.write_text(json.dumps(on_disk), encoding="utf-8")

    return verify_run(out)
