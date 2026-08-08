#!/usr/bin/env python3
"""Optional Playwright integration from a real Task Computer run to Task Floor TF5."""
from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATALOG = ROOT / "experiments" / "task_computer" / "project_scenarios.json"
MANIFEST = ROOT / "experiments" / "task_floor" / "reference_manifest.json"


def test_optional_task_computer_run_exports_as_tf5_bundle() -> None:
    try:
        import playwright  # noqa: F401
        from tier_runner.playwright_computer_common import load_json
        from tier_runner.task_computer_lab import TaskComputerRunner, load_catalog
        from tier_runner.task_floor_conformance import assess_bundle
        from tier_runner.task_floor_export import build_bundle, verify_bundle, write_bundle_directory
    except ImportError:
        print("  skip  test_optional_task_computer_run_exports_as_tf5_bundle: Playwright unavailable")
        return

    parent = Path(tempfile.mkdtemp(prefix="task-floor-playwright-"))
    try:
        catalog = load_catalog(CATALOG)
        runner = TaskComputerRunner(
            catalog=catalog,
            scenario_id="tier-desk-approve-underdrain",
            variant="dynamic",
            out_root=parent / "runs",
            headless=True,
            trace=False,
            approval_enabled=True,
        )
        receipt = asyncio.run(runner.run())
        assert receipt["status"] == "ACCEPTED", receipt
        bundle = write_bundle_directory(
            parent / "bundle",
            build_bundle(runner.run_dir, load_json(MANIFEST)),
            a2a_endpoint="https://example.invalid/a2a",
            artifact_source_root=runner.run_dir,
        )
        assert verify_bundle(bundle, root=parent / "bundle") == []
        report = assess_bundle(bundle)
        assert report["highest_contiguous_profile"] == "TF5", report
        assert report["claims"]["overclaimed_profiles"] == []
        assert bundle["project_handoff"]["transition"] == "DRAFT->QUEUED"
        assert bundle["metrics"]["accepted_work_units"] == 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main() -> int:
    try:
        test_optional_task_computer_run_exports_as_tf5_bundle()
        print("  ok  test_optional_task_computer_run_exports_as_tf5_bundle")
        print("\n1/1 Task Floor integration tests passed")
        return 0
    except Exception as exc:
        print(
            "FAIL  test_optional_task_computer_run_exports_as_tf5_bundle: "
            f"{type(exc).__name__}: {exc}"
        )
        print("\n0/1 Task Floor integration tests passed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
