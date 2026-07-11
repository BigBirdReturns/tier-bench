#!/usr/bin/env python3
"""
Which tasks are valid for capability breadth-mapping — and which are answer-key theatre.

An agentic solver (haiku iterating, or any model that can run the tests) will read
whatever grader it can see and brute it. So a task only measures *capability* if the
deciding grader is HIDDEN from the solver. The rule, enforced here:

  breadth-valid  == ships a hidden grader the solver never sees. The solver may only
                    see a weak `visible_tests.py` / the spec; the hidden grader
                    produces the score. "The loop can only buy what visible selection
                    can see; the hidden set says whether that bought real quality."

  NOT breadth-valid == the grader is the file the solver edits/runs (the `tasks/*.json`
                    manifests: solver edits input.py, grader IS `python input.py`).
                    Fine for the router benchmark's one-shot grading; USELESS for
                    capability mapping, because an agentic solver reads the tests.

Today the hidden-grader (breadth-valid) set is small and real: task01, task02,
task06 in experiments/tier-uplift. That is the honest ruler. Grow it by AUTHORING
tasks with visible/hidden daylight — not by pointing the run at gameable ones.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPLIFT = REPO / "experiments" / "tier-uplift"

# Filenames that are a hidden grader (produce the score, never shown to the solver).
HIDDEN_GRADER_NAMES = ("hidden_tests.py", "hidden_oracle.py", "grader.py")


def hidden_grading_problems(manifest: str | Path, repo_root: Path = REPO) -> list[str]:
    """Return contract defects that prevent a manifest being called hidden-graded.

    Declarations are not evidence by themselves: the withheld files must be real,
    outside the solver-editable surface, and consumed by the deciding command.
    """
    import json

    path = Path(manifest)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest cannot be read: {exc}"]

    hidden_files = raw.get("hidden_files")
    hidden_command = raw.get("hidden_run_command")
    if not isinstance(hidden_files, list) or not hidden_files:
        return ["hidden_files must be a non-empty list"]
    if not isinstance(hidden_command, list) or not hidden_command:
        return ["hidden_run_command must be a non-empty list"]
    if not all(isinstance(value, str) and value for value in hidden_files):
        return ["every hidden_files entry must be a non-empty string"]
    if not all(isinstance(value, str) and value for value in hidden_command):
        return ["every hidden_run_command entry must be a non-empty string"]

    fixture = Path(raw.get("fixture_dir", ""))
    if not fixture.is_absolute():
        fixture = repo_root / fixture
    fixture = fixture.resolve()
    problems: list[str] = []
    normalized_hidden: set[str] = set()
    for value in hidden_files:
        hidden_path = (fixture / value).resolve()
        try:
            relative = hidden_path.relative_to(fixture).as_posix()
        except ValueError:
            problems.append(f"hidden file escapes fixture_dir: {value}")
            continue
        normalized_hidden.add(relative)
        if not hidden_path.is_file():
            problems.append(f"hidden file is not a regular file: {value}")

    target = Path(str(raw.get("target_relpath", ""))).as_posix().lstrip("./")
    editable = {Path(str(value)).as_posix().lstrip("./")
                for value in raw.get("allowed_files", []) if isinstance(value, str)}
    for relative in normalized_hidden:
        if relative == target or relative in editable:
            problems.append(f"hidden file is solver-editable: {relative}")

    command_paths = {Path(value).as_posix().lstrip("./") for value in hidden_command}
    if normalized_hidden and normalized_hidden.isdisjoint(command_paths):
        problems.append("hidden_run_command does not consume a declared hidden file")
    return problems


def breadth_valid_tasks(root: Path = UPLIFT) -> list[dict]:
    """Tier-uplift tasks that ship a hidden grader — the only ones valid for
    capability breadth-mapping."""
    out = []
    for d in sorted(root.glob("task*")):
        if not d.is_dir():
            continue
        hidden = [f.name for f in d.iterdir() if f.name in HIDDEN_GRADER_NAMES]
        if hidden:
            out.append({"task": d.name, "dir": str(d.relative_to(REPO)),
                        "hidden_grader": hidden[0]})
    return out


def is_gameable(manifest_or_dir: str | Path) -> bool:
    """True if the solver can see the deciding grader.

    tasks/*.json manifests are gameable UNLESS they declare hidden grading
    (`hidden_files` + `hidden_run_command`): the harness strips those files from
    the solver's working copy and prompt, and injects them only at grade time
    (harness/task_schema.py + harness/attempt.py). Manifests without those
    fields grade with the file the solver edits/runs — answer-key theatre."""
    p = Path(manifest_or_dir)
    if p.suffix == ".json":
        return bool(hidden_grading_problems(p))
    if p.is_dir():
        return not any((p / n).exists() for n in HIDDEN_GRADER_NAMES)
    return True


def breadth_valid_manifests(tasks_dir: Path = REPO / "tasks") -> list[dict]:
    """tasks/*.json manifests that declare hidden grading — breadth-valid via the
    harness's hidden_files mechanism."""
    out = []
    for mp in sorted(tasks_dir.glob("*.json")):
        if not is_gameable(mp):
            import json
            raw = json.loads(mp.read_text(encoding="utf-8"))
            out.append({"task": raw["task_id"], "manifest": str(mp.relative_to(REPO)),
                        "hidden_grader": raw["hidden_files"][0]})
    return out


if __name__ == "__main__":
    valid = breadth_valid_tasks()
    print(f"breadth-valid (hidden-grader) tasks: {len(valid)}")
    for t in valid:
        print(f"  {t['task']:24s} hidden grader: {t['hidden_grader']}  ({t['dir']})")
    hidden_manifests = breadth_valid_manifests()
    print(f"\nbreadth-valid tasks/*.json manifests (hidden_files grading): {len(hidden_manifests)}")
    for t in hidden_manifests:
        print(f"  {t['task']:28s} hidden grader: {t['hidden_grader']}  ({t['manifest']})")
    print("\nNOT breadth-valid (visible grader — an agentic solver reads the answer key):")
    print("  every tasks/*.json manifest WITHOUT hidden_files/hidden_run_command")
    print("  tier-uplift task03/04/05/07  (no hidden grader file)")
    print("\nMap on the valid set only. Grow it by authoring visible/hidden-daylight tasks.")
