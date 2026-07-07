from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from cost_guard import COMPOSITES_RAW, Tier, model_available
from harness.attempt import run_attempt
from harness.task_schema import Task

# Composite candidates: compositions of registry models that get benchmarked
# as first-class rows, so "a cheap model plus a harness replicates the
# expensive model" is a measured claim, not an opinion. Defined declaratively
# in models.json under "composites" — strategies are data, not code, so the
# registry outlives any particular model generation.
#
# Strategies:
#   cascade       — try members in order; first output that passes validation
#                   wins. Cost is the sum of every attempt made.
#   best_of_n     — resample the single member up to n times; the task's own
#                   deterministic validators act as the selection verifier.
#                   Early-stops on the first pass (same outcome, less spend).
#   driver_repair — the driver/hands pattern: a cheap "hands" model attempts
#                   the task; on validation failure the "driver" model gets
#                   the failed output AND the validator report as evidence and
#                   produces the repair. The driver never does the bulk work —
#                   it spends only judgment tokens, and failures are reused
#                   instead of discarded.


@dataclass(frozen=True)
class CompositeDef:
    name: str
    strategy: str  # "cascade" | "best_of_n" | "driver_repair"
    members: list[str] = field(default_factory=list)
    driver: str | None = None
    n: int = 1
    max_repairs: int = 1
    tier_ceiling: str = "T0"


def load_composites() -> list[CompositeDef]:
    defs: list[CompositeDef] = []
    for name, info in COMPOSITES_RAW.items():
        if name.startswith("_"):
            continue  # comment keys
        defs.append(CompositeDef(
            name=name,
            strategy=str(info.get("strategy", "")),
            members=list(info.get("members", [])),
            driver=info.get("driver"),
            n=int(info.get("n", 1)),
            max_repairs=int(info.get("max_repairs", 1)),
            tier_ceiling=str(info.get("tier_ceiling", "T0")),
        ))
    return defs


def composites_for_tier(tier: Tier) -> list[CompositeDef]:
    out = []
    for comp in load_composites():
        try:
            ceiling = Tier[comp.tier_ceiling]
        except KeyError:
            ceiling = Tier.T0
        if tier.value <= ceiling.value:
            out.append(comp)
    return out


def composite_available(comp: CompositeDef) -> bool:
    """A composite is runnable only if every model it references is."""
    models = list(comp.members) + ([comp.driver] if comp.driver else [])
    return bool(models) and all(model_available(m) for m in models)


def _compact(row: dict) -> dict:
    """Per-attempt record kept inside the aggregate row. Compact on purpose —
    the full call trail already lives in llm_costs.jsonl."""
    out = {
        "model": row.get("model"),
        "pass": row.get("pass"),
        "actual_cost": row.get("actual_cost"),
    }
    if row.get("reason"):
        out["reason"] = row["reason"]
    return out


def _validator_report(failed_row: dict) -> dict:
    """The validator fields the driver reasons over, factored out so the
    repair prompt (_repair_suffix) and the training trace (_append_trace)
    draw from exactly the same evidence -- no drift between what the driver
    saw when it repaired and what gets distilled later."""
    report_keys = (
        "reason", "compile_ok", "ruff_imports_ok", "functional_equivalence",
        "tests_ok", "allowed_files_ok", "max_lines_ok", "canonical_match",
        "diff_lines", "notes",
    )
    return {k: failed_row[k] for k in report_keys if k in failed_row}


def _repair_suffix(failed_content: str | None, failed_row: dict) -> str:
    """Turn a failed attempt into repair evidence for the driver model."""
    report_json = json.dumps(_validator_report(failed_row), ensure_ascii=False, default=str)[:2000]

    if failed_content:
        evidence = (
            "A smaller model attempted this task and FAILED validation.\n"
            "Its full output was:\n"
            "----- FAILED ATTEMPT -----\n"
            f"{failed_content}\n"
            "----- END FAILED ATTEMPT -----\n"
        )
    else:
        evidence = "A smaller model attempted this task and produced no usable output.\n"

    return (
        f"{evidence}"
        f"Validator report (JSON): {report_json}\n\n"
        "Fix what the failed attempt got wrong. Return ONLY the corrected, "
        "complete content for the target file. No explanations. No markdown."
    )


