#!/usr/bin/env python3
"""Session-burn ledger + functional-quota estimator.

The project measures model cost per task; this measures the *meta-resource* — how
much of a Claude Code session's own quota is available before it exhausts. You log
one append-only row per session (when it ends, and why); this computes the
functional quota with the same discipline the rest of the repo uses: measured vs
estimated, single-source vs corroborated, and NEVER a guessed ceiling.

The key idea: a session that ends with `end_reason=quota_exhausted` is the only
kind that MEASURES the ceiling — its `budget_consumed` is one observation of the
functional quota. A session that `completed` only gives a LOWER BOUND (you had at
least that much). So the honest functional-quota readout is the distribution of
exhaustion points, with the minimum as the conservative floor.

Units never mix: a report is for exactly one `budget_metric`. Asking across mixed
units fails closed rather than adding tokens to dollars.

    python session_burn.py log --session S1 --model claude-fable-5 \
        --started 2026-07-11T00:00:00Z --end-reason quota_exhausted \
        --metric subagent_trials --consumed 33 --evidence estimated --note "..."
    python session_burn.py report --metric subagent_trials
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

DEFAULT_LEDGER = Path(__file__).resolve().parent / "run" / "session_burn.jsonl"

END_REASONS = {"completed", "quota_exhausted", "aborted_other", "unknown"}
BUDGET_METRICS = {"output_tokens", "usd", "turns", "subagent_trials", "wall_minutes"}
EVIDENCE_CLASSES = {"measured", "estimated"}
REQUIRED = ("session_id", "model", "started", "end_reason", "budget_metric",
            "budget_consumed", "evidence_class")


def validate_row(row: dict) -> list[str]:
    """Fail-closed row validation. Empty list == valid."""
    errs: list[str] = []
    for key in REQUIRED:
        if key not in row:
            errs.append(f"missing required field {key!r}")
    if row.get("end_reason") not in END_REASONS:
        errs.append(f"end_reason must be one of {sorted(END_REASONS)}")
    if row.get("budget_metric") not in BUDGET_METRICS:
        errs.append(f"budget_metric must be one of {sorted(BUDGET_METRICS)}")
    if row.get("evidence_class") not in EVIDENCE_CLASSES:
        errs.append(f"evidence_class must be one of {sorted(EVIDENCE_CLASSES)}")
    bc = row.get("budget_consumed")
    if not isinstance(bc, (int, float)) or isinstance(bc, bool) or bc < 0:
        errs.append("budget_consumed must be a non-negative number")
    for key in ("session_id", "model", "started"):
        if not (isinstance(row.get(key), str) and row[key].strip()):
            errs.append(f"{key} must be a non-empty string")
    return errs


def log_session(path: str | Path, **fields) -> dict:
    row = dict(fields)
    errs = validate_row(row)
    if errs:
        raise ValueError("invalid session-burn row: " + "; ".join(errs))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def functional_quota(rows: list[dict], metric: str) -> dict:
    """Compute the functional quota for ONE metric. Fails closed on unit mixing.

    Only `quota_exhausted` sessions measure the ceiling; `completed` sessions give
    lower bounds. The conservative functional quota is the minimum exhaustion
    point; median is the typical.
    """
    if metric not in BUDGET_METRICS:
        return {"metric": metric, "state": "INVALID_METRIC",
                "note": f"metric must be one of {sorted(BUDGET_METRICS)}"}
    same = [r for r in rows if r.get("budget_metric") == metric]
    exhausted = [r for r in same if r.get("end_reason") == "quota_exhausted"
                 and isinstance(r.get("budget_consumed"), (int, float))
                 and not isinstance(r.get("budget_consumed"), bool)]
    completed = [r for r in same if r.get("end_reason") == "completed"
                 and isinstance(r.get("budget_consumed"), (int, float))
                 and not isinstance(r.get("budget_consumed"), bool)]
    if not exhausted:
        return {"metric": metric, "state": "UNMEASURED",
                "note": "no quota_exhausted sessions for this metric — the ceiling "
                        "is not yet observed; completed sessions only bound it below",
                "lower_bound_from_completed": max((r["budget_consumed"] for r in completed), default=None),
                "completed_n": len(completed)}
    values = [r["budget_consumed"] for r in exhausted]
    n = len(exhausted)
    all_estimated = all(r.get("evidence_class") == "estimated" for r in exhausted)
    return {
        "metric": metric,
        "state": "measured",
        "exhaustion_observations": n,
        "conservative_functional_quota": min(values),   # you can reliably reach this
        "median_exhaustion": statistics.median(values),
        "max_observed": max(values),
        "evidence_class": "estimated" if all_estimated else "mixed/measured",
        "corroboration": "single-source" if n < 2 else "corroborated",
        "lower_bound_from_completed": max((r["budget_consumed"] for r in completed), default=None),
        "note": "conservative_functional_quota is the MINIMUM observed exhaustion "
                "point — the amount you can reliably spend before the wall. Not a "
                "true ceiling; more exhausted sessions tighten it.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log", help="append one session-burn row")
    lg.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    lg.add_argument("--session", dest="session_id", required=True)
    lg.add_argument("--model", required=True)
    lg.add_argument("--started", required=True)
    lg.add_argument("--ended", default="")
    lg.add_argument("--end-reason", dest="end_reason", required=True, choices=sorted(END_REASONS))
    lg.add_argument("--metric", dest="budget_metric", required=True, choices=sorted(BUDGET_METRICS))
    lg.add_argument("--consumed", dest="budget_consumed", type=float, required=True)
    lg.add_argument("--evidence", dest="evidence_class", required=True, choices=sorted(EVIDENCE_CLASSES))
    lg.add_argument("--note", default="")
    rp = sub.add_parser("report", help="functional quota for one metric")
    rp.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    rp.add_argument("--metric", help="one budget metric; omit to list metrics present")
    a = ap.parse_args()

    if a.cmd == "log":
        fields = {k: getattr(a, k) for k in
                  ("session_id", "model", "started", "ended", "end_reason",
                   "budget_metric", "budget_consumed", "evidence_class", "note")}
        row = log_session(a.ledger, **{k: v for k, v in fields.items() if v != ""})
        print(json.dumps(row))
        return 0

    rows = load(a.ledger)
    if not a.metric:
        metrics = sorted({r.get("budget_metric") for r in rows if r.get("budget_metric")})
        print(json.dumps({"metrics_present": metrics,
                          "note": "units never mix — run report with exactly one --metric"}, indent=2))
        return 0
    print(json.dumps(functional_quota(rows, a.metric), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
