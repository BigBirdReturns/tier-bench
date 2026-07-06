"""Distill driver traces into an apprentice curriculum.

driver_repair composites (harness/composites.py) capture one JSONL line per
repair to --traces: (task, failed hands output, validator report, driver's
fix, passed?) -- exactly the tuple driver/README.md names as the unit of
imitation. This script does the "load this file as the system prompt, study
the traces" steps of that README's teach loop: it reads driver/README.md
verbatim as the role spec, keeps only the traces where the repair actually
passed (a curriculum is made of moves that WORKED -- a failed repair is kept
in the corpus for completeness but teaches the wrong lesson if shown as an
example), and formats them as few-shot exemplars an apprentice model can be
handed before it attempts to drive.

Two output modes:
  text (default) -- spec + exemplars as a single prompt block, ready to paste
                     as a system/context prime for an apprentice model.
  --json         -- {"spec": ..., "exemplars": [...]} structured the same
                     way, for a fine-tune or eval pipeline instead of a
                     human pasting text.

Nothing here calls a model or writes anything -- it only reads what
composites.py already captured. Distillation of judgment, not weights, per
driver/README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_SPEC_PATH = REPO_ROOT / "driver" / "README.md"

REQUIRED_KEYS = (
    "task_id", "tier", "hands_model", "hands_output",
    "validator_report", "driver_model", "driver_output", "passed",
)


def load_traces(path: Path) -> list[dict]:
    """Parse the JSONL trace file, skipping any line that isn't a well-formed
    trace rather than failing the whole run -- traces are appended by a
    long-running benchmark and a crash mid-write should not poison history."""
    traces: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if all(k in row for k in REQUIRED_KEYS):
            traces.append(row)
    return traces


def passed_only(traces: list[dict]) -> list[dict]:
    # A curriculum is made of moves that WORKED. Failed repairs stay in the
    # raw corpus (composites.py logs them on purpose -- "use all the
    # buffalo") but showing an apprentice a fix that didn't pass would teach
    # it the wrong lesson, so the filter lives here, at read time, not at
    # capture time.
    return [t for t in traces if t.get("passed") is True]


def format_exemplar(trace: dict, index: int) -> str:
    report = json.dumps(trace["validator_report"], ensure_ascii=False, indent=2, default=str)
    hands_output = trace["hands_output"] if trace["hands_output"] is not None else "(no usable output)"
    driver_output = trace["driver_output"] if trace["driver_output"] is not None else "(no output)"
    return (
        f"### Exemplar {index} -- {trace['task_id']} ({trace['tier']})\n\n"
        f"TASK: {trace['task_id']} (tier {trace['tier']}), attempted by "
        f"hands model `{trace['hands_model']}`.\n\n"
        "FAILED ATTEMPT:\n"
        f"{hands_output}\n\n"
        "VALIDATOR REPORT:\n"
        f"{report}\n\n"
        f"CORRECT REPAIR (by driver `{trace['driver_model']}`):\n"
        f"{driver_output}\n"
    )


def build_curriculum(traces_path: Path, limit: int) -> dict:
    spec = DRIVER_SPEC_PATH.read_text(encoding="utf-8")
    traces = passed_only(load_traces(traces_path))
    exemplars = [
        {
            "task_id": t["task_id"],
            "tier": t["tier"],
            "hands_model": t["hands_model"],
            "hands_output": t["hands_output"],
            "validator_report": t["validator_report"],
            "driver_model": t["driver_model"],
            "driver_output": t["driver_output"],
        }
        for t in traces[:limit]
    ]
    return {"spec": spec, "exemplars": exemplars, "total_passed_traces": len(traces)}


def render_text(curriculum: dict) -> str:
    parts = [curriculum["spec"].rstrip(), "\n\n---\n"]
    if not curriculum["exemplars"]:
        parts.append(
            "(No passed driver_repair traces yet -- spec only. Run a "
            "driver_repair benchmark to generate exemplars.)\n"
        )
    else:
        parts.append(
            f"## Worked examples ({len(curriculum['exemplars'])} of "
            f"{curriculum['total_passed_traces']} passed traces)\n\n"
        )
        for i, t in enumerate(curriculum["exemplars"], start=1):
            parts.append(format_exemplar(t, i))
    return "\n".join(parts)


EPILOG = """\
Graduation test (see driver/README.md):
  set the apprentice as the driver (--driver <apprentice> or roles.apprentice
  in models.json), run `python orchestrator.py --benchmark all`, then
  `python scripts/diff_report.py --target <apprentice>` -- when its
  cost-per-success on the driver role matches the frontier's, it has
  replicated the driver.
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    ap.add_argument("--traces", default="driver_traces.jsonl",
                     help="JSONL trace file written by driver_repair composites (default: driver_traces.jsonl)")
    ap.add_argument("--limit", type=int, default=5,
                     help="Max exemplars to include after the spec (default: 5)")
    ap.add_argument("--json", action="store_true", help="Emit {spec, exemplars} JSON instead of text")
    args = ap.parse_args()

    traces_path = Path(args.traces)
    if not traces_path.exists() or traces_path.stat().st_size == 0:
        print(
            f"No traces at {traces_path}. Run a driver_repair benchmark first "
            "to generate them, e.g.:\n"
            "  python orchestrator.py --benchmark all\n"
            "(driver_repair composites append to this file automatically; "
            "see harness/composites.py and models.json's composites section)."
        )
        return 2

    curriculum = build_curriculum(traces_path, max(args.limit, 0))
    if args.json:
        print(json.dumps(curriculum, indent=2, ensure_ascii=False, default=str))
    else:
        print(render_text(curriculum))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