def _append_trace(
    traces_path: str | None,
    task: Task,
    hands_model: str,
    hands_output: str | None,
    validator_report: dict,
    driver_model: str,
    driver_output: str | None,
    passed: bool,
) -> None:
    """Append ONE training example per repair attempt: (task, failed hands
    output, the report that graded it, the driver's fix, did it pass). This
    is the exact tuple driver/README.md names as the distillation unit --
    "(task, failed_hands_output, validator_report) -> (driver_repair,
    passed?)" -- so scripts/distill.py can turn it into a curriculum without
    re-deriving anything the driver already computed.

    We log every repair, passed or not -- "use all the buffalo": a failed
    repair is still evidence (of what the report alone does NOT fix), and
    throwing it away here would just mean re-running the benchmark later to
    get it back. distill.py is the one that filters to passed==true, because
    a few-shot curriculum should only show moves that worked -- but that's a
    read-time decision, not a write-time one, so the corpus stays complete.

    traces_path=None disables capture entirely (e.g. a caller that wants a
    dry run without touching disk); the default lands next to wherever the
    benchmark is invoked from, same as harness_results.jsonl.
    """
    if traces_path is None:
        return
    trace = {
        "task_id": task.task_id,
        "tier": task.tier,
        "hands_model": hands_model,
        "hands_output": hands_output,
        "validator_report": validator_report,
        "driver_model": driver_model,
        "driver_output": driver_output,
        "passed": bool(passed),
    }
    with open(traces_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(trace, ensure_ascii=False, default=str) + "\n")


def run_composite(
    task: Task,
    tier: Tier,
    comp: CompositeDef,
    traces_path: str | None = "driver_traces.jsonl",
) -> dict:
    """Run one composite candidate on one task; return ONE aggregate row.

    The row satisfies the same schema harness.metrics.compute() reads for
    plain models (model / tier / pass / actual_cost), so composites appear in
    the routing table and diff report with zero downstream changes.

    traces_path controls where driver_repair captures training traces (see
    _append_trace); pass None to skip writing. Other strategies ignore it --
    only driver_repair produces (failed attempt, report, fix) tuples worth
    distilling.
    """
    attempts: list[dict] = []

    if comp.strategy == "cascade":
        for member in comp.members:
            row, _ = run_attempt(task, tier, member)
            attempts.append(row)
            if row.get("pass"):
                break

    elif comp.strategy == "best_of_n":
        member = comp.members[0]
        for _ in range(max(comp.n, 1)):
            row, _ = run_attempt(task, tier, member)
            attempts.append(row)
            if row.get("pass"):
                break

    elif comp.strategy == "driver_repair":
        hands = comp.members[0]
        row, content = run_attempt(task, tier, hands)
        attempts.append(row)
        for _ in range(max(comp.max_repairs, 0)):
            if row.get("pass"):
                break
            failed_content, failed_row = content, row  # evidence, not garbage
            driver_model = comp.driver or hands
            suffix = _repair_suffix(failed_content, failed_row)
            row, content = run_attempt(task, tier, driver_model, prompt_suffix=suffix)
            attempts.append(row)
            _append_trace(
                traces_path, task, hands, failed_content,
                _validator_report(failed_row), driver_model, content, row.get("pass"),
            )

    else:
        return {
            "task_id": task.task_id,
            "tier": task.tier,
            "model": comp.name,
            "strategy": comp.strategy,
            "status": "error",
            "pass": False,
            "actual_cost": 0.0,
            "cost_missing": False,
            "reason": f"unknown_composite_strategy:{comp.strategy}",
            "attempts": [],
        }

    costs = [a["actual_cost"] for a in attempts if isinstance(a.get("actual_cost"), (int, float))]
    passed = any(a.get("pass") for a in attempts)

    # Capture the driver's DECISION (not its output) when policy capture is on, so
    # the frozen snapshot survives the driver disappearing. Guarded + swallowed:
    # a benchmark run must never fail because decision logging hiccuped.
    if comp.strategy == "driver_repair" and os.environ.get("TIER_BENCH_CAPTURE_POLICY"):
        try:
            from harness.driver_policy import capture_composite_decision
            capture_composite_decision(task, comp, passed)
        except Exception:
            pass

    return {
        "task_id": task.task_id,
        "tier": task.tier,
        "model": comp.name,
        "strategy": comp.strategy,
        "status": "ok" if attempts and attempts[-1].get("status") == "ok" else "error",
        # Honest pricing: a composite pays for EVERY attempt it made,
        # including the failures that preceded the pass.
        "actual_cost": round(sum(costs), 6),
        "cost_missing": len(costs) != len(attempts),
        "pass": bool(passed),
        "attempts": [_compact(a) for a in attempts],
    }
