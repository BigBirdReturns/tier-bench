#!/usr/bin/env python3
"""Zero-model-call tests for the World Experience Atlas."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.experience_atlas import (  # noqa: E402
    AtlasError,
    catalog,
    compile_plan,
    validate_atlas,
    verify_plan,
)


ATLAS = ROOT / "experiments" / "world_experience" / "atlas.json"


def raw() -> dict:
    return json.loads(ATLAS.read_text(encoding="utf-8"))


def test_validate() -> None:
    atlas = validate_atlas(raw())
    assert len(atlas["references"]) == 14
    assert len(atlas["disciplines"]) == 11
    assert len(atlas["patterns"]) == 44


def test_plan_is_deterministic_and_dependency_closed() -> None:
    atlas = raw()
    first = compile_plan(atlas, limit=12)
    second = compile_plan(atlas, limit=12)
    assert first == second
    scheduled = {
        row["id"]
        for wave in first["waves"]
        for row in wave["patterns"]
    }
    by_id = {row["id"]: row for row in atlas["patterns"]}
    for identifier in scheduled:
        assert set(by_id[identifier]["depends_on"]) <= scheduled
    assert first["top_candidates"][0]["id"] in {
        "B01-action-cache-cas",
        "C01-typed-work-ir",
        "U01-attention-broker",
        "U02-batched-review-windows",
        "U03-reattachment-packets",
        "W01-event-history-replay",
    }


def test_tampered_plan_fails() -> None:
    atlas = raw()
    plan = compile_plan(atlas, limit=10)
    assert verify_plan(atlas, plan) == []
    plan["totals"]["patterns"] += 1
    assert verify_plan(atlas, plan)


def test_unknown_dependency_fails() -> None:
    atlas = raw()
    atlas["patterns"][0]["depends_on"].append("missing-pattern")
    try:
        validate_atlas(atlas)
    except AtlasError as exc:
        assert "missing dependencies" in str(exc)
    else:
        raise AssertionError("unknown dependency should fail")


def test_cycle_fails() -> None:
    atlas = raw()
    by_id = {row["id"]: row for row in atlas["patterns"]}
    by_id["B01-action-cache-cas"]["depends_on"] = ["B03-incremental-invalidation"]
    try:
        validate_atlas(atlas)
    except AtlasError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("dependency cycle should fail")


def test_strict_scores() -> None:
    atlas = raw()
    atlas["patterns"][0]["scores"]["attention_return"] = True
    try:
        validate_atlas(atlas)
    except AtlasError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("boolean score should fail")


def test_catalog_filters() -> None:
    result = catalog(raw(), discipline="human-attention")
    assert result["count"] == 4
    assert all(row["discipline"] == "human-attention" for row in result["patterns"])


def test_research_excluded_by_default_but_dependencies_admitted() -> None:
    plan = compile_plan(raw(), limit=44)
    rows = [
        row
        for wave in plan["waves"]
        for row in wave["patterns"]
    ]
    assert all(row["status"] != "research" for row in rows)
    research = compile_plan(raw(), statuses={"research"}, limit=44)
    ids = {row["id"] for wave in research["waves"] for row in wave["patterns"]}
    assert "C04-equality-saturation-plans" in ids
    assert "C01-typed-work-ir" in ids
    assert "D01-cost-based-work-optimizer" in ids


def main() -> int:
    tests = [
        test_validate,
        test_plan_is_deterministic_and_dependency_closed,
        test_tampered_plan_fails,
        test_unknown_dependency_fails,
        test_cycle_fails,
        test_strict_scores,
        test_catalog_filters,
        test_research_excluded_by_default_but_dependencies_admitted,
    ]
    for test in tests:
        test()
    print(f"OK - {len(tests)}/{len(tests)} World Experience Atlas tests passed; zero model calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
