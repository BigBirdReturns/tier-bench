"""Normalized shape derivation and conservative separation logic."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .canonical import Stage2Error, sha256_object, without_field
from .contracts import STAGE1_BLOBS, validate_observations, verify_stage1_blobs
from .generator import CONTROL_ROLES, EFFORTS, FAMILIES, K_LEVELS, R_LEVELS

RESULT_SCHEMA = "tier-bench/astra-stage2-calibration-result@1"
FEATURE_NAMES = (
    "r_elasticity",
    "k_elasticity",
    "k_curvature",
    "r_monotonicity",
    "r_nonmonotonicity",
    "token_residual_r_contrast",
    "effort_ttft_elasticity",
    "accuracy_floor",
)

RESULT_FIELDS = frozenset(
    {
        "absolute_timing_transfer",
        "accuracy_gate",
        "candidate_thresholds",
        "control_manifest_sha256",
        "empirical_candidate_may_self_freeze",
        "envelopes",
        "evidence_class",
        "feature_sample_count",
        "features",
        "fixture_may_freeze",
        "freeze_authority",
        "next_required_authority",
        "observation_count",
        "payload_sha256",
        "plan_sha256",
        "schema",
        "separation_checks",
        "stage1_custody",
        "stage2_frozen",
        "state",
        "threshold_derivation",
    }
)


def _median(values: Iterable[float]) -> float:
    materialized = [float(value) for value in values]
    if not materialized:
        raise Stage2Error("cannot compute a median over an empty set")
    return float(statistics.median(materialized))


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise Stage2Error("cannot compute a quantile over an empty set")
    if not 0.0 <= probability <= 1.0:
        raise Stage2Error("quantile probability is outside [0,1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _log_ratio(high: float, low: float, denominator: float) -> float:
    if high <= 0 or low <= 0 or denominator <= 0:
        raise Stage2Error("elasticity inputs must be positive")
    return math.log(high / low) / denominator


def _sample_features(rows: list[dict[str, Any]]) -> dict[str, float]:
    by_effort: dict[str, dict[tuple[int, int], dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_effort[row["effort"]][(row["k"], row["r"])] = row
    if set(by_effort) != set(EFFORTS):
        raise Stage2Error("feature sample lacks both frozen effort levels")
    for effort in EFFORTS:
        expected = {(k, r) for k in K_LEVELS for r in R_LEVELS}
        if set(by_effort[effort]) != expected:
            raise Stage2Error("feature sample lacks a complete K×R lattice")
        token_vectors = {
            (
                row["input_tokens"],
                row["cached_input_tokens"],
                row["output_tokens"],
                row["reasoning_tokens"],
            )
            for row in by_effort[effort].values()
        }
        if len(token_vectors) != 1:
            raise Stage2Error(
                "token-compute contrast requires one provider-reported token vector per effort block"
            )

    r_elasticities: list[float] = []
    k_elasticities: list[float] = []
    k_curvatures: list[float] = []
    r_monotonic_steps: list[float] = []
    r_nonmonotonic_peaks: list[float] = []
    residual_contrasts: list[float] = []
    accepted: list[float] = []
    for effort in EFFORTS:
        lattice = by_effort[effort]
        block_median = _median(row["latency_ms"] for row in lattice.values())
        for k in K_LEVELS:
            low = float(lattice[(k, R_LEVELS[0])]["latency_ms"])
            middle = float(lattice[(k, R_LEVELS[1])]["latency_ms"])
            high = float(lattice[(k, R_LEVELS[2])]["latency_ms"])
            r_elasticities.append(_log_ratio(high, low, math.log(R_LEVELS[-1] / R_LEVELS[0])))
            r_monotonic_steps.extend([1.0 if middle > low else 0.0, 1.0 if high > middle else 0.0])
            r_nonmonotonic_peaks.append(1.0 if middle > low and middle > high else 0.0)
            residual_contrasts.append((high - low) / block_median)
        for r in R_LEVELS:
            low = float(lattice[(K_LEVELS[0], r)]["latency_ms"])
            middle = float(lattice[(K_LEVELS[1], r)]["latency_ms"])
            high = float(lattice[(K_LEVELS[2], r)]["latency_ms"])
            first_slope = _log_ratio(middle, low, math.log(K_LEVELS[1] / K_LEVELS[0]))
            second_slope = _log_ratio(high, middle, math.log(K_LEVELS[2] / K_LEVELS[1]))
            k_elasticities.append(_log_ratio(high, low, math.log(K_LEVELS[-1] / K_LEVELS[0])))
            k_curvatures.append(second_slope - first_slope)
        accepted.extend(1.0 if row["accepted"] else 0.0 for row in lattice.values())

    effort_ttft = []
    for k in K_LEVELS:
        for r in R_LEVELS:
            low = float(by_effort["low"][(k, r)]["ttft_ms"])
            high = float(by_effort["high"][(k, r)]["ttft_ms"])
            effort_ttft.append((high - low) / low if low > 0 else 0.0)

    return {
        "r_elasticity": _median(r_elasticities),
        "k_elasticity": _median(k_elasticities),
        "k_curvature": _median(k_curvatures),
        "r_monotonicity": sum(r_monotonic_steps) / len(r_monotonic_steps),
        "r_nonmonotonicity": sum(r_nonmonotonic_peaks) / len(r_nonmonotonic_peaks),
        "token_residual_r_contrast": _median(residual_contrasts),
        "effort_ttft_elasticity": _median(effort_ttft),
        "accuracy_floor": min(accepted),
    }


def derive_feature_samples(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["control_id"], row["family"], row["replicate"])].append(row)
    expected_keys = {
        (control, family, replicate)
        for control in CONTROL_ROLES
        for family in FAMILIES
        for replicate in range(4)
    }
    if set(grouped) != expected_keys:
        raise Stage2Error("feature-sample denominator is incomplete or widened")
    output: dict[str, list[dict[str, Any]]] = {control: [] for control in CONTROL_ROLES}
    for key in sorted(grouped):
        control, family, replicate = key
        features = _sample_features(grouped[key])
        output[control].append(
            {
                "family": family,
                "replicate": replicate,
                "features": features,
                "sample_sha256": sha256_object(
                    {
                        "control_id": control,
                        "family": family,
                        "replicate": replicate,
                        "features": features,
                    }
                ),
            }
        )
    return output


def derive_envelopes(samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    envelopes: dict[str, Any] = {}
    for control in CONTROL_ROLES:
        if len(samples.get(control, [])) != 12:
            raise Stage2Error(f"control {control} must contribute exactly 12 feature samples")
        feature_envelopes: dict[str, Any] = {}
        for feature in FEATURE_NAMES:
            values = [float(sample["features"][feature]) for sample in samples[control]]
            feature_envelopes[feature] = {
                "lower_q10": _quantile(values, 0.10),
                "median": _quantile(values, 0.50),
                "upper_q90": _quantile(values, 0.90),
                "minimum": min(values),
                "maximum": max(values),
                "sample_count": len(values),
            }
        envelopes[control] = feature_envelopes
    return envelopes


def _separation(
    envelopes: dict[str, Any],
    *,
    higher: str,
    lower: str,
    feature: str,
) -> dict[str, Any]:
    high_lower = float(envelopes[higher][feature]["lower_q10"])
    low_upper = float(envelopes[lower][feature]["upper_q90"])
    separated = high_lower > low_upper
    return {
        "feature": feature,
        "higher_class": higher,
        "lower_class": lower,
        "higher_lower_q10": high_lower,
        "lower_upper_q90": low_upper,
        "margin": high_lower - low_upper,
        "separated": separated,
        "derived_midpoint": (high_lower + low_upper) / 2.0 if separated else None,
    }


def derive_candidate_thresholds(envelopes: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    checks = [
        _separation(
            envelopes,
            higher="lotus_3b_recurrent",
            lower="conventional_transformer_negative",
            feature="r_elasticity",
        ),
        _separation(
            envelopes,
            higher="lotus_3b_recurrent",
            lower="conventional_transformer_negative",
            feature="token_residual_r_contrast",
        ),
        _separation(
            envelopes,
            higher="loopcoder_v2_7b_parallel",
            lower="conventional_transformer_negative",
            feature="r_nonmonotonicity",
        ),
        _separation(
            envelopes,
            higher="loopcoder_v2_7b_parallel",
            lower="lotus_3b_recurrent",
            feature="k_curvature",
        ),
    ]
    thresholds = {
        f"{check['feature']}__{check['higher_class']}__over__{check['lower_class']}": float(
            check["derived_midpoint"]
        )
        for check in checks
        if check["separated"]
    }
    return checks, thresholds


def derive_calibration_result(
    observations: Iterable[Any],
    plan: dict[str, Any],
    control_manifest: dict[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    stage1_blobs = verify_stage1_blobs(repo_root)
    rows, evidence_class = validate_observations(observations, plan, control_manifest)
    samples = derive_feature_samples(rows)
    envelopes = derive_envelopes(samples)
    checks, candidate_thresholds = derive_candidate_thresholds(envelopes)
    observed_accuracy_floor = min(
        float(envelopes[control]["accuracy_floor"]["minimum"])
        for control in CONTROL_ROLES
    )
    accuracy_gate = observed_accuracy_floor == 1.0
    separated = all(check["separated"] for check in checks) and accuracy_gate

    if evidence_class == "fixture_synthetic":
        state = "FIXTURE_CONFORMANCE_ONLY"
        thresholds: dict[str, float] = {}
    elif separated:
        state = "EMPIRICAL_CALIBRATION_CANDIDATE"
        thresholds = candidate_thresholds
    else:
        state = "CALIBRATION_INCONCLUSIVE"
        thresholds = {}

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "state": state,
        "evidence_class": evidence_class,
        "stage2_frozen": False,
        "freeze_authority": "ABSENT_IN_SCAFFOLD",
        "plan_sha256": plan["payload_sha256"],
        "control_manifest_sha256": control_manifest["payload_sha256"],
        "stage1_custody": {
            "status": "VERIFIED",
            "blobs": stage1_blobs,
        },
        "observation_count": len(rows),
        "feature_sample_count": sum(len(value) for value in samples.values()),
        "features": list(FEATURE_NAMES),
        "envelopes": envelopes,
        "separation_checks": checks,
        "accuracy_gate": {
            "required_minimum": 1.0,
            "observed_minimum": observed_accuracy_floor,
            "passed": accuracy_gate,
        },
        "candidate_thresholds": thresholds,
        "threshold_derivation": "midpoint between non-overlapping q10/q90 control envelopes",
        "absolute_timing_transfer": "PROHIBITED",
        "fixture_may_freeze": False,
        "empirical_candidate_may_self_freeze": False,
        "next_required_authority": "exact released Sol calibration-law blob plus a separately qualified runtime successor",
    }
    result["payload_sha256"] = sha256_object(result)
    validate_calibration_result(result)
    return result


def validate_calibration_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("schema") != RESULT_SCHEMA:
        raise Stage2Error("unexpected calibration-result schema")
    missing = sorted(RESULT_FIELDS - set(result))
    unexpected = sorted(set(result) - RESULT_FIELDS)
    if missing or unexpected:
        raise Stage2Error(
            f"calibration-result property set mismatch: missing={missing}, unexpected={unexpected}"
        )
    observed_hash = result.get("payload_sha256")
    if observed_hash != sha256_object(without_field(result, "payload_sha256")):
        raise Stage2Error("calibration-result self-hash mismatch")
    if result.get("stage2_frozen") is not False:
        raise Stage2Error("provider-free scaffold may never emit a frozen Stage 2 state")
    if result.get("freeze_authority") != "ABSENT_IN_SCAFFOLD":
        raise Stage2Error("scaffold freeze authority widened")
    stage1_custody = result.get("stage1_custody")
    if not isinstance(stage1_custody, dict):
        raise Stage2Error("calibration result lacks Stage 1 custody")
    if set(stage1_custody) != {"status", "blobs"}:
        raise Stage2Error("calibration result Stage 1 custody property set differs")
    if stage1_custody.get("status") != "VERIFIED":
        raise Stage2Error("calibration result Stage 1 custody is not verified")
    if stage1_custody.get("blobs") != STAGE1_BLOBS:
        raise Stage2Error("calibration result Stage 1 blob set differs from the frozen set")
    state = result.get("state")
    evidence_class = result.get("evidence_class")
    if evidence_class == "fixture_synthetic":
        if state != "FIXTURE_CONFORMANCE_ONLY" or result.get("candidate_thresholds") != {}:
            raise Stage2Error("fixture evidence attempted to carry threshold or freeze authority")
    elif evidence_class == "empirical_local":
        if state not in {"EMPIRICAL_CALIBRATION_CANDIDATE", "CALIBRATION_INCONCLUSIVE"}:
            raise Stage2Error("invalid empirical calibration state")
    else:
        raise Stage2Error("invalid calibration-result evidence class")
    return result
