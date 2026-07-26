#!/usr/bin/env python3
"""Zero-model-call tests for Model Waterline Observatory."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.model_waterline import (  # noqa: E402
    CATALOG_SCHEMA,
    PROTOCOL_SCHEMA,
    TASKS_SCHEMA,
    WaterlineError,
    analyze,
    compile_campaigns,
    validate_catalog,
    validate_protocol,
    validate_task_catalog,
)


def protocol() -> dict:
    base_price = {
        "input_per_million": 5.0,
        "output_per_million": 25.0,
        "cache_read_per_million": 0.5,
        "basis": "test",
    }
    return {
        "schema": PROTOCOL_SCHEMA,
        "id": "test-waterline-v1",
        "title": "Test model waterline",
        "subject_model": "subject",
        "reference_model": "reference",
        "settlement": {
            "cell_k": 1,
            "family_min_distinct_tasks": 2,
            "family_claim": "proposal_only",
            "cost_policy": "official_token_price",
            "attention_policy": "required",
            "audit_policy": "required",
            "runtime_attestation_required": True,
            "max_trials_per_route": 3,
        },
        "routes": [
            {
                "id": "subject-native",
                "label": "Subject native",
                "provider": "test",
                "role": "candidate",
                "lane": "native",
                "status": "ready",
                "model_id": "subject",
                "effort": "high",
                "manifest": "waterlines/subject.json",
                "arm": "arm_b",
                "execution_class": "remote_closed",
                "source_access": "api_only",
                "capability_basis": "unmeasured",
                "resource_key": "api:test",
                "max_concurrency": 1,
                "price": base_price,
            },
            {
                "id": "subject-augmented",
                "label": "Subject augmented",
                "provider": "test",
                "role": "candidate",
                "lane": "augmented",
                "status": "ready",
                "augmentation_id": "lens-v1",
                "model_id": "subject",
                "effort": "high",
                "manifest": "waterlines/subject-augmented.json",
                "arm": "arm_b",
                "execution_class": "remote_closed",
                "source_access": "api_only",
                "capability_basis": "unmeasured",
                "resource_key": "api:test",
                "max_concurrency": 1,
                "price": base_price,
            },
            {
                "id": "reference",
                "label": "Reference",
                "provider": "test",
                "role": "reference",
                "lane": "native",
                "status": "ready",
                "model_id": "reference",
                "effort": "max",
                "manifest": "waterlines/reference.json",
                "arm": "arm_b",
                "execution_class": "remote_closed",
                "source_access": "api_only",
                "capability_basis": "unmeasured",
                "resource_key": "api:test",
                "max_concurrency": 1,
                "price": {
                    "input_per_million": 10.0,
                    "output_per_million": 50.0,
                    "cache_read_per_million": 1.0,
                    "basis": "test",
                },
            },
        ],
    }


def task_catalog() -> dict:
    return {
        "schema": TASKS_SCHEMA,
        "id": "test-tasks-v1",
        "tasks": [
            {
                "id": "task-one",
                "title": "Task one",
                "kind": "task_manifest",
                "manifest": "tasks/task-one.json",
                "family": "test-family",
                "status": "ready",
            }
        ],
    }


def git_repo(parent: Path) -> Path:
    repo = parent / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "waterline@example.invalid"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Waterline Test"], cwd=repo, check=True
    )
    (repo / "tasks").mkdir()
    (repo / "fixtures" / "task-one").mkdir(parents=True)
    (repo / "fixtures" / "task-one" / "input.py").write_text(
        '"""Implement value()."""\n\ndef value():\n    return 0\n', encoding="utf-8"
    )
    (repo / "fixtures" / "task-one" / "hidden.py").write_text(
        "from input import value\nassert value() == 1\n", encoding="utf-8"
    )
    manifest = {
        "task_id": "task-one",
        "fixture_dir": "fixtures/task-one",
        "target_relpath": "input.py",
        "hidden_files": ["hidden.py"],
        "hidden_run_command": ["python", "hidden.py"],
    }
    (repo / "tasks" / "task-one.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("subject.json", "subject-augmented.json", "reference.json"):
        path = repo / "waterlines" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
    return repo


def trial(route_id: str, model: str, outcome: str, number: int = 1) -> dict:
    return {
        "id": f"{route_id}-{number}",
        "task_id": f"trial-{route_id}-{number}",
        "outcome": outcome,
        "result": {
            "task_id": f"trial-{route_id}-{number}",
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_read_tokens": 0,
            "cost_usd": 0,
            "runtime_attestation": {
                "model": model,
                "effort": "high",
                "extra": {
                    "runtime_model_id": model,
                    "telemetry_complete": True,
                    "cost_basis": "subscription-derived",
                },
            },
        },
    }


def campaign(task_id: str, subject: str, augmented: str, reference: str) -> dict:
    return {
        "schema": "tier-bench/frontier-residue-campaign@1",
        "id": f"campaign-{task_id}",
        "_waterline": {"task_id": task_id, "family": "test-family"},
        "routes": [
            {
                "route_id": "subject-native",
                "binding": {"model_id": "subject", "effort": "high"},
                "trials": [trial("subject-native", "subject", subject)],
            },
            {
                "route_id": "subject-augmented",
                "binding": {"model_id": "subject", "effort": "high"},
                "trials": [trial("subject-augmented", "subject", augmented)],
            },
            {
                "route_id": "reference",
                "binding": {"model_id": "reference", "effort": "max"},
                "trials": [trial("reference", "reference", reference)],
            },
        ],
        "waterline_audits": {
            "subject-native": {"state": "sealed", "critical_escaped_defects": 0},
            "subject-augmented": {"state": "sealed", "critical_escaped_defects": 0},
            "reference": {"state": "sealed", "critical_escaped_defects": 0},
        },
    }


def interventions_for(campaigns: list[dict]) -> list[dict]:
    events = []
    start = datetime(2026, 7, 26, tzinfo=timezone.utc)
    for camp in campaigns:
        for route in camp["routes"]:
            task_id = route["trials"][0]["task_id"]
            intervention_id = f"i-{task_id}"
            a = start.isoformat().replace("+00:00", "Z")
            b = (start + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            events.extend(
                [
                    {
                        "task_id": task_id,
                        "intervention_id": intervention_id,
                        "event": "start",
                        "category": "review",
                        "ts": a,
                    },
                    {
                        "task_id": task_id,
                        "intervention_id": intervention_id,
                        "event": "stop",
                        "category": "review",
                        "ts": b,
                    },
                ]
            )
            start += timedelta(minutes=2)
    return events


def test_protocol_rejects_missing_attestation_rule() -> None:
    value = protocol()
    value["settlement"]["runtime_attestation_required"] = False
    try:
        validate_protocol(value)
    except WaterlineError as exc:
        assert "runtime_attestation_required" in str(exc)
    else:
        raise AssertionError("missing runtime attestation must fail")


def test_compile_materializes_hidden_task_and_campaign(parent: Path) -> None:
    repo = git_repo(parent)
    compiled = compile_campaigns(protocol(), task_catalog(), repo)
    assert len(compiled["campaigns"]) == 1
    item = compiled["campaigns"][0]
    assert item["mode"] == "survey"
    assert item["task"]["files"] == ["fixtures/task-one/input.py"]
    assert "fixtures/task-one/hidden.py" in item["task"]["acceptance"]
    assert len(item["routes"]) == 3
    assert item["_waterline"]["target_head"] == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_compile_refuses_uncommitted_manifest(parent: Path) -> None:
    repo = git_repo(parent)
    (repo / "waterlines" / "subject.json").write_text('{"changed":true}\n', encoding="utf-8")
    # Existing committed object still exists at HEAD, so an uncommitted working-tree
    # change must not perturb the binding.
    compiled = compile_campaigns(protocol(), task_catalog(), repo)
    assert compiled["campaigns"]
    (repo / "waterlines" / "reference.json").unlink()
    subprocess.run(["git", "rm", "-q", "waterlines/reference.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove reference"], cwd=repo, check=True)
    try:
        compile_campaigns(protocol(), task_catalog(), repo)
    except WaterlineError as exc:
        assert "not committed" in str(exc)
    else:
        raise AssertionError("missing committed manifest must fail")


def test_native_replication_requires_attention_and_audit_for_full_waterline() -> None:
    campaigns = [
        campaign("one", "pass", "fail", "pass"),
        campaign("two", "pass", "fail", "pass"),
    ]
    no_attention = analyze(protocol(), campaigns)
    assert no_attention["capability_status"] == "PROPOSED_NATIVE_WATERLINE"
    assert no_attention["waterline_status"] == "PARTIAL"
    assert "attention_unmeasured" in no_attention["blocked_reasons"]

    report = analyze(protocol(), campaigns, intervention_events=interventions_for(campaigns))
    assert report["waterline_status"] == "PROPOSED_NATIVE_WATERLINE"
    assert report["counts"]["native_replications"] == 2


def test_augmented_replication_is_separate_from_native() -> None:
    campaigns = [
        campaign("one", "fail", "pass", "pass"),
        campaign("two", "fail", "pass", "pass"),
    ]
    report = analyze(protocol(), campaigns, intervention_events=interventions_for(campaigns))
    assert report["capability_status"] == "PROPOSED_AUGMENTED_WATERLINE"
    assert all(row["classification"] == "REPLICATED_AUGMENTED" for row in report["tasks"])


def test_runtime_fallback_does_not_count_as_subject_success() -> None:
    campaigns = [campaign("one", "pass", "fail", "pass")]
    native = campaigns[0]["routes"][0]["trials"][0]
    native["result"]["runtime_attestation"]["extra"]["runtime_model_id"] = "fallback-model"
    report = analyze(protocol(), campaigns, intervention_events=interventions_for(campaigns))
    row = report["tasks"][0]
    assert row["classification"] == "NO_DECISION"
    summary = next(x for x in row["route_summaries"] if x["route_id"] == "subject-native")
    assert summary["valid_decisive"] == 0
    assert "runtime_model_mismatch" in summary["invalid_trials"][0]["attestation"]["reasons"]


def test_transport_errors_never_buy_reference_residue() -> None:
    campaigns = [campaign("one", "error", "error", "pass")]
    report = analyze(protocol(), campaigns, intervention_events=interventions_for(campaigns))
    assert report["tasks"][0]["classification"] == "NO_DECISION"


def test_catalog_validation() -> None:
    value = {
        "schema": CATALOG_SCHEMA,
        "experiments": [
            {
                "id": "a",
                "domain": "model-tier",
                "question": "Where is the floor?",
                "status": "ready",
                "acceptance": "deterministic",
            },
            {
                "id": "b",
                "domain": "project",
                "question": "Where does judgment remain?",
                "status": "needs_tasks",
                "acceptance": "mixed",
            },
        ],
    }
    assert len(validate_catalog(value)["experiments"]) == 2


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="model-waterline-"))
    tests = [
        test_protocol_rejects_missing_attestation_rule,
        lambda: test_compile_materializes_hidden_task_and_campaign(parent / "one"),
        lambda: test_compile_refuses_uncommitted_manifest(parent / "two"),
        test_native_replication_requires_attention_and_audit_for_full_waterline,
        test_augmented_replication_is_separate_from_native,
        test_runtime_fallback_does_not_count_as_subject_success,
        test_transport_errors_never_buy_reference_residue,
        test_catalog_validation,
    ]
    try:
        for index, test in enumerate(tests):
            if index in {1, 2}:
                (parent / ("one" if index == 1 else "two")).mkdir()
            test()
        print(f"OK - {len(tests)}/{len(tests)} model-waterline tests passed; zero model calls")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
