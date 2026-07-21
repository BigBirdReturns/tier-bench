from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.benchmark_report import (  # noqa: E402
    REPORT_PATH,
    ReportError,
    SCHEMA,
    is_benchmark_intent,
    requested_count,
    verify_report,
)


def main() -> int:
    assert is_benchmark_intent("run 10 benchmarks that teach us the costs")
    assert requested_count("run 10 benchmarks that teach us the costs") == 10
    assert REPORT_PATH == "data/desk-benchmark-report.json"
    rows = [
        {
            "task_id": f"task-{index}",
            "model": "qwen3.5:9b-q4_K_M",
            "pass": index % 2 == 0,
            "actual_cost": 0.0,
            "duration_seconds": 1.5,
            "input_tokens": 100,
            "output_tokens": 20,
        }
        for index in range(10)
    ]
    report = {
        "schema": SCHEMA,
        "suite_commit": "a" * 40,
        "model": "qwen3.5:9b-q4_K_M",
        "requested_count": 10,
        "rows": rows,
        "summary": {
            "attempts": 10,
            "passes": 5,
            "failures": 5,
            "input_tokens": 1000,
            "output_tokens": 200,
            "cost_usd": 0.0,
        },
    }
    with tempfile.TemporaryDirectory(prefix="tier-benchmark-report-") as raw:
        path = Path(raw) / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        assert verify_report(path, 10, "qwen3.5:9b-q4_K_M") == report
        report["summary"]["passes"] = 6
        path.write_text(json.dumps(report), encoding="utf-8")
        try:
            verify_report(path, 10, "qwen3.5:9b-q4_K_M")
        except ReportError as exc:
            assert "summary" in str(exc)
        else:
            raise AssertionError("inconsistent benchmark summary must fail")
    print("PASS - benchmark intents and reports are bounded and independently checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
