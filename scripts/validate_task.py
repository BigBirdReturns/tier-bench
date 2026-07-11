"""
Validate contributed tasks before they enter the harness.

Usage:
    python scripts/validate_task.py tasks/t2_my_new_task_001.json
    python scripts/validate_task.py tasks/  # validate all tasks in directory

Exit 0 = valid, Exit 1 = problems found.

This is the boundary gate. A task that passes this script will not crash the harness.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REQUIRED_FIELDS = ["task_id", "tier", "prompt_template", "fixture_dir",
                   "target_relpath", "run_command", "validate",
                   "max_lines_changed", "allowed_files"]

VALID_TIERS = {"T0", "T1", "T2", "T3", "T4", "T5"}

VALID_VALIDATE_FLAGS = {"compile", "ruff_imports", "functional_equivalence", "tests"}

TEMPLATE_VARS = {"{target_relpath}", "{file_content}", "{baseline_rc}",
                 "{baseline_stdout}", "{baseline_stderr}", "{context_files}"}

# These landed before the tier-prefix contribution rule and already have sealed
# receipts keyed by their opaque-stable IDs. New tasks still must use tN_*.
LEGACY_STABLE_TASK_IDS = {
    "almanac_exception_class_001",
    "almanac_record_binding_001",
    "almanac_rule_boundary_001",
}


def validate_task(path: Path) -> list[str]:
    """Returns list of problems. Empty list = valid."""
    problems = []

    # 1. JSON parseable
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except Exception as e:
        return [f"Cannot read file: {e}"]

    # 2. Required fields
    for field in REQUIRED_FIELDS:
        if field not in raw:
            problems.append(f"Missing required field: '{field}'")
    if problems:
        return problems  # Can't validate further without required fields

    # 3. Tier
    tier = raw["tier"]
    if tier not in VALID_TIERS:
        problems.append(f"Invalid tier: '{tier}'. Must be one of {VALID_TIERS}")

    # 4. Task ID convention: must start with tier prefix
    task_id = raw["task_id"]
    expected_prefix = tier.lower() + "_"
    if not task_id.startswith(expected_prefix) and task_id not in LEGACY_STABLE_TASK_IDS:
        problems.append(f"task_id '{task_id}' should start with '{expected_prefix}'")

    # 5. Fixture directory exists
    fixture_dir = Path(raw["fixture_dir"])
    if not fixture_dir.exists():
        problems.append(f"fixture_dir '{fixture_dir}' does not exist")
    elif not fixture_dir.is_dir():
        problems.append(f"fixture_dir '{fixture_dir}' is not a directory")

    # 6. Target file exists in fixture
    if fixture_dir.exists():
        target = fixture_dir / raw["target_relpath"]
        if not target.exists():
            problems.append(f"target_relpath '{raw['target_relpath']}' not found in {fixture_dir}")

    # 7. Run command is a list
    if not isinstance(raw["run_command"], list) or not raw["run_command"]:
        problems.append("run_command must be a non-empty list")

    # 8. Validate flags are recognized
    validate_flags = raw["validate"]
    if not isinstance(validate_flags, dict):
        problems.append("validate must be a dict")
    else:
        for key in validate_flags:
            if key not in VALID_VALIDATE_FLAGS:
                problems.append(f"Unknown validate flag: '{key}'. Valid: {VALID_VALIDATE_FLAGS}")

    # 9. max_lines_changed is positive int
    mlc = raw["max_lines_changed"]
    if not isinstance(mlc, int) or mlc <= 0:
        problems.append(f"max_lines_changed must be a positive integer, got {mlc}")

    # 10. allowed_files is a non-empty list
    af = raw["allowed_files"]
    if not isinstance(af, list) or not af:
        problems.append("allowed_files must be a non-empty list")

    # 11. Prompt template has required variables
    template = raw["prompt_template"]
    if "{file_content}" not in template:
        problems.append("prompt_template must contain {file_content}")
    if "{target_relpath}" not in template:
        problems.append("prompt_template must contain {target_relpath}")

    # 12. Fixture baseline actually runs (even if it fails — that's expected for bug-fix tasks)
    if fixture_dir.exists() and isinstance(raw["run_command"], list):
        try:
            p = subprocess.run(
                raw["run_command"], cwd=str(fixture_dir),
                capture_output=True, text=True, timeout=30,
            )
            # We don't check return code — the fixture is SUPPOSED to fail for bug-fix tasks.
            # We just check it doesn't hang or crash the interpreter.
        except subprocess.TimeoutExpired:
            problems.append(f"run_command timed out after 30s in {fixture_dir}")
        except FileNotFoundError as e:
            problems.append(f"run_command failed to start: {e}")

    # 13. File naming convention: task JSON filename matches task_id
    expected_filename = f"{task_id}.json"
    if path.name != expected_filename:
        problems.append(f"Filename '{path.name}' should be '{expected_filename}' to match task_id")

    return problems


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_task.py <task.json or tasks/>")
        return 2

    target = Path(sys.argv[1])
    if target.is_dir():
        files = sorted(target.glob("*.json"))
    else:
        files = [target]

    if not files:
        print(f"No JSON files found in {target}")
        return 2

    total_problems = 0
    for f in files:
        problems = validate_task(f)
        if problems:
            print(f"\nFAIL {f.name}")
            for p in problems:
                print(f"   {p}")
            total_problems += len(problems)
        else:
            print(f"OK   {f.name}")

    print(f"\n{len(files)} tasks checked, {total_problems} problems found.")
    return 1 if total_problems > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
