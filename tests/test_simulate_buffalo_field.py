#!/usr/bin/env python3
"""Tests for the deterministic sparse-harvest illustrative projection."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import simulate_buffalo_field as buffalo  # noqa: E402


def _params(**overrides) -> buffalo.ProjectionParams:
    base = buffalo.ProjectionParams(hunts=12, portfolios=40, seed=12345)
    return replace(base, **overrides)


def _assert_value_error(fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_sparse_prior_is_strict_and_caps_are_coherent():
    _assert_value_error(lambda: replace(_params(), baseline_validated_probability=0.10).validate())
    _assert_value_error(
        lambda: replace(
            _params(),
            transfer_validation_probability=0.15,
            validated_probability_cap=0.20,
        ).validate()
    )
    _params().validate()


def test_failed_transfer_never_enters_pool_or_lifts_next_hunt():
    params = _params(
        hunts=2,
        family_count=1,
        baseline_validated_probability=0.05,
        transfer_validation_probability=0.50,
    )
    result = buffalo.simulate_arm_on_draws(
        params,
        families=(0, 0),
        candidate_uniforms=(0.0, 0.0),
        transfer_uniforms=(0.9, 0.9),
        compound=True,
        include_trace=True,
    )
    assert result["raw_candidates"] == 2
    assert result["validated_harvests"] == 0
    assert result["final_validated_artifacts"] == 0
    assert result["trace"][1]["validated_artifacts_in_family_before"] == 0
    assert result["trace"][1]["applicable_artifacts"] == 0


def test_validated_artifact_helps_only_later_work_in_same_family():
    params = _params(
        hunts=3,
        family_count=2,
        baseline_validated_probability=0.05,
        transfer_validation_probability=0.50,
    )
    result = buffalo.simulate_arm_on_draws(
        params,
        families=(0, 1, 0),
        candidate_uniforms=(0.0, 0.0, 0.0),
        transfer_uniforms=(0.0, 0.9, 0.9),
        compound=True,
        include_trace=True,
    )
    first, other_family, same_family_later = result["trace"]
    assert first["applicable_artifacts"] == 0
    assert first["transfer_passed"] is True
    assert other_family["applicable_artifacts"] == 0
    assert same_family_later["validated_artifacts_in_family_before"] == 1
    assert same_family_later["applicable_artifacts"] == 1
    assert (
        same_family_later["validated_harvest_probability"]
        > first["validated_harvest_probability"]
    )


def test_artifact_and_probability_caps_bind():
    params = _params(
        max_applicable_artifacts=2,
        odds_multiplier_per_artifact=100.0,
        validated_probability_cap=0.20,
    )
    probabilities = buffalo.probability_for_artifacts(params, 99)
    assert probabilities["applicable_artifacts"] == 2
    assert probabilities["cap_binding"] is True
    assert probabilities["validated_harvest_probability"] <= 0.20


def test_no_lift_is_bit_identical_to_control_under_shared_draws():
    params = _params(odds_multiplier_per_artifact=1.0, portfolios=80)
    for portfolio_index in range(params.portfolios):
        control, compounded = buffalo.simulate_pair(params, portfolio_index)
        assert control["raw_candidates"] == compounded["raw_candidates"]
        assert control["validated_harvests"] == compounded["validated_harvests"]
    result = buffalo.run_projection(params)
    delta = result["paired_delta_validated_harvests"]
    assert delta["minimum"] == delta["maximum"] == 0
    assert delta["pathwise_monotonicity_violations"] == 0


def test_positive_lift_is_pathwise_monotone_with_common_random_numbers():
    params = _params(hunts=40, portfolios=200)
    for portfolio_index in range(params.portfolios):
        control, compounded = buffalo.simulate_pair(params, portfolio_index)
        assert compounded["validated_harvests"] >= control["validated_harvests"]
    result = buffalo.run_projection(params)
    assert (
        result["paired_delta_validated_harvests"]["pathwise_monotonicity_violations"]
        == 0
    )


def test_seeded_projection_is_exactly_deterministic():
    params = _params(hunts=25, portfolios=120)
    assert buffalo.run_projection(params) == buffalo.run_projection(params)


def test_control_mean_tracks_the_analytic_sparse_prior():
    params = _params(hunts=50, portfolios=2_000, seed=20260712)
    result = buffalo.run_projection(params)
    observed = result["control"]["validated_harvests"]["mean"]
    expected = result["derived_assumptions"][
        "control_expected_validated_harvests_analytic"
    ]
    assert abs(observed - expected) < 0.15


def test_projection_labels_and_absence_states_are_explicit():
    result = buffalo.run_projection(_params())
    assert result["evidence_class"] == "ILLUSTRATIVE_PROJECTION"
    assert result["empirical"] is False
    assert result["failure_default"] == "REMAIN_UNMEASURED"
    assert result["work_accounting"]["tokens"]["state"] == "UNMEASURED"
    assert result["work_accounting"]["cost"]["state"] == "UNMEASURED"


def test_accounting_relationships_hold_for_every_arm():
    params = _params(hunts=30, portfolios=50)
    for portfolio_index in range(params.portfolios):
        for arm in buffalo.simulate_pair(params, portfolio_index):
            assert arm["transfer_attempts"] == arm["raw_candidates"]
            assert arm["transfer_passes"] == arm["validated_harvests"]
            assert arm["final_validated_artifacts"] == arm["validated_harvests"]
            assert arm["transfer_failures"] == (
                arm["transfer_attempts"] - arm["transfer_passes"]
            )


def _run_standalone() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:  # pragma: no cover - standalone diagnostic
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
