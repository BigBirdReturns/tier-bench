#!/usr/bin/env python3
"""Conservative OSS registry and ecosystem-gap tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REGISTRY = ROOT / "experiments" / "task_floor" / "oss_registry.json"
COMMITTED_REPORT = ROOT / "experiments" / "task_floor" / "gap_report.json"

from tier_runner.playwright_computer_common import PlaywrightComputerError, load_json  # noqa: E402
from tier_runner.task_floor_conformance import (  # noqa: E402
    GAP_DEFINITIONS,
    gap_report,
    validate_registry,
)


def test_registry_covers_representative_protocols_runtimes_and_assurance_tools() -> None:
    registry = validate_registry(load_json(REGISTRY))
    assert len(registry["entries"]) == 21
    assert len(registry["axes"]) == len(GAP_DEFINITIONS) == 26
    ids = {entry["id"] for entry in registry["entries"]}
    assert {
        "mcp",
        "a2a",
        "ag-ui",
        "opentelemetry-genai",
        "in-toto-slsa",
        "opa",
        "cedar",
        "spiffe-spire",
        "langgraph",
        "playwright-agents",
        "browser-use",
        "stagehand",
        "webwright",
        "cua",
        "browsergym",
        "agentrx",
        "agentdojo",
        "browser-harness",
        "bytebot",
        "magentic-ui",
        "fara",
    } == ids
    assert all(entry["sources"] for entry in registry["entries"])


def test_gap_report_proves_no_surveyed_system_is_the_complete_floor() -> None:
    report = gap_report(load_json(REGISTRY))
    assert report["entries"] == 21
    assert report["axes"] == 26
    assert set(report["critical_gaps"]) == {
        "approval_portability",
        "project_handoff",
        "retention_privacy",
        "rollback_compensation",
        "state_binding",
    }
    assert set(report["high_gaps"]) == {
        "accepted_work_economics",
        "authority_quorum",
        "counterfactual_replay",
        "idempotency_transactions",
        "skill_supply_chain",
    }
    assert max(row["score"] for row in report["system_scores"]) < report["axes"]
    assert "complete Task Floor contract" in report["conclusion"]



def test_committed_gap_report_is_a_deterministic_derivative() -> None:
    assert gap_report(load_json(REGISTRY)) == load_json(COMMITTED_REPORT)

def test_registry_hash_prevents_silent_coverage_rewrites() -> None:
    raw = load_json(REGISTRY)
    tampered = deepcopy(raw)
    tampered["entries"][0]["coverage"]["state_binding"] = "documented"
    try:
        validate_registry(tampered)
    except PlaywrightComputerError as exc:
        assert "registry_sha256" in str(exc)
    else:
        raise AssertionError("registry coverage rewrite must require resealing")


def main() -> int:
    tests = [
        test_registry_covers_representative_protocols_runtimes_and_assurance_tools,
        test_gap_report_proves_no_surveyed_system_is_the_complete_floor,
        test_committed_gap_report_is_a_deterministic_derivative,
        test_registry_hash_prevents_silent_coverage_rewrites,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} Task Floor registry tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
