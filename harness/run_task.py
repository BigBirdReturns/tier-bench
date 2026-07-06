from __future__ import annotations

from pathlib import Path

from cost_guard import Tier, model_available
from harness.attempt import run_attempt
from harness.composites import composite_available, composites_for_tier, run_composite
from harness.config import RunConfig, models_for_tier
from harness.record import append_jsonl
from harness.task_schema import Task


def run_task(task_json: Path, cfg: RunConfig) -> None:
    task = Task.from_json(task_json)
    tier = Tier[task.tier]

    # Plain models first. Models whose provider has no key (or whose local
    # runtime is down) are skipped, not failed — an unreachable provider says
    # nothing about the model, and junk rows would poison success rates the
    # routing table and diff report are built from.
    for rank, model in enumerate(models_for_tier(tier)):
        if not model_available(model):
            print(f"  ~ skip {model} on {task.task_id}: provider unavailable")
            continue
        row, _ = run_attempt(task, tier, model)
        row["routing_rank"] = rank
        append_jsonl(cfg.results_path, row)

    # Composite candidates (cascade / best-of-n / driver-repair) run through
    # the exact same attempt+validation path and land as first-class rows.
    for comp in composites_for_tier(tier):
        if not composite_available(comp):
            print(f"  ~ skip composite {comp.name} on {task.task_id}: member provider unavailable")
            continue
        row = run_composite(task, tier, comp)
        append_jsonl(cfg.results_path, row)
