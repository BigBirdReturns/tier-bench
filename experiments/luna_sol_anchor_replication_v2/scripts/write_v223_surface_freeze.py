#!/usr/bin/env python3
"""Write the reproducible v2.2.3 app-inherited Spark command freeze."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run_v2.py"
PROPOSAL = ROOT / "SPARK_EXECUTION_INTERFACE_V2_2_3_DECISION_PROPOSAL.md"
PROBE = ROOT / "SPARK_FREEFORM_EXECUTION_PROBE_20260716.md"
spec = importlib.util.spec_from_file_location("luna_run_v223_surface_freeze", RUNNER)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def build() -> dict[str, object]:
    command = runner.spark_execution_command(Path("<SUBJECT>"), Path("<FINAL_RESPONSE>"))
    runner.require_spark_execution_surface(command)
    return {
        "schema": "luna-sol-anchor-replication/spark-execution-surface-freeze@2.2.3",
        "protocol_revision": "2.2.3",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cli_identity": runner.require_cli_identity(),
        "model": "gpt-5.3-codex-spark",
        "reasoning_effort": "low",
        "surface": "app_inherited",
        "sandbox": "workspace-write",
        "free_form": True,
        "output_schema": None,
        "command_template": command,
        "required_absent_arguments": ["--ignore-user-config", "--ignore-rules", "--output-schema"],
        "planner_invocation": "structured_and_schema_bound_unchanged",
        "admission_authority": "controller_observed_diff_and_controller_rerun_validator",
        "spark_final_prose_used_for_admission": False,
        "benchmark_execution_authorized": False,
        "hashes": {
            "runner_sha256": runner.sha(RUNNER),
            "proposal_sha256": runner.sha(PROPOSAL),
            "freeform_probe_report_sha256": runner.sha(PROBE),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    value = build()
    runner.write(args.output.resolve(), runner.canon(value))
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
