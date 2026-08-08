#!/usr/bin/env python3
"""Live command-driver conformance tests for the Task Floor reference backend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRIVER = ROOT / "examples" / "task_floor" / "reference_driver.py"

from tier_runner.task_floor_driver import CommandDriver, run_driver_conformance  # noqa: E402


def _environment(state_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["TASK_FLOOR_DRIVER_ROOT"] = str(state_root)
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


def test_reference_driver_reaches_tf4_and_rejects_stale_effects() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-floor-driver-"))
    try:
        report = run_driver_conformance(
            CommandDriver(
                [sys.executable, str(DRIVER)],
                timeout_seconds=30,
                cwd=ROOT,
                environment=_environment(parent / "state"),
            )
        )
        assert report["passed"] is True, report
        assert report["highest_contiguous_profile"] == "TF4"
        assert all(report["profiles"][profile]["pass"] for profile in ("TF0", "TF1", "TF2", "TF3", "TF4"))
        assert report["profiles"]["TF5"]["pass"] is False
        checks = {row["id"]: row for row in report["checks"]}
        assert checks["state.stale_action_rejected"]["pass"] is True
        assert checks["effects.unapproved_external_write_rejected"]["pass"] is True
        assert checks["execution.idempotency"]["pass"] is True
        assert checks["acceptance.external_verifier"]["pass"] is True
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_public_cli_driver_command_does_not_shadow_subcommand() -> None:
    parent = Path(tempfile.mkdtemp(prefix="task-floor-driver-cli-"))
    try:
        out = parent / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tier_runner.task_floor_cli",
                "driver-test",
                "--command",
                f'"{sys.executable}" "{DRIVER}"',
                "--cwd",
                str(ROOT),
                "--out",
                str(out),
            ],
            cwd=ROOT,
            env=_environment(parent / "state"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["highest_contiguous_profile"] == "TF4"
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    tests = [
        test_reference_driver_reaches_tf4_and_rejects_stale_effects,
        test_public_cli_driver_command_does_not_shadow_subcommand,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Floor driver tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
