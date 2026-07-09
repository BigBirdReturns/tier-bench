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
    import json
    p = Path(manifest_or_dir)
    if p.suffix == ".json":
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return not (raw.get("hidden_files") and raw.get("hidden_run_command"))
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
