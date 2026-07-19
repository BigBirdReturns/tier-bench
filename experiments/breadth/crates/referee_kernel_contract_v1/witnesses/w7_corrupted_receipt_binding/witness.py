"""Card witness 7: deliberately corrupted receipt -> `tier verify` refusal naming the binding.

After a clean ACCEPTED run, receipt.json's `arm` field is tampered directly
on disk (not through the runner). `tier verify` must recompute the bindings
from the sealed dispatch/ledger artifacts and name exactly which binding the
corrupted receipt no longer satisfies.
"""

from __future__ import annotations

import json
from pathlib import Path

from tier_runner.core import run_task, verify_run

from .. import common

WITNESS_ID = 7
CARD_TEXT = "Deliberately corrupted receipt -> `tier verify` refusal naming the binding."


def construct(tmp_path: Path) -> list[str]:
    repo = common.make_repo(tmp_path, common.backend_source(write_app=True, app_value=2))
    out = tmp_path / "out"
    receipt = run_task(
        repo=repo,
        task_id="w7-verify-semantic",
        task="make value return two",
        files=["app.py"],
        acceptance=common.acceptance(2),
        manifest=repo / "pilot_backends.json",
        arm="arm_b",
        output_dir=out,
    )
    assert receipt["state"] == "ACCEPTED", receipt
    assert verify_run(out) == []

    receipt_path = out / "receipt.json"
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    on_disk["arm"] = "arm_c"
    receipt_path.write_text(json.dumps(on_disk), encoding="utf-8")

    return verify_run(out)
