"""World Experience Atlas for the sovereign desktop estate.

The atlas imports mature mechanisms from adjacent engineering disciplines as
explicit, falsifiable build candidates. It is a planning instrument only: an
entry is not treated as implemented or beneficial until its own experiment
clears.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any

SCHEMA = "tier-bench/world-experience-atlas@1"
PLAN_SCHEMA = "tier-bench/world-experience-plan@1"
STATUSES = {"ready", "next", "needs-adapter", "research", "hold"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AtlasError(ValueError):
    """The atlas or a generated plan violated its contract."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AtlasError(f"cannot read {path}: {exc}") from exc


def write_json(path: Path | None, value: Any) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AtlasError(f"{label} must be an object")
    return value


def _array(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise AtlasError(f"{label} must be an array{suffix}")
    return value


def _text(value: Any, label: str, *, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AtlasError(f"{label} must be a non-empty string of at most {limit} characters")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label, limit=120)
    if not SAFE_ID.fullmatch(text):
        raise AtlasError(f"{label} contains unsafe characters")
    return text


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AtlasError(f"{label} must be an integer between {low} and {high}")
    return value


def _unique_ids(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        if identifier in result:
            raise AtlasError(f"duplicate {label} id: {identifier}")
        result[identifier] = row
    return result


def _cycle(patterns: dict[str, dict[str, Any]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def walk(identifier: str) -> list[str] | None:
        if identifier in visited:
            return None
        if identifier in visiting:
            start = path.index(identifier)
            return path[start:] + [identifier]
        visiting.add(identifier)
        path.append(identifier)
        for dependency in patterns[identifier]["depends_on"]:
            found = walk(dependency)
            if found:
                return found
        path.pop()
        visiting.remove(identifier)
        visited.add(identifier)
        return None

    for identifier in sorted(patterns):
        found = walk(identifier)
        if found:
            return found
    return None


def validate_atlas(raw: Any) -> dict[str, Any]:
    atlas = _object(raw, "atlas")
    if atlas.get("schema") != SCHEMA:
        raise AtlasError(f"atlas.schema must be {SCHEMA}")
    _identifier(atlas.get("id"), "atlas.id")
    _text(atlas.get("title"), "atlas.title", limit=240)
    _text(atlas.get("objective"), "atlas.objective")
    laws = [_text(item, f"atlas.laws[{index}]") for index, item in enumerate(
        _array(atlas.get("laws"), "atlas.laws", nonempty=True)
    )]
    if len(set(laws)) != len(laws):
        raise AtlasError("atlas.laws must be unique")

    current = _object(atlas.get("current_estate"), "atlas.current_estate")
    for key in ("implemented", "missing_cross_cutting_layers"):
        values = [_text(item, f"atlas.current_estate.{key}") for item in _array(
            current.get(key), f"atlas.current_estate.{key}", nonempty=True
        )]
        if len(set(values)) != len(values):
            raise AtlasError(f"atlas.current_estate.{key} must be unique")

    references: list[dict[str, Any]] = []
    for index, item in enumerate(_array(atlas.get("references"), "atlas.references", nonempty=True)):
        row = _object(item, f"atlas.references[{index}]")
        references.append({
            "id": _identifier(row.get("id"), f"reference {index}.id"),
            "title": _text(row.get("title"), f"reference {index}.title", limit=240),
            "url": _text(row.get("url"), f"reference {index}.url", limit=1000),
            "supports": [
                _text(value, f"reference {index}.supports")
                for value in _array(row.get("supports"), f"reference {index}.supports", nonempty=True)
            ],
        })
    references_by_id = _unique_ids(references, "reference")

    disciplines: list[dict[str, Any]] = []
    for index, item in enumerate(_array(atlas.get("disciplines"), "atlas.disciplines", nonempty=True)):
        row = _object(item, f"atlas.disciplines[{index}]")
        disciplines.append({
            "id": _identifier(row.get("id"), f"discipline {index}.id"),
            "title": _text(row.get("title"), f"discipline {index}.title", limit=240),
        })
    disciplines_by_id = _unique_ids(disciplines, "discipline")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(_array(atlas.get("patterns"), "atlas.patterns", nonempty=True)):
        row = _object(item, f"atlas.patterns[{index}]")
        identifier = _identifier(row.get("id"), f"pattern {index}.id")
        discipline = _identifier(row.get("discipline"), f"pattern {identifier}.discipline")
        if discipline not in disciplines_by_id:
            raise AtlasError(f"pattern {identifier} names unknown discipline {discipline}")
        status = _text(row.get("status"), f"pattern {identifier}.status", limit=40)
        if status not in STATUSES:
            raise AtlasError(f"pattern {identifier}.status must be one of {sorted(STATUSES)}")
        scores = _object(row.get("scores"), f"pattern {identifier}.scores")
        normalized_scores = {
            key: _integer(scores.get(key), f"pattern {identifier}.scores.{key}", 1, 5)
            for key in (
                "attention_return",
                "reuse_radius",
                "implementation_cost",
                "operational_risk",
            )
        }
        refs = [
            _identifier(value, f"pattern {identifier}.references")
            for value in _array(row.get("references"), f"pattern {identifier}.references", nonempty=True)
        ]
        unknown_refs = sorted(set(refs) - set(references_by_id))
        if unknown_refs:
            raise AtlasError(f"pattern {identifier} names unknown references {unknown_refs}")
        deps = [
            _identifier(value, f"pattern {identifier}.depends_on")
            for value in _array(row.get("depends_on", []), f"pattern {identifier}.depends_on")
        ]
        if identifier in deps:
            raise AtlasError(f"pattern {identifier} cannot depend on itself")
        normalized.append({
            "id": identifier,
            "title": _text(row.get("title"), f"pattern {identifier}.title", limit=240),
            "discipline": discipline,
            "priority": _integer(row.get("priority"), f"pattern {identifier}.priority", 0, 100),
            "status": status,
            "scores": normalized_scores,
            "mechanism": _text(row.get("mechanism"), f"pattern {identifier}.mechanism"),
            "current_gap": _text(row.get("current_gap"), f"pattern {identifier}.current_gap"),
            "desktop_translation": _text(
                row.get("desktop_translation"), f"pattern {identifier}.desktop_translation"
            ),
            "testable_hypothesis": _text(
                row.get("testable_hypothesis"), f"pattern {identifier}.testable_hypothesis"
            ),
            "first_experiment": _text(
                row.get("first_experiment"), f"pattern {identifier}.first_experiment"
            ),
            "references": refs,
            "depends_on": deps,
            "failure_default": _text(
                row.get("failure_default"), f"pattern {identifier}.failure_default"
            ),
        })
    patterns_by_id = _unique_ids(normalized, "pattern")
    for identifier, row in patterns_by_id.items():
        missing = sorted(set(row["depends_on"]) - set(patterns_by_id))
        if missing:
            raise AtlasError(f"pattern {identifier} has missing dependencies {missing}")
    cycle = _cycle(patterns_by_id)
    if cycle:
        raise AtlasError("pattern dependency cycle: " + " -> ".join(cycle))

    return {
        "schema": SCHEMA,
        "id": atlas["id"],
        "title": atlas["title"],
        "objective": atlas["objective"],
        "laws": laws,
        "current_estate": current,
        "references": references,
        "disciplines": disciplines,
        "patterns": normalized,
    }


def pattern_score(row: dict[str, Any]) -> int:
    scores = row["scores"]
    status_bias = {
        "ready": 20,
        "next": 10,
        "needs-adapter": 0,
        "research": -8,
        "hold": -100,
    }[row["status"]]
    return (
        row["priority"]
        + 8 * scores["attention_return"]
        + 5 * scores["reuse_radius"]
        - 4 * scores["implementation_cost"]
        - 3 * scores["operational_risk"]
        + status_bias
    )


def _selected_patterns(
    atlas: dict[str, Any],
    statuses: set[str],
    disciplines: set[str] | None,
    limit: int | None,
) -> dict[str, dict[str, Any]]:
    all_rows = {row["id"]: row for row in atlas["patterns"]}
    seeds = [
        row
        for row in atlas["patterns"]
        if row["status"] in statuses
        and (disciplines is None or row["discipline"] in disciplines)
    ]
    seeds.sort(key=lambda row: (-pattern_score(row), -row["priority"], row["id"]))
    if limit is not None:
        seeds = seeds[:limit]
    selected: dict[str, dict[str, Any]] = {}

    def admit(identifier: str) -> None:
        if identifier in selected:
            return
        row = all_rows[identifier]
        for dependency in row["depends_on"]:
            admit(dependency)
        selected[identifier] = row

    for row in seeds:
        admit(row["id"])
    return selected


def compile_plan(
    raw: Any,
    *,
    statuses: set[str] | None = None,
    disciplines: set[str] | None = None,
    limit: int | None = 12,
) -> dict[str, Any]:
    atlas = validate_atlas(raw)
    chosen_statuses = statuses or {"ready", "next"}
    invalid_statuses = chosen_statuses - STATUSES
    if invalid_statuses:
        raise AtlasError(f"unknown statuses: {sorted(invalid_statuses)}")
    known_disciplines = {row["id"] for row in atlas["disciplines"]}
    if disciplines is not None:
        unknown = disciplines - known_disciplines
        if unknown:
            raise AtlasError(f"unknown disciplines: {sorted(unknown)}")
    if limit is not None and (isinstance(limit, bool) or limit < 1 or limit > 1000):
        raise AtlasError("limit must be between 1 and 1000")

    selected = _selected_patterns(atlas, chosen_statuses, disciplines, limit)
    indegree = {identifier: 0 for identifier in selected}
    children: dict[str, list[str]] = defaultdict(list)
    for identifier, row in selected.items():
        for dependency in row["depends_on"]:
            if dependency in selected:
                indegree[identifier] += 1
                children[dependency].append(identifier)
    ready = [
        selected[identifier]
        for identifier, degree in indegree.items()
        if degree == 0
    ]
    waves: list[dict[str, Any]] = []
    scheduled: list[str] = []
    while ready:
        ready.sort(key=lambda row: (-pattern_score(row), -row["priority"], row["id"]))
        wave_rows = ready
        ready = []
        wave = {
            "index": len(waves),
            "patterns": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "discipline": row["discipline"],
                    "status": row["status"],
                    "score": pattern_score(row),
                    "depends_on": row["depends_on"],
                    "first_experiment": row["first_experiment"],
                    "testable_hypothesis": row["testable_hypothesis"],
                }
                for row in wave_rows
            ],
        }
        waves.append(wave)
        for row in wave_rows:
            scheduled.append(row["id"])
            for child in sorted(children.get(row["id"], [])):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(selected[child])
    if len(scheduled) != len(selected):
        raise AtlasError("selected dependency graph did not fully schedule")

    discipline_counts = defaultdict(int)
    for row in selected.values():
        discipline_counts[row["discipline"]] += 1
    top = sorted(selected.values(), key=lambda row: (-pattern_score(row), row["id"]))
    return {
        "schema": PLAN_SCHEMA,
        "atlas_id": atlas["id"],
        "selection": {
            "statuses": sorted(chosen_statuses),
            "disciplines": sorted(disciplines) if disciplines else None,
            "seed_limit": limit,
            "dependency_closure": True,
        },
        "totals": {
            "patterns": len(selected),
            "waves": len(waves),
            "disciplines": len(discipline_counts),
        },
        "discipline_counts": dict(sorted(discipline_counts.items())),
        "top_candidates": [
            {
                "id": row["id"],
                "title": row["title"],
                "score": pattern_score(row),
                "status": row["status"],
                "discipline": row["discipline"],
            }
            for row in top[:10]
        ],
        "waves": waves,
        "authority": {
            "meaning": "planning only",
            "implementation_claim": "none",
            "benefit_claim": "none",
            "promotion": "requires the entry's first experiment and estate acceptance authority",
        },
    }


def verify_plan(raw: Any, plan: Any) -> list[str]:
    errors: list[str] = []
    try:
        plan_obj = _object(plan, "plan")
        if plan_obj.get("schema") != PLAN_SCHEMA:
            return [f"plan.schema must be {PLAN_SCHEMA}"]
        selection = _object(plan_obj.get("selection"), "plan.selection")
        statuses = set(_array(selection.get("statuses"), "plan.selection.statuses", nonempty=True))
        disciplines_value = selection.get("disciplines")
        disciplines = (
            set(_array(disciplines_value, "plan.selection.disciplines"))
            if disciplines_value is not None
            else None
        )
        limit = selection.get("seed_limit")
        expected = compile_plan(
            raw,
            statuses=statuses,
            disciplines=disciplines,
            limit=limit,
        )
        if plan_obj != expected:
            errors.append("plan does not match deterministic recompilation")
    except AtlasError as exc:
        errors.append(str(exc))
    return errors


def catalog(
    raw: Any,
    *,
    discipline: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    atlas = validate_atlas(raw)
    if discipline is not None and discipline not in {row["id"] for row in atlas["disciplines"]}:
        raise AtlasError(f"unknown discipline: {discipline}")
    if status is not None and status not in STATUSES:
        raise AtlasError(f"unknown status: {status}")
    rows = [
        row for row in atlas["patterns"]
        if (discipline is None or row["discipline"] == discipline)
        and (status is None or row["status"] == status)
    ]
    rows.sort(key=lambda row: (-pattern_score(row), row["id"]))
    return {
        "schema": SCHEMA,
        "atlas_id": atlas["id"],
        "filters": {"discipline": discipline, "status": status},
        "count": len(rows),
        "patterns": [
            {
                "id": row["id"],
                "title": row["title"],
                "discipline": row["discipline"],
                "status": row["status"],
                "score": pattern_score(row),
                "current_gap": row["current_gap"],
                "desktop_translation": row["desktop_translation"],
                "first_experiment": row["first_experiment"],
                "depends_on": row["depends_on"],
            }
            for row in rows
        ],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="tieratlas",
        description="Validate and plan the World Experience Atlas",
    )
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--atlas", type=Path, required=True)

    show = commands.add_parser("catalog")
    show.add_argument("--atlas", type=Path, required=True)
    show.add_argument("--discipline")
    show.add_argument("--status")

    plan = commands.add_parser("plan")
    plan.add_argument("--atlas", type=Path, required=True)
    plan.add_argument("--status", action="append", dest="statuses")
    plan.add_argument("--discipline", action="append", dest="disciplines")
    plan.add_argument("--limit", type=int, default=12)
    plan.add_argument("--out", type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--atlas", type=Path, required=True)
    verify.add_argument("--plan", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        raw = load_json(args.atlas)
        if args.command == "validate":
            atlas = validate_atlas(raw)
            print(json.dumps({
                "ok": True,
                "atlas_id": atlas["id"],
                "references": len(atlas["references"]),
                "disciplines": len(atlas["disciplines"]),
                "patterns": len(atlas["patterns"]),
            }, indent=2, sort_keys=True))
            return 0
        if args.command == "catalog":
            write_json(None, catalog(raw, discipline=args.discipline, status=args.status))
            return 0
        if args.command == "plan":
            statuses = set(args.statuses) if args.statuses else None
            disciplines = set(args.disciplines) if args.disciplines else None
            write_json(
                args.out,
                compile_plan(
                    raw,
                    statuses=statuses,
                    disciplines=disciplines,
                    limit=args.limit,
                ),
            )
            return 0
        if args.command == "verify":
            errors = verify_plan(raw, load_json(args.plan))
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
            return int(bool(errors))
    except (AtlasError, OSError, ValueError) as exc:
        print(f"tieratlas: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
