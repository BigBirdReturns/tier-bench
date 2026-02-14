from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from cost_guard import Tier
from harness.canonical import compare_to_canonical, save_canonical
from harness.config import RunConfig, models_for_tier
from harness.model_call import call_with_guard
from harness.prompting import render_prompt
from harness.record import append_jsonl
from harness.task_schema import Task
from harness.util_git import ensure_git_repo, git_commit_all
from harness.validators import capture_behavior, validate_all

def _tier_requires_canonical(tier: Tier) -> bool:
    # Canonical exact-match enforcement only for T0 clerical tasks.
    return tier == Tier.T0

def run_task(task_json: Path, cfg: RunConfig) -> None:
    task = Task.from_json(task_json)
    tier = Tier[task.tier]

    models = models_for_tier(tier)

    for rank, model in enumerate(models):
        with tempfile.TemporaryDirectory(prefix=f"{task.task_id}__") as td:
            work = Path(td)
            shutil.copytree(task.fixture_dir, work / "repo", dirs_exist_ok=True)
            repo = work / "repo"

            ensure_git_repo(repo)
            git_commit_all(repo, "baseline")

            # Baseline behavior before edits
            baseline_snapshot = capture_behavior(repo, task.run_command)
            baseline = {"rc": baseline_snapshot[0], "stdout": baseline_snapshot[1], "stderr": baseline_snapshot[2]}

            prompt = render_prompt(task.prompt_template, repo, task.target_relpath, baseline=baseline)

            call = call_with_guard(model=model, tier=tier, prompt=prompt)

            row = {
                "task_id": task.task_id,
                "tier": task.tier,
                "model": model,
                "routing_rank": rank,
                "status": call.get("status"),
                "estimated_cost": call.get("estimated_cost"),
                "actual_cost": call.get("cost"),
            }

            # Cost stability guard: if we cannot read actual_cost, mark and fail the row.
            actual_cost = row.get("actual_cost")
            if not isinstance(actual_cost, (int, float)):
                row["cost_missing"] = True
                row["pass"] = False
                row["reason"] = "cost_missing_or_non_numeric"
                append_jsonl(cfg.results_path, row)
                continue
            row["cost_missing"] = False

            if call.get("status") != "ok" or not call.get("content"):
                row["pass"] = False
                row["reason"] = call.get("reason", "model_call_failed")
                append_jsonl(cfg.results_path, row)
                continue

            # Apply output (after sanitization happens in model_call wrapper)
            target_path = repo / task.target_relpath
            target_path.write_text(call["content"], encoding="utf-8")

            # After behavior
            after_snapshot = capture_behavior(repo, task.run_command)

            v = validate_all(
                cwd=repo,
                target_relpath=task.target_relpath,
                run_command=task.run_command,
                max_lines_changed=task.max_lines_changed,
                allowed_files=task.allowed_files,
                require_functional_equivalence=bool(task.validate.get("functional_equivalence")),
                require_ruff_imports=bool(task.validate.get("ruff_imports")),
                require_compile=bool(task.validate.get("compile")),
                require_tests=bool(task.validate.get("tests")),
                before=baseline_snapshot,
                after=after_snapshot,
            )

            root = Path.cwd()
            canonical_match = compare_to_canonical(task.task_id, root, call["content"])
            if v.pass_all and canonical_match is None:
                save_canonical(task.task_id, root, call["content"])
                canonical_match = True
                row["baseline_established"] = True
            else:
                row["baseline_established"] = False

            row.update({
                "compile_ok": v.compile_ok,
                "ruff_imports_ok": v.ruff_imports_ok,
                "functional_equivalence": v.functional_equivalence,
                "diff_lines": v.diff_lines,
                "changed_files": v.changed_files,
                "diff_numstat": v.notes.get("diff_numstat", []),
                "allowed_files_ok": v.allowed_files_ok,
                "max_lines_ok": v.max_lines_ok,
                "tests_ok": v.tests_ok,
                "canonical_match": canonical_match,
                "notes": v.notes,
            })

            # Pass criteria: deterministic checks + (canonical only enforced for T0)
            if _tier_requires_canonical(tier):
                row["pass"] = bool(v.pass_all and (canonical_match is True))
            else:
                row["pass"] = bool(v.pass_all)

            append_jsonl(cfg.results_path, row)
