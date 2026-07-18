# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\diff_report.py  mutation_score=4/8
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))

import contextlib
import enum
import io
import json
import sys
import tempfile
import types
from collections import namedtuple
from pathlib import Path
from typing import Any, Callable, Dict, Tuple


# diff_report imports cost_guard and harness.metrics, which are absent in this
# working copy. Install lightweight stubs so the module can be imported and
# characterized.
cost_guard_module = types.ModuleType("cost_guard")
harness_package = types.ModuleType("harness")
harness_metrics = types.ModuleType("harness.metrics")
harness_package.__path__ = []  # type: ignore[attr-defined]
harness_package.metrics = harness_metrics  # type: ignore[attr-defined]
DummyTier = enum.Enum("DummyTier", {"dummy": "dummy"})
cost_guard_module.ROLES = {}
cost_guard_module.Tier = DummyTier
cost_guard_module._MODELS_RAW = {}


def _default_compute(_: Path) -> dict:
    return {}


harness_metrics.compute = _default_compute

sys.modules["cost_guard"] = cost_guard_module
sys.modules["harness"] = harness_package
sys.modules["harness.metrics"] = harness_metrics

import diff_report  # noqa: E402


def _install_cost_guard(tiers: tuple[str, ...], roles: Dict[str, str], models_raw: Dict[str, Any]) -> None:
    tier_enum = enum.Enum("Tier", {name: name for name in tiers})
    cost_guard_module.ROLES = roles
    cost_guard_module.Tier = tier_enum
    cost_guard_module._MODELS_RAW = models_raw
    diff_report.ROLES = roles
    diff_report.Tier = tier_enum
    diff_report._MODELS_RAW = models_raw


Stat = namedtuple("Stat", "attempts success_rate cost_per_success")


def _make_compute(stats_by_key: Dict[Tuple[str, str], Any]) -> Callable[[Path], Dict[Tuple[str, str], Any]]:
    def _compute(_: Path) -> Dict[Tuple[str, str], Any]:
        return stats_by_key

    return _compute


def test_build_diff_empty_stats() -> None:
    _install_cost_guard(("alpha", "beta"), {"driver": "target"}, {"target": {"tier_ceiling": "alpha"}})
    diff_report.compute = _make_compute({})
    report = diff_report.build_diff(Path("unused.jsonl"), "target")

    assert report["target"] == "target"
    assert report["tiers"] == []
    assert report["measured_ceiling"] is None
    assert report["hypothesis_ceiling"] == "alpha"
    assert report["unmeasured_tiers"] == ["alpha", "beta"]


def test_build_diff_no_target_data() -> None:
    _install_cost_guard(("a",), {"driver": "target"}, {"target": {"tier_ceiling": "a"}})
    diff_report.compute = _make_compute({("other", "a"): Stat(3, 1.0, 2.0)})
    report = diff_report.build_diff(Path("unused.jsonl"), "target")
    entry = report["tiers"][0]

    assert entry["tier"] == "a"
    assert entry["verdict"] == "no_target_data"
    assert entry["note"] == "target has no rows at a; run the benchmark first."
    assert "target" not in entry
    assert "best_match" not in entry


def test_build_diff_target_fails_tier() -> None:
    _install_cost_guard(("tier",), {"driver": "target"}, {"target": {"tier_ceiling": "tier"}})
    diff_report.compute = _make_compute(
        {
            ("target", "tier"): Stat(5, 0.0, 10.0),
            ("backup", "tier"): Stat(6, 0.2, 1.0),
        }
    )
    entry = diff_report.build_diff(Path("unused.jsonl"), "target")["tiers"][0]

    assert entry["tier"] == "tier"
    assert entry["target"] == {"attempts": 5, "success_rate": 0.0, "cost_per_success": 10.0}
    assert entry["verdict"] == "target_fails_tier"
    assert entry["note"] == "Nothing to replicate: the target itself fails here."


def test_build_diff_replicated() -> None:
    _install_cost_guard(("tier",), {"driver": "target"}, {"target": {"tier_ceiling": "tier"}})
    diff_report.compute = _make_compute(
        {
            ("target", "tier"): Stat(9, 0.70, 4.0),
            ("better", "tier"): Stat(5, 0.70, 2.0),
            ("bad", "tier"): Stat(5, 0.80, 0.0),
        }
    )
    entry = diff_report.build_diff(Path("unused.jsonl"), "target")["tiers"][0]

    assert entry["verdict"] == "replicated"
    assert entry["best_match"] == {
        "model": "bad",
        "success_rate": 0.8,
        "cost_per_success": 0.0,
        "cost_ratio": None,
    }
    assert entry["best_match"]["cost_ratio"] is None


