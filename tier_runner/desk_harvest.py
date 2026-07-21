from __future__ import annotations

from pathlib import Path
from typing import Any


def _evidence(estate: Path, relative: str) -> bool:
    return (estate / relative).exists()


def harvested_orchestration(
    repo: Path, cartridges: dict[str, Any] | None
) -> dict[str, Any]:
    estate = repo.parents[1]
    arms = cartridges.get("arms", {}) if isinstance(cartridges, dict) else {}
    ready_models = {
        str(value.get("model_id"))
        for value in arms.values()
        if isinstance(value, dict) and value.get("model_id")
    }
    qwen_ready = "qwen3.5:9b-q4_K_M" in ready_models
    return {
        "doctrine": "Sol directs; narrow hands emit; deterministic receipts decide.",
        "lanes": [
            {
                "id": "sol",
                "label": "Sol",
                "role": "top driver",
                "state": "controller",
                "detail": "Breaks goals into bounded crates and decides escalation.",
                "evidence": _evidence(
                    estate,
                    "worktrees/luna-sol-anchor-replication-v2/experiments/sol_root_matched_config/.cart0/000.000.json",
                ),
            },
            {
                "id": "luna",
                "label": "Luna",
                "role": "planner",
                "state": "controller",
                "detail": "Cheap planning and continuation lane; cloud writes require a fresh canary.",
                "evidence": _evidence(
                    estate,
                    "worktrees/luna-sol-anchor-replication-v2/experiments/luna_sol_anchor_replication_v2/run_v2.py",
                ),
            },
            {
                "id": "qwen",
                "label": "Local Qwen",
                "role": "file hand",
                "state": "ready" if qwen_ready else "gated",
                "detail": (
                    "Zero-cost strict text emission; scope and acceptance are enforced outside the model."
                    if qwen_ready
                    else "Installed local floor is not activated by the committed manifest."
                ),
                "evidence": qwen_ready,
            },
            {
                "id": "spark",
                "label": "Spark",
                "role": "fast hand",
                "state": "gated",
                "detail": "Historical 3/3 writer proof exists; current Windows write transport must re-canary.",
                "evidence": _evidence(
                    estate,
                    "worktrees/luna-sol-anchor-replication-v2/experiments/luna_sol_anchor_replication_v2/SPARK_EXECUTION_SURFACE_V2_2_3_FREEZE.json",
                ),
            },
            {
                "id": "terra",
                "label": "Terra",
                "role": "residue verifier",
                "state": "controller",
                "detail": "Escalates only validator residue after cheaper hands fail.",
                "evidence": _evidence(
                    estate,
                    "worktrees/residue-bridge-v1/data/model_residue/spark_effort_public_v1",
                ),
            },
        ],
        "custody": {
            "admission": _evidence(
                estate, "worktrees/codex-chatgpt-dag-desk/scripts/admit_operator_work.py"
            ),
            "anchor": _evidence(
                estate, "worktrees/codex-crate-crossover-1/docs/CRATE_OPS.md"
            ),
            "referee": _evidence(
                estate, "worktrees/codex-crate-crossover-1/scripts/dispatch.py"
            ),
        },
    }
