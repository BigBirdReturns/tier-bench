from pathlib import Path

from harness.rig import Rig
from scripts.rig_report import build_report, render_text


GRAM_3090_A = {
    "uuid": "GPU-gram-3090-a",
    "name": "NVIDIA GeForce RTX 3090",
    "vram_gb": 24.0,
}
GRAM_3090_B = {
    "uuid": "GPU-gram-3090-b",
    "name": "NVIDIA GeForce RTX 3090",
    "vram_gb": 24.0,
}


def test_two_independent_3090s_are_not_reported_as_one_48_gb_fit_pool() -> None:
    rig = Rig(
        ram_gb=64.0,
        cpu_cores=16,
        gpus=[GRAM_3090_A, GRAM_3090_B],
    )

    report = build_report(rig, Path("does-not-exist.jsonl"))
    reported_rig = report["rig"]

    assert reported_rig["aggregate_vram_gb"] == 48.0
    assert reported_rig["usable_gb"] == 22.8
    assert reported_rig["max_params_B_q4"] == 30.4
    assert reported_rig["class"] == "multi-GPU workstation (independent devices)"
    assert reported_rig["capacity_pooling"] == {
        "status": "not_pooled",
        "qualified": False,
    }
    assert [
        (node["gpu_ids"], node["vram_gb"], node["usable_gb"])
        for node in reported_rig["resource_nodes"]
    ] == [
        ([GRAM_3090_A["uuid"]], 24.0, 22.8),
        ([GRAM_3090_B["uuid"]], 24.0, 22.8),
    ]

    text = render_text(report)
    assert "48.0 GB aggregate inventory is not pooled or qualified" in text
    assert "~22.8 GB on the largest independent device" in text