def test_build_diff_matched_not_cheaper_and_ceiling() -> None:
    _install_cost_guard(("tier", "higher"), {"driver": "target"}, {"target": {"tier_ceiling": "higher"}})
    diff_report.compute = _make_compute(
        {
            ("target", "higher"): Stat(11, 0.60, 3.0),
            ("expensive", "higher"): Stat(7, 0.60, 9.0),
            ("low", "higher"): Stat(8, 0.20, 0.0),
        }
    )
    entry = diff_report.build_diff(Path("unused.jsonl"), "target")["tiers"][0]

    assert entry["verdict"] == "matched_not_cheaper"
    assert entry["best_match"] == {
        "model": "expensive",
        "success_rate": 0.6,
        "cost_per_success": 9.0,
        "cost_ratio": 0.3,
    }
    assert entry["best_match"]["cost_ratio"] == 0.3
    assert entry["target"]["success_rate"] == 0.6
    assert entry["target"]["attempts"] == 11
    report = diff_report.build_diff(Path("unused.jsonl"), "target")
    assert report["measured_ceiling"] is None
    assert report["unmeasured_tiers"] == ["tier"]


def test_build_diff_frontier_edge_with_note() -> None:
    _install_cost_guard(("t1",), {"driver": "target"}, {"target": {"tier_ceiling": None}})
    diff_report.compute = _make_compute(
        {
            ("target", "t1"): Stat(10, 0.55, 2.0),
            ("laggard", "t1"): Stat(10, 0.40, 1.0),
            ("zero_attempts", "t1"): Stat(0, 0.0, float("inf")),
        }
    )
    entry = diff_report.build_diff(Path("unused.jsonl"), "target")["tiers"][0]

    assert entry["verdict"] == "frontier_edge"
    assert entry["note"] == (
        "No benchmarked model or composite matches the target's success "
        "rate at this tier. This is the measured part of what you pay for."
    )
    assert "best_match" not in entry


def test_render_text_replication_and_unmeasured_text() -> None:
    report = {
        "target": "target",
        "tiers": [
            {
                "tier": "t1",
                "target": {"attempts": 2, "success_rate": 1.0, "cost_per_success": 0.25},
                "best_match": {
                    "model": "faster",
                    "success_rate": 1.0,
                    "cost_per_success": 0.05,
                    "cost_ratio": 5.0,
                },
                "verdict": "replicated",
            },
            {"tier": "t2", "verdict": "frontier_edge", "note": "No match."},
        ],
        "measured_ceiling": "t1",
        "hypothesis_ceiling": None,
        "unmeasured_tiers": ["t3"],
    }
    out = diff_report.render_text(report)
    lines = out.splitlines()

    assert lines[0].startswith("Frontier diff")
    assert lines[0].endswith("target: target")
    assert lines[4] == "  target : 100% success, $0.2500/success (2 attempts)"
    assert lines[5].startswith("  match  : faster")
    assert "REPLICATED" in lines[6]
    assert "faster" in lines[6]
    assert "5.0x" in lines[6]
    assert lines[8] == "t2"
    assert lines[9].startswith("  verdict:")
    assert "FRONTIER EDGE" in lines[9]
    assert lines[10] == "           No match."
    assert lines[-3] == "Measured ceiling : t1"
    assert lines[-2] == "Registry claim   : not registered"
    assert lines[-1].startswith("Unmeasured tiers : t3 ")


def test_main_no_target() -> None:
    _install_cost_guard(("t",), {}, {"target": {"tier_ceiling": None}})
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as temp:
        sys.argv = ["diff_report.py", "--results", temp.name]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = diff_report.main()

    assert rc == 2
    assert buf.getvalue() == "No --target given and no roles.driver in models.json.\n"


def test_main_missing_results_file() -> None:
    _install_cost_guard(("t",), {"driver": "target"}, {"target": {"tier_ceiling": None}})
    sys.argv = ["diff_report.py", "--target", "target", "--results", "missing.jsonl"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = diff_report.main()

    assert rc == 2
    assert buf.getvalue() == "No results at missing.jsonl. Run: python orchestrator.py --benchmark all\n"


def test_main_json_output() -> None:
    _install_cost_guard(("t",), {"driver": "target"}, {"target": {"tier_ceiling": "t"}})
    diff_report.compute = _make_compute({("target", "t"): Stat(4, 1.0, 2.0)})
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as temp:
        temp.write(b"{}")
        temp.flush()
        sys.argv = ["diff_report.py", "--target", "target", "--results", temp.name, "--json"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = diff_report.main()

    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["target"] == "target"
    assert payload["tiers"][0]["target"]["attempts"] == 4
    assert payload["tiers"][0]["target"]["cost_per_success"] == 2.0
    assert payload["tiers"][0]["verdict"] == "frontier_edge"
    assert "best_match" not in payload["tiers"][0]


def main() -> None:
    tests = [
        test_build_diff_empty_stats,
        test_build_diff_no_target_data,
        test_build_diff_target_fails_tier,
        test_build_diff_replicated,
        test_build_diff_matched_not_cheaper_and_ceiling,
        test_build_diff_frontier_edge_with_note,
        test_render_text_replication_and_unmeasured_text,
        test_main_no_target,
        test_main_missing_results_file,
        test_main_json_output,
    ]
    for test in tests:
        test()
    print("OK")


if __name__ == "__main__":
    main()
