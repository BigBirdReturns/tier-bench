#!/usr/bin/env python3
"""Validate the frontier capture ledger (data/capture/*.jsonl).

The capture ledger is the economic proof object: it records whether expensive
frontier cognition was converted into reusable machinery. Because "amortized" is
a closure claim, this validator enforces burden discipline
(docs/burden-discipline.md) in code, not just structure:

  Structure (mirrors schemas/capture_ledger.schema.json + delta_observation.schema.json)
  - every row is typed: record_type in {capture, delta_observation}
  - capture rows carry all required fields incl. the full burden packet
  - cost_basis is one of the four evidence classes (real-billed, shadow-estimated,
    subscription-derived, repaired-transport-adjudicated)

  Closure rules (the part a schema can't express)
  - the captured artifact PATH MUST EXIST in the repo — no vaporware captures
  - status 'amortized' and burden.closure_decision 'closed' REQUIRE
    validated_replays > 0 with non-empty replay_evidence; with zero replays the
    only legal states are the non-closed ones (failure default, never silence)
  - break_even_reuse_count must be null until validated replays exist —
    projections live in capture_roi.py output, never in the ledger as fact
  - a waterline_effect claim requires source_task_id to resolve in
    waterline.json (link check only; this ledger NEVER writes the waterline)
  - delta rows: capturable=true requires captured_as

Independent of the community results pipeline by design: capture rows have
their own door and never flow through contribute.py.

    python scripts/validate_capture_ledger.py            # validate data/capture/*.jsonl
    python scripts/validate_capture_ledger.py <file...>  # validate specific files
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAPTURE_DIR = REPO / "data/capture"
WATERLINE = REPO / "experiments/breadth/run/waterline.json"

COST_BASES = {"real-billed", "shadow-estimated", "subscription-derived",
              "repaired-transport-adjudicated"}
STATUSES = {"captured_not_yet_amortized", "needs_replay", "partial", "amortized"}
CLOSED_STATUSES = {"amortized"}
CLOSURE_DECISIONS = {"open", "needs_replay", "partial", "closed"}
DELTA_TYPES = {"edge_delta", "framing_delta", "routing_delta", "spec_delta", "transport_delta"}

CAPTURE_REQUIRED = ("capture_id", "source_task_id", "driver_model", "driver_role",
                    "capture_cost_usd", "cost_basis", "captured_artifact", "old_path",
                    "new_path", "break_even_reuse_count", "validated_replays", "status", "burden")
BURDEN_REQUIRED = ("requested_outcome", "claimant", "authority", "predicates", "burden_holder",
                   "evidence", "verifier", "gap", "closure_decision", "failure_default")
DELTA_REQUIRED = ("from_model", "to_model", "task_id", "delta_types",
                  "what_lower_missed", "what_higher_added", "capturable")
PATH_REQUIRED = ("model", "status", "success")


def _nonempty(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def waterline_task_ids(path: Path = WATERLINE) -> set[str]:
    try:
        w = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return set()
    return set(w.get("settled_floor", {})) | set(w.get("judgment_residue", {}))


def validate_capture(row: dict, waterline_ids: set[str], repo: Path = REPO) -> list[str]:
    errs: list[str] = []
    cid = row.get("capture_id", "<no id>")
    for key in CAPTURE_REQUIRED:
        if key not in row:
            errs.append(f"capture {cid}: missing required field '{key}'")
    if row.get("cost_basis") is not None and row["cost_basis"] not in COST_BASES:
        errs.append(f"capture {cid}: invalid cost_basis '{row['cost_basis']}' (allowed: {sorted(COST_BASES)})")
    if not isinstance(row.get("capture_cost_usd"), (int, float)) or isinstance(row.get("capture_cost_usd"), bool) or (isinstance(row.get("capture_cost_usd"), (int, float)) and row["capture_cost_usd"] < 0):
        errs.append(f"capture {cid}: capture_cost_usd must be a non-negative number")
    status = row.get("status")
    if status is not None and status not in STATUSES:
        errs.append(f"capture {cid}: invalid status '{status}' (allowed: {sorted(STATUSES)})")

    art = row.get("captured_artifact")
    if not isinstance(art, dict):
        errs.append(f"capture {cid}: captured_artifact must be an object")
    else:
        for key in ("type", "path", "description"):
            if not _nonempty(art.get(key)):
                errs.append(f"capture {cid}: captured_artifact.{key} must be a non-empty string")
        p = art.get("path")
        if _nonempty(p) and not (repo / p).exists():
            errs.append(f"capture {cid}: captured_artifact.path '{p}' does not exist — "
                        f"a capture without its artifact is a claim, not a capture")

    for leg in ("old_path", "new_path"):
        obj = row.get(leg)
        if not isinstance(obj, dict):
            errs.append(f"capture {cid}: {leg} must be an object")
            continue
        for key in PATH_REQUIRED:
            if not _nonempty(obj.get(key)):
                errs.append(f"capture {cid}: {leg}.{key} must be a non-empty string")
        cb = obj.get("cost_basis")
        if cb is not None and cb not in COST_BASES:
            errs.append(f"capture {cid}: {leg}.cost_basis '{cb}' invalid")
        cost = obj.get("cost_usd_per_trial")
        if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0):
            errs.append(f"capture {cid}: {leg}.cost_usd_per_trial must be a non-negative number")

    replays = row.get("validated_replays")
    if not isinstance(replays, int) or isinstance(replays, bool) or replays < 0:
        errs.append(f"capture {cid}: validated_replays must be a non-negative integer")
        replays = 0
    evidence = row.get("replay_evidence") or []
    if replays > 0 and not evidence:
        errs.append(f"capture {cid}: validated_replays={replays} with empty replay_evidence — "
                    f"a count without rows is a fabricated receipt")

    # Closure discipline: zero replays can never close.
    if replays == 0:
        if status in CLOSED_STATUSES:
            errs.append(f"capture {cid}: status '{status}' with zero validated replays — "
                        f"missing replay evidence defaults to needs_replay/partial, never amortized")
        if row.get("break_even_reuse_count") is not None:
            errs.append(f"capture {cid}: break_even_reuse_count must be null until validated "
                        f"replays exist — projections belong to capture_roi.py output, not the ledger")

    burden = row.get("burden")
    if not isinstance(burden, dict):
        errs.append(f"capture {cid}: burden packet missing — closure claims require one (burden-discipline)")
    else:
        for key in BURDEN_REQUIRED:
            v = burden.get(key)
            if key in ("predicates", "evidence"):
                if not isinstance(v, list) or not v or not all(_nonempty(x) for x in v):
                    errs.append(f"capture {cid}: burden.{key} must be a non-empty list of strings")
            elif not _nonempty(v):
                errs.append(f"capture {cid}: burden.{key} must be a non-empty string")
        cd = burden.get("closure_decision")
        if cd is not None and cd not in CLOSURE_DECISIONS:
            errs.append(f"capture {cid}: burden.closure_decision '{cd}' invalid (allowed: {sorted(CLOSURE_DECISIONS)})")
        if cd == "closed" and replays == 0:
            errs.append(f"capture {cid}: burden.closure_decision 'closed' with zero validated replays")

    # Waterline link check — read-only referential integrity, never a write.
    if _nonempty(row.get("waterline_effect")) and waterline_ids:
        tid = row.get("source_task_id")
        if tid not in waterline_ids:
            errs.append(f"capture {cid}: waterline_effect claimed but source_task_id '{tid}' "
                        f"resolves to no waterline cell")
    return errs


def validate_delta(row: dict) -> list[str]:
    errs: list[str] = []
    tid = row.get("task_id", "<no task>")
    for key in DELTA_REQUIRED:
        if key not in row:
            errs.append(f"delta({tid}): missing required field '{key}'")
    dts = row.get("delta_types")
    if not isinstance(dts, list) or not dts:
        errs.append(f"delta({tid}): delta_types must be a non-empty list")
    else:
        for dt in dts:
            if dt not in DELTA_TYPES:
                errs.append(f"delta({tid}): invalid delta_type '{dt}' (allowed: {sorted(DELTA_TYPES)})")
    for key in ("from_model", "to_model", "what_lower_missed", "what_higher_added"):
        if key in row and not _nonempty(row[key]):
            errs.append(f"delta({tid}): '{key}' must be a non-empty string")
    if row.get("capturable") is True and not _nonempty(row.get("captured_as")):
        errs.append(f"delta({tid}): capturable=true requires a non-empty captured_as")
    if not isinstance(row.get("capturable"), bool):
        errs.append(f"delta({tid}): capturable must be a boolean")
    return errs


def validate_file(path: Path, waterline_ids: set[str]) -> tuple[list[str], int, int]:
    """Returns (errors, n_captures, n_deltas)."""
    errs: list[str] = []
    n_cap = n_delta = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            errs.append(f"{path.name}:{i}: not valid JSON ({e})")
            continue
        rt = row.get("record_type")
        if rt == "capture":
            n_cap += 1
            errs.extend(validate_capture(row, waterline_ids))
        elif rt == "delta_observation":
            n_delta += 1
            errs.extend(validate_delta(row))
        else:
            errs.append(f"{path.name}:{i}: unknown record_type '{rt}' "
                        f"(allowed: capture, delta_observation)")
    return errs, n_cap, n_delta


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]] or sorted(CAPTURE_DIR.glob("*.jsonl"))
    if not files:
        print(f"FAIL — no capture files found under {CAPTURE_DIR}", file=sys.stderr)
        return 1
    wl = waterline_task_ids()
    all_errs: list[str] = []
    total_cap = total_delta = 0
    for f in files:
        errs, n_cap, n_delta = validate_file(f, wl)
        all_errs.extend(errs)
        total_cap += n_cap
        total_delta += n_delta
    if all_errs:
        print(f"FAIL — {len(all_errs)} problem(s) in the capture ledger:\n", file=sys.stderr)
        for e in all_errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK — {total_cap} capture(s), {total_delta} delta observation(s) across "
          f"{len(files)} file(s); artifacts exist, closure discipline holds "
          f"(no amortization without validated replays).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
