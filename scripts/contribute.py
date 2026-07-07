"""
Package and validate community benchmark contributions.

Tier Bench is only as good as the pool it draws from. Nobody's rig can run
every model at every tier, so the pool has to come from many machines. This
script is the one door in: it turns a raw `harness_results.jsonl` into a
packaged, provenance-stamped file under data/results/, and it is also the
mechanical gate CI runs against every packaged file in a PR (--validate).

HONESTY DOCTRINE: every row here is self-reported. This script does not (and
cannot) verify a contributor actually ran the harness honestly — it only
verifies the row is *structurally* trustworthy: real task, correct tier,
sane cost. Evidence class (single-source vs corroborated) is computed later,
by scripts/aggregate.py, from how many distinct contributors report a cell.

Usage:
    python scripts/contribute.py --results harness_results.jsonl --as yourhandle
    python scripts/contribute.py --validate data/results/2026-07-07-yourhandle-a1b2c3d4.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VALID_TIERS = {"T0", "T1", "T2", "T3", "T4", "T5"}

# A single task row costing more than this is either a broken cost calculation
# or an attempt to poison pooled cost averages -- not a legitimate benchmark run.
MAX_ROW_COST = 10.0

# Sloppy data poisons pools: if more than this share of a submitted file's rows
# are invalid, reject the whole file rather than average in the good rows.
MAX_INVALID_FRACTION = 0.20


def _load_task_tiers(tasks_dir: Path) -> dict[str, str]:
    """task_id -> tier, loaded once from tasks/*.json manifests. This is what
    stops a contributed row from claiming a task id that doesn't exist, or
    labeling a real task with the wrong tier to fish for an easier bucket."""
    tiers: dict[str, str] = {}
    for f in sorted(tasks_dir.glob("*.json")):
        try:
            manifest = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        tid = manifest.get("task_id")
        tier = manifest.get("tier")
        if isinstance(tid, str) and isinstance(tier, str):
            tiers[tid] = tier
    return tiers


def _load_registry_models(repo_root: Path) -> set[str]:
    """Model names known to models.json. Unknown models only warn -- new
    models are exactly the fresh data this pool wants, and the registry entry
    can ride the same PR as the data instead of gating it."""
    models_path = repo_root / "models.json"
    if not models_path.exists():
        return set()
    raw = json.loads(models_path.read_text(encoding="utf-8"))
    return set(raw.get("models", {}).keys())


def validate_rows(
    rows: list[dict],
    task_tiers: dict[str, str] | None = None,
    known_models: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Check every row against the contribution rules. Returns (errors, warnings).
    Rows are checked independently so a single bad row's error message points at
    it precisely -- the caller decides whether the file as a whole survives."""
    repo_root = Path(__file__).resolve().parent.parent
    if task_tiers is None:
        task_tiers = _load_task_tiers(repo_root / "tasks")
    if known_models is None:
        known_models = _load_registry_models(repo_root)

    errors: list[str] = []
    warnings: list[str] = []

    for i, row in enumerate(rows):
        prefix = f"row {i}"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: not a JSON object")
            continue

        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            errors.append(f"{prefix}: task_id missing or not a string")
            task_id = None

        tier = row.get("tier")
        if tier not in VALID_TIERS:
            errors.append(f"{prefix} ({task_id}): tier {tier!r} not in {sorted(VALID_TIERS)}")

        model = row.get("model")
        if not isinstance(model, str) or not model:
            errors.append(f"{prefix} ({task_id}): model missing or not a string")
            model = None

        if not isinstance(row.get("pass"), bool):
            errors.append(f"{prefix} ({task_id}): pass must be a bool")

        cost = row.get("actual_cost")
        if row.get("cost_missing") is True:
            pass  # explicitly declared missing -- not a fabricated free run
        elif not isinstance(cost, (int, float)) or isinstance(cost, bool):
            errors.append(f"{prefix} ({task_id}): actual_cost missing/not numeric (set cost_missing:true if unknown)")
        elif cost < 0:
            errors.append(f"{prefix} ({task_id}): actual_cost {cost} is negative")
        elif cost > MAX_ROW_COST:
            errors.append(f"{prefix} ({task_id}): actual_cost {cost} exceeds sanity ceiling ${MAX_ROW_COST}")

        if task_id is not None:
            expected_tier = task_tiers.get(task_id)
            if expected_tier is None:
                errors.append(f"{prefix}: task_id {task_id!r} not found in tasks/*.json manifests")
            elif tier in VALID_TIERS and tier != expected_tier:
                errors.append(
                    f"{prefix}: task_id {task_id!r} is tier {expected_tier} in the manifest, row claims {tier}"
                )

        if model is not None and known_models and model not in known_models:
            tag = "composite/strategy name" if ":" in model else "not in models.json registry"
            warnings.append(f"{prefix} ({task_id}): model {model!r} {tag} -- new data is welcome, add a registry entry when convenient")

    return errors, warnings


def _row_hash(row: dict) -> str:
    """Deterministic hash of row content -- same content from two contributors
    still gets distinct filenames because the filename also carries the handle,
    but this keeps a single contributor's re-packaging of identical data from
    silently overwriting a differently-named file by accident."""
    blob = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:8]


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def cmd_package(args: argparse.Namespace) -> int:
    results_path = Path(args.results)
    if not results_path.exists():
        print(f"No results at {results_path}")
        return 1

    try:
        raw_rows = _read_jsonl(results_path)
    except json.JSONDecodeError as e:
        print(f"Invalid JSONL in {results_path}: {e}")
        return 1

    errors, warnings = validate_rows(raw_rows)

    # Map each error back to a row index so we can drop only the bad rows,
    # not the whole file -- as long as the invalid fraction stays under the cap.
    bad_indices: set[int] = set()
    for e in errors:
        # errors are formatted "row N ..." or "row N (task) ..."
        try:
            idx = int(e.split()[1].rstrip(":").split("(")[0])
        except (IndexError, ValueError):
            continue
        bad_indices.add(idx)

    total = len(raw_rows)
    if total == 0:
        print("No rows in results file.")
        return 1

    invalid_fraction = len(bad_indices) / total
    if invalid_fraction > MAX_INVALID_FRACTION:
        print(f"Rejected: {len(bad_indices)}/{total} rows invalid ({invalid_fraction:.0%}), "
              f"exceeds the {MAX_INVALID_FRACTION:.0%} sloppiness ceiling.")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    valid_rows = [row for i, row in enumerate(raw_rows) if i not in bad_indices]
    if not valid_rows:
        print("Rejected: zero valid rows.")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    if errors:
        print(f"Dropping {len(bad_indices)}/{total} invalid rows (kept {len(valid_rows)}):")
        for e in errors:
            print(f"  ERROR: {e}")
    for w in warnings:
        print(f"  WARNING: {w}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Hash over the packaged (post-drop) row content -- the file's identity is
    # what actually ships, not the raw input the contributor happened to have.
    combined_hash = hashlib.sha256(
        json.dumps(valid_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    out_path = out_dir / f"{date}-{args.as_handle}-{combined_hash}.jsonl"

    meta = {"_meta": {"schema": 1, "contributor": args.as_handle, "submitted": date, "rows": len(valid_rows)}}
    with out_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(meta) + "\n")
        for row in valid_rows:
            f.write(json.dumps(row) + "\n")

    print(f"\nWrote {out_path} ({len(valid_rows)} rows)")
    print("Next: open a PR adding this file to data/results/ -- CI validates it mechanically,")
    print("merging republishes the pooled site automatically. Do not hand-edit the file.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.validate)
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except UnicodeDecodeError as e:
        print(f"Cannot read {path}: {e}")
        return 1

    if not lines:
        print(f"{path}: empty file")
        return 1

    errors: list[str] = []

    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as e:
        print(f"{path}: first line is not valid JSON ({e})")
        return 1

    meta = first.get("_meta") if isinstance(first, dict) else None
    if not isinstance(meta, dict):
        errors.append("first line missing _meta object")
        meta = {}
    if meta.get("schema") != 1:
        errors.append(f"_meta.schema is {meta.get('schema')!r}, expected 1")
    if not isinstance(meta.get("contributor"), str) or not meta.get("contributor"):
        errors.append("_meta.contributor missing or empty")
    declared_rows = meta.get("rows")

    row_lines = lines[1:]
    if not isinstance(declared_rows, int) or declared_rows != len(row_lines):
        errors.append(f"_meta.rows says {declared_rows!r} but file has {len(row_lines)} data row(s)")

    rows: list[dict] = []
    for i, line in enumerate(row_lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"data row {i}: invalid JSON ({e})")

    if not rows and not row_lines:
        errors.append("file has no data rows")

    row_errors, row_warnings = validate_rows(rows)
    errors.extend(row_errors)

    total = len(rows) if rows else 1
    if len(row_errors) / total > MAX_INVALID_FRACTION:
        errors.append(
            f"{len(row_errors)}/{len(rows)} rows invalid, exceeds {MAX_INVALID_FRACTION:.0%} sloppiness ceiling"
        )

    for w in row_warnings:
        print(f"WARNING: {w}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1

    print(f"{path}: OK ({len(rows)} rows, contributor={meta.get('contributor')!r})")
    return 0


def cmd_emit_meta(args: argparse.Namespace) -> int:
    """Emit the validation contract the browser needs to check a contribution
    BEFORE it is submitted: the task_id -> tier map and the known-model list,
    drawn from the SAME loaders the CLI/CI validator uses. The static site
    can't read tasks/*.json itself, so the Pages build calls this to bake the
    map next to index.html. One source of truth: if a new task lands, the map
    the page validates against updates on the next deploy -- no drift between
    what the page promises and what CI enforces."""
    repo_root = Path(__file__).resolve().parent.parent
    meta = {
        "task_tiers": _load_task_tiers(repo_root / "tasks"),
        "models": sorted(_load_registry_models(repo_root)),
        "max_row_cost": MAX_ROW_COST,
        "max_invalid_fraction": MAX_INVALID_FRACTION,
        "valid_tiers": sorted(VALID_TIERS),
    }
    out = Path(args.emit_meta)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(meta['task_tiers'])} tasks, {len(meta['models'])} models)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", help="Raw harness_results.jsonl to package")
    ap.add_argument("--as", dest="as_handle", help="Your contributor handle")
    ap.add_argument("--out", default="data/results", help="Output directory for packaged mode")
    ap.add_argument("--validate", help="Path to a packaged data/results/*.jsonl file to re-validate")
    ap.add_argument("--emit-meta", help="Write the browser validation contract (task_tiers + models) to this path")
    args = ap.parse_args()

    if args.emit_meta:
        return cmd_emit_meta(args)

    if args.validate:
        return cmd_validate(args)

    if args.results:
        if not args.as_handle:
            print("Package mode requires --as yourhandle")
            return 2
        return cmd_package(args)

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
