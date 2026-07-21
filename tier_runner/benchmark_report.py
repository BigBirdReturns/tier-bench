from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any


SCHEMA = "tier-bench/local-benchmark-report@1"
REPORT_PATH = "data/desk-benchmark-report.json"


class ReportError(RuntimeError):
    pass


def requested_count(intent: str, default: int = 10) -> int:
    match = re.search(r"\b(?:run|measure)\s+(\d{1,2})\s+benchmarks?\b", intent, re.I)
    count = int(match.group(1)) if match else default
    if not 1 <= count <= 20:
        raise ReportError("benchmark count must be between 1 and 20")
    return count


def is_benchmark_intent(intent: str) -> bool:
    lowered = intent.lower()
    return "benchmark" in lowered and any(
        word in lowered for word in ("run", "measure", "cost", "compare")
    )


def _need_number(value: Any, label: str, *, integer: bool = False) -> None:
    kind = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ReportError(f"{label} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ReportError(f"{label} must be finite and non-negative")


def verify_report(path: Path, expected_count: int, expected_model: str) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read benchmark report: {exc}") from exc
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ReportError(f"benchmark report schema must be {SCHEMA}")
    if report.get("model") != expected_model:
        raise ReportError("benchmark report model does not match the frozen lane")
    if report.get("requested_count") != expected_count:
        raise ReportError("benchmark report count does not match the frozen request")
    suite_commit = report.get("suite_commit")
    if not isinstance(suite_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", suite_commit):
        raise ReportError("benchmark report has no full suite commit")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ReportError(f"benchmark report must contain exactly {expected_count} rows")
    task_ids: set[str] = set()
    total_cost = 0.0
    total_input = 0
    total_output = 0
    passes = 0
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ReportError(f"benchmark row {index} must be an object")
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise ReportError(f"benchmark row {index} has an invalid or duplicate task_id")
        task_ids.add(task_id)
        if row.get("model") != expected_model:
            raise ReportError(f"benchmark row {index} model drifted")
        if not isinstance(row.get("pass"), bool):
            raise ReportError(f"benchmark row {index} has no boolean verdict")
        _need_number(row.get("actual_cost"), f"row {index} actual_cost")
        _need_number(row.get("duration_seconds"), f"row {index} duration_seconds")
        _need_number(row.get("input_tokens"), f"row {index} input_tokens", integer=True)
        _need_number(row.get("output_tokens"), f"row {index} output_tokens", integer=True)
        total_cost += float(row["actual_cost"])
        total_input += int(row["input_tokens"])
        total_output += int(row["output_tokens"])
        passes += int(row["pass"])
    summary = report.get("summary")
    expected = {
        "attempts": expected_count,
        "passes": passes,
        "failures": expected_count - passes,
        "input_tokens": total_input,
        "output_tokens": total_output,
    }
    if not isinstance(summary, dict) or any(summary.get(k) != v for k, v in expected.items()):
        raise ReportError("benchmark report summary does not equal its rows")
    if abs(float(summary.get("cost_usd", -1)) - total_cost) > 1e-9:
        raise ReportError("benchmark report cost does not equal its rows")
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Verify a Tier Desk benchmark report")
    commands = result.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--path", type=Path, required=True)
    verify.add_argument("--expected-count", type=int, required=True)
    verify.add_argument("--expected-model", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "verify":
        verify_report(args.path, args.expected_count, args.expected_model)
        print(f"PASS - {args.expected_count} benchmark rows are complete and internally consistent")
        return 0
    raise ReportError(f"unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReportError, OSError, ValueError) as exc:
        print(f"tier benchmark report: {exc}")
        raise SystemExit(1)
