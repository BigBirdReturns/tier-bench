"""Machine-readable gap ledger for the public Interaction Floor.

A gap is not closed by prose.  Each row names the actors, the missing mechanism,
the artifact that would close it, and the executable or inspectable condition
that distinguishes closure from intention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import load_json, stable_id, write_json
from .errors import FloorGapError

GAP_FORMAT = "axm-interaction-gap-ledger/1"
STATUSES = frozenset({"closed", "in-progress", "open", "deferred", "reference"})
SEVERITIES = frozenset({"critical", "high", "medium", "low"})


@dataclass(frozen=True)
class FloorGap:
    gap_id: str
    category: str
    title: str
    status: str
    severity: str
    actors: tuple[str, ...]
    mechanism: str
    failure_mode: str
    closure_artifact: str
    closure_test: str
    owner: str
    dependencies: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class FloorGapLedger:
    ledger_id: str
    reviewed_as_of: str
    gaps: tuple[FloorGap, ...]
    raw: dict[str, Any]
    source_path: Path


def _require_string(raw: Mapping[str, Any], key: str, *, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FloorGapError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _require_list(
    raw: Mapping[str, Any], key: str, *, where: str, allow_empty: bool = False
) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        raise FloorGapError(f"{where}.{key} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise FloorGapError(f"{where}.{key}[{index}] must be a non-empty string")
        result.append(item.strip())
    if len(result) != len(set(result)):
        raise FloorGapError(f"{where}.{key} contains duplicates")
    return tuple(result)


def gap_identity_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in raw if key != "ledger_id"}


def derived_gap_ledger_id(raw: Mapping[str, Any]) -> str:
    return stable_id("floorgaps1", gap_identity_projection(raw), length=32)


def _assert_acyclic(gaps: Mapping[str, FloorGap]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(gap_id: str) -> None:
        if gap_id in visited:
            return
        if gap_id in visiting:
            raise FloorGapError(f"gap dependency cycle contains {gap_id}")
        visiting.add(gap_id)
        for dependency in gaps[gap_id].dependencies:
            walk(dependency)
        visiting.remove(gap_id)
        visited.add(gap_id)

    for gap_id in gaps:
        walk(gap_id)


def load_gap_ledger(path: Path) -> FloorGapLedger:
    try:
        raw = load_json(path)
    except (OSError, ValueError) as exc:
        raise FloorGapError(f"cannot load gap ledger {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FloorGapError("gap ledger root must be an object")
    if raw.get("format") != GAP_FORMAT:
        raise FloorGapError(f"gap ledger format must be {GAP_FORMAT!r}")
    ledger_id = _require_string(raw, "ledger_id", where="ledger")
    expected = derived_gap_ledger_id(raw)
    if ledger_id != expected:
        raise FloorGapError(
            f"ledger_id mismatch: declared {ledger_id!r}, expected {expected!r}"
        )
    reviewed_as_of = _require_string(raw, "reviewed_as_of", where="ledger")
    rows = raw.get("gaps")
    if not isinstance(rows, list) or not rows:
        raise FloorGapError("ledger.gaps must be a non-empty array")
    seen: set[str] = set()
    gaps: list[FloorGap] = []
    for index, row in enumerate(rows):
        where = f"ledger.gaps[{index}]"
        if not isinstance(row, dict):
            raise FloorGapError(f"{where} must be an object")
        gap_id = _require_string(row, "id", where=where)
        if gap_id in seen:
            raise FloorGapError(f"duplicate gap id: {gap_id}")
        seen.add(gap_id)
        status = _require_string(row, "status", where=where)
        severity = _require_string(row, "severity", where=where)
        if status not in STATUSES:
            raise FloorGapError(f"{where}.status must be one of {sorted(STATUSES)}")
        if severity not in SEVERITIES:
            raise FloorGapError(f"{where}.severity must be one of {sorted(SEVERITIES)}")
        gaps.append(
            FloorGap(
                gap_id=gap_id,
                category=_require_string(row, "category", where=where),
                title=_require_string(row, "title", where=where),
                status=status,
                severity=severity,
                actors=_require_list(row, "actors", where=where),
                mechanism=_require_string(row, "mechanism", where=where),
                failure_mode=_require_string(row, "failure_mode", where=where),
                closure_artifact=_require_string(row, "closure_artifact", where=where),
                closure_test=_require_string(row, "closure_test", where=where),
                owner=_require_string(row, "owner", where=where),
                dependencies=_require_list(row, "dependencies", where=where, allow_empty=True),
                evidence=_require_list(row, "evidence", where=where, allow_empty=True),
            )
        )
    by_id = {gap.gap_id: gap for gap in gaps}
    for gap in gaps:
        unknown = set(gap.dependencies) - set(by_id)
        if unknown:
            raise FloorGapError(f"gap {gap.gap_id} has unknown dependencies: {sorted(unknown)}")
        if gap.status == "closed":
            open_dependencies = [
                dependency
                for dependency in gap.dependencies
                if by_id[dependency].status not in {"closed", "reference"}
            ]
            if open_dependencies:
                raise FloorGapError(
                    f"closed gap {gap.gap_id} depends on open gaps {open_dependencies}"
                )
    _assert_acyclic(by_id)
    return FloorGapLedger(
        ledger_id=ledger_id,
        reviewed_as_of=reviewed_as_of,
        gaps=tuple(gaps),
        raw=raw,
        source_path=path.resolve(),
    )


def _topological(gaps: Iterable[FloorGap]) -> tuple[FloorGap, ...]:
    by_id = {gap.gap_id: gap for gap in gaps}
    visited: set[str] = set()
    result: list[FloorGap] = []

    def visit(gap: FloorGap) -> None:
        if gap.gap_id in visited:
            return
        for dependency in gap.dependencies:
            visit(by_id[dependency])
        visited.add(gap.gap_id)
        result.append(gap)

    for gap in sorted(by_id.values(), key=lambda item: item.gap_id):
        visit(gap)
    return tuple(result)


def build_gap_report(ledger: FloorGapLedger) -> dict[str, Any]:
    counts_by_status = {status: 0 for status in sorted(STATUSES)}
    counts_by_severity = {severity: 0 for severity in sorted(SEVERITIES)}
    counts_by_category: dict[str, int] = {}
    for gap in ledger.gaps:
        counts_by_status[gap.status] += 1
        counts_by_severity[gap.severity] += 1
        counts_by_category[gap.category] = counts_by_category.get(gap.category, 0) + 1
    sequence = [
        gap
        for gap in _topological(ledger.gaps)
        if gap.status in {"open", "in-progress"}
    ]
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    queue = sorted(
        sequence,
        key=lambda gap: (
            severity_order[gap.severity],
            0 if gap.status == "in-progress" else 1,
            gap.category,
            gap.gap_id,
        ),
    )
    return {
        "format": "axm-interaction-gap-report/1",
        "ledger_id": ledger.ledger_id,
        "reviewed_as_of": ledger.reviewed_as_of,
        "gap_count": len(ledger.gaps),
        "counts_by_status": counts_by_status,
        "counts_by_severity": counts_by_severity,
        "counts_by_category": dict(sorted(counts_by_category.items())),
        "closure_queue": [
            {
                "id": gap.gap_id,
                "title": gap.title,
                "category": gap.category,
                "status": gap.status,
                "severity": gap.severity,
                "owner": gap.owner,
                "dependencies": list(gap.dependencies),
                "closure_artifact": gap.closure_artifact,
                "closure_test": gap.closure_test,
            }
            for gap in queue
        ],
        "control_question": (
            "Can an external implementation prove compatibility, portability, safety limits, "
            "and substitution without importing AXM authority or relying on the reference runtime?"
        ),
    }


def render_gap_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Interaction Floor gap ledger",
        "",
        f"Ledger: `{report['ledger_id']}`",
        f"Reviewed as of: `{report['reviewed_as_of']}`",
        f"Tracked gaps: **{report['gap_count']}**",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in report["counts_by_status"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Closure queue",
            "",
            "| Severity | Status | Gap | Owner | Closure test |",
            "|---|---|---|---|---|",
        ]
    )
    for gap in report["closure_queue"]:
        lines.append(
            f"| {gap['severity']} | {gap['status']} | `{gap['id']}` {gap['title']} | "
            f"{gap['owner']} | {gap['closure_test'].replace('|', '\\|')} |"
        )
    lines.extend(["", "## Control question", "", report["control_question"], ""])
    return "\n".join(lines)


def write_gap_report(path: Path, report: Mapping[str, Any], *, markdown: bool) -> None:
    if markdown:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_gap_report_markdown(report), encoding="utf-8", newline="\n")
    else:
        write_json(path, dict(report))
