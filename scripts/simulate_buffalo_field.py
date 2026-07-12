#!/usr/bin/env python3
"""Deterministic sparse-harvest compounding projection.

This is an illustrative model, not empirical evidence.  It asks what a field of
low-prior hunts could look like if a raw candidate must survive a distinct
transfer check before it becomes reusable residue, and if that residue can help
only later work in its declared family.

The no-compounding control and compounded arm share the same family schedule,
candidate uniforms, and transfer uniforms.  Component streams are derived from
the recorded seed with SHA-256, so conditional RNG consumption cannot make the
arms drift.  The coupling is a variance-reduction device, not an observation.

Example:

    python scripts/simulate_buffalo_field.py --portfolios 10000 --hunts 100
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

EVIDENCE_CLASS = "ILLUSTRATIVE_PROJECTION"
FAILURE_DEFAULT = "REMAIN_UNMEASURED"


@dataclass(frozen=True)
class ProjectionParams:
    """Preregistered assumptions for one paired Monte Carlo projection."""

    hunts: int = 100
    portfolios: int = 10_000
    baseline_validated_probability: float = 0.08
    transfer_validation_probability: float = 0.35
    family_count: int = 8
    odds_multiplier_per_artifact: float = 1.8
    max_applicable_artifacts: int = 3
    validated_probability_cap: float = 0.20
    seed: int = 20_260_712

    def validate(self) -> None:
        p0 = self.baseline_validated_probability
        q = self.transfer_validation_probability
        cap = self.validated_probability_cap
        if self.hunts <= 0:
            raise ValueError("hunts must be positive")
        if self.portfolios <= 0:
            raise ValueError("portfolios must be positive")
        if not 0.0 < p0 < 0.10:
            raise ValueError("baseline_validated_probability must be strictly below 0.10")
        if not p0 < q <= 1.0:
            raise ValueError(
                "transfer_validation_probability must be greater than the baseline "
                "validated probability and at most 1"
            )
        if not p0 <= cap <= q:
            raise ValueError(
                "validated_probability_cap must be at least the baseline and no greater "
                "than transfer_validation_probability"
            )
        if self.family_count <= 0:
            raise ValueError("family_count must be positive")
        if self.odds_multiplier_per_artifact < 1.0:
            raise ValueError("odds_multiplier_per_artifact must be at least 1")
        if self.max_applicable_artifacts < 0:
            raise ValueError("max_applicable_artifacts must be non-negative")


def _component_seed(seed: int, portfolio_index: int, component: str) -> int:
    material = f"{seed}:{portfolio_index}:{component}".encode("ascii")
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big")


def probability_for_artifacts(
    params: ProjectionParams,
    available_artifacts: int,
    *,
    compound: bool = True,
) -> dict:
    """Return the bounded two-stage probabilities for one hunt.

    ``p0`` names the probability of a *validated* harvest without residue.  If
    transfer succeeds with probability ``q``, the corresponding raw-candidate
    probability is ``p0 / q``.  Applicable residue multiplies raw-candidate
    odds.  The validated cap is converted to a raw cap with the same factor.
    """
    params.validate()
    if available_artifacts < 0:
        raise ValueError("available_artifacts must be non-negative")

    return _probability_for_artifacts_unchecked(params, available_artifacts, compound=compound)


def _probability_for_artifacts_unchecked(
    params: ProjectionParams,
    available_artifacts: int,
    *,
    compound: bool,
) -> dict:
    """Inner-loop form; callers validate the parameters and artifact count once."""

    applicable = min(available_artifacts, params.max_applicable_artifacts)
    if not compound:
        applicable = 0
    q = params.transfer_validation_probability
    raw_base = params.baseline_validated_probability / q
    raw_cap = params.validated_probability_cap / q
    base_odds = raw_base / (1.0 - raw_base)
    lifted_odds = base_odds * params.odds_multiplier_per_artifact**applicable
    uncapped_raw = lifted_odds / (1.0 + lifted_odds)
    raw_probability = min(uncapped_raw, raw_cap)
    return {
        "applicable_artifacts": applicable,
        "raw_candidate_probability": raw_probability,
        "validated_harvest_probability": raw_probability * q,
        "cap_binding": uncapped_raw > raw_cap,
    }


def simulate_arm_on_draws(
    params: ProjectionParams,
    families: Sequence[int],
    candidate_uniforms: Sequence[float],
    transfer_uniforms: Sequence[float],
    *,
    compound: bool,
    include_trace: bool = False,
) -> dict:
    """Run one arm on fixed draws; useful for paired simulation and witnesses."""
    params.validate()
    if not (len(families) == len(candidate_uniforms) == len(transfer_uniforms)):
        raise ValueError("families and uniform sequences must have equal length")
    if len(families) != params.hunts:
        raise ValueError("draw sequences must contain exactly params.hunts entries")
    if any(f < 0 or f >= params.family_count for f in families):
        raise ValueError("family index outside configured family_count")
    if any(not 0.0 <= u < 1.0 for u in (*candidate_uniforms, *transfer_uniforms)):
        raise ValueError("uniform draws must be in [0, 1)")

    artifacts_by_family = [0] * params.family_count
    raw_candidates = 0
    transfer_passes = 0
    cap_binding_hunts = 0
    artifact_assisted_hunts = 0
    max_applicable_seen = 0
    trace = []

    for hunt_index, (family, candidate_u, transfer_u) in enumerate(
        zip(families, candidate_uniforms, transfer_uniforms)
    ):
        before = artifacts_by_family[family]
        probabilities = _probability_for_artifacts_unchecked(
            params, before, compound=compound
        )
        applicable = probabilities["applicable_artifacts"]
        candidate = candidate_u < probabilities["raw_candidate_probability"]
        transfer_passed = candidate and transfer_u < params.transfer_validation_probability

        raw_candidates += int(candidate)
        transfer_passes += int(transfer_passed)
        cap_binding_hunts += int(probabilities["cap_binding"])
        artifact_assisted_hunts += int(applicable > 0)
        max_applicable_seen = max(max_applicable_seen, applicable)

        # The new residue becomes available only after this hunt's distinct
        # transfer gate, so it cannot help the hunt that produced it.
        if transfer_passed:
            artifacts_by_family[family] += 1

        if include_trace:
            trace.append(
                {
                    "hunt_index": hunt_index,
                    "family": family,
                    "validated_artifacts_in_family_before": before,
                    **probabilities,
                    "raw_candidate": candidate,
                    "transfer_passed": transfer_passed,
                    "validated_artifacts_in_family_after": artifacts_by_family[family],
                }
            )

    result = {
        "raw_candidates": raw_candidates,
        "transfer_attempts": raw_candidates,
        "transfer_passes": transfer_passes,
        "transfer_failures": raw_candidates - transfer_passes,
        "validated_harvests": transfer_passes,
        "final_validated_artifacts": transfer_passes,
        "artifacts_by_family": artifacts_by_family,
        "artifact_assisted_hunts": artifact_assisted_hunts,
        "cap_binding_hunts": cap_binding_hunts,
        "max_applicable_artifacts_seen": max_applicable_seen,
    }
    if include_trace:
        result["trace"] = trace
    return result


def simulate_pair(params: ProjectionParams, portfolio_index: int) -> tuple[dict, dict]:
    """Run the control and compounded arms with common random numbers."""
    params.validate()
    if portfolio_index < 0:
        raise ValueError("portfolio_index must be non-negative")

    family_rng = random.Random(_component_seed(params.seed, portfolio_index, "family"))
    candidate_rng = random.Random(_component_seed(params.seed, portfolio_index, "candidate"))
    transfer_rng = random.Random(_component_seed(params.seed, portfolio_index, "transfer"))
    families = tuple(family_rng.randrange(params.family_count) for _ in range(params.hunts))
    candidate_uniforms = tuple(candidate_rng.random() for _ in range(params.hunts))
    transfer_uniforms = tuple(transfer_rng.random() for _ in range(params.hunts))

    control = simulate_arm_on_draws(
        params,
        families,
        candidate_uniforms,
        transfer_uniforms,
        compound=False,
    )
    compounded = simulate_arm_on_draws(
        params,
        families,
        candidate_uniforms,
        transfer_uniforms,
        compound=True,
    )
    return control, compounded


def _nearest_rank(values: Sequence[int], probability: float) -> int:
    if not values:
        raise ValueError("cannot take a quantile of an empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _round(value: float) -> float:
    return round(value, 6)


def _series_summary(values: Sequence[int]) -> dict:
    if not values:
        raise ValueError("cannot summarize an empty sequence")
    mean = statistics.fmean(values)
    sample_sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": _round(mean),
        "sample_standard_deviation": _round(sample_sd),
        "monte_carlo_standard_error_of_mean": _round(sample_sd / math.sqrt(len(values))),
        "minimum": min(values),
        "maximum": max(values),
        "quantiles_nearest_rank": {
            "p05": _nearest_rank(values, 0.05),
            "p50": _nearest_rank(values, 0.50),
            "p95": _nearest_rank(values, 0.95),
        },
        "fraction_zero": _round(sum(value == 0 for value in values) / len(values)),
    }


def _collect(rows: Iterable[dict], key: str) -> list[int]:
    return [row[key] for row in rows]


def run_projection(params: ProjectionParams = ProjectionParams()) -> dict:
    """Run the paired deterministic projection and return a JSON-ready receipt."""
    params.validate()
    controls = []
    compounded = []
    for portfolio_index in range(params.portfolios):
        control, lifted = simulate_pair(params, portfolio_index)
        controls.append(control)
        compounded.append(lifted)

    control_validated = _collect(controls, "validated_harvests")
    compounded_validated = _collect(compounded, "validated_harvests")
    deltas = [lifted - control for control, lifted in zip(control_validated, compounded_validated)]
    monotonicity_violations = sum(delta < 0 for delta in deltas)

    control_raw = _collect(controls, "raw_candidates")
    compounded_raw = _collect(compounded, "raw_candidates")
    compounded_cap = _collect(compounded, "cap_binding_hunts")
    compounded_assisted = _collect(compounded, "artifact_assisted_hunts")

    p0 = params.baseline_validated_probability
    q = params.transfer_validation_probability
    paired_delta = _series_summary(deltas)
    paired_delta.update(
        {
            "fraction_positive": _round(sum(delta > 0 for delta in deltas) / len(deltas)),
            "pathwise_monotonicity_violations": monotonicity_violations,
            "mean_95_percent_monte_carlo_interval": [
                _round(
                    paired_delta["mean"]
                    - 1.96 * paired_delta["monte_carlo_standard_error_of_mean"]
                ),
                _round(
                    paired_delta["mean"]
                    + 1.96 * paired_delta["monte_carlo_standard_error_of_mean"]
                ),
            ],
            "interval_scope": "Monte Carlo error of the paired mean, not outcome uncertainty",
        }
    )

    return {
        "evidence_class": EVIDENCE_CLASS,
        "empirical": False,
        "failure_default": FAILURE_DEFAULT,
        "claim_boundary": [
            "No capability, amortization, return-on-investment, or upstream-fix claim.",
            "Parameters are preregistered illustrative assumptions, not fitted observations.",
            "Only sealed distinct-transfer evidence may replace this projection with measurement.",
        ],
        "parameters": asdict(params),
        "derived_assumptions": {
            "baseline_raw_candidate_probability": _round(p0 / q),
            "raw_candidate_probability_cap": _round(params.validated_probability_cap / q),
            "nominal_same_family_probability": _round(1.0 / params.family_count),
            "control_expected_validated_harvests_analytic": _round(params.hunts * p0),
            "control_variance_validated_harvests_analytic": _round(
                params.hunts * p0 * (1.0 - p0)
            ),
            "transfer_item_is_distinct": True,
            "transfer_item_may_validate_but_does_not_mint_a_second_artifact": True,
        },
        "randomness": {
            "seed": params.seed,
            "generator": "Python random.Random (MT19937)",
            "python_version": platform.python_version(),
            "component_seed_derivation": (
                "first 64 bits of SHA-256(seed:portfolio_index:component)"
            ),
            "shared_components": ["family", "candidate", "transfer"],
            "coupling_note": (
                "Common random numbers reduce comparison noise; they are not empirical pairing."
            ),
        },
        "control": {
            "validated_harvests": _series_summary(control_validated),
            "raw_candidates_and_transfer_attempts": _series_summary(control_raw),
            "transfer_failures": _series_summary(_collect(controls, "transfer_failures")),
        },
        "compounding": {
            "validated_harvests": _series_summary(compounded_validated),
            "raw_candidates_and_transfer_attempts": _series_summary(compounded_raw),
            "transfer_failures": _series_summary(_collect(compounded, "transfer_failures")),
            "artifact_assisted_hunts": _series_summary(compounded_assisted),
            "cap_binding_hunts": _series_summary(compounded_cap),
        },
        "paired_delta_validated_harvests": paired_delta,
        "work_accounting": {
            "hunt_work_items_per_portfolio": params.hunts,
            "control_mean_distinct_transfer_items": _round(statistics.fmean(control_raw)),
            "compounding_mean_distinct_transfer_items": _round(
                statistics.fmean(compounded_raw)
            ),
            "control_mean_total_distinct_items": _round(
                params.hunts + statistics.fmean(control_raw)
            ),
            "compounding_mean_total_distinct_items": _round(
                params.hunts + statistics.fmean(compounded_raw)
            ),
            "tokens": {
                "state": "UNMEASURED",
                "note": "No token-per-hunt or token-per-transfer value was guessed.",
            },
            "cost": {
                "state": "UNMEASURED",
                "note": "No price or billing basis was supplied.",
            },
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hunts", type=int, default=ProjectionParams.hunts)
    parser.add_argument("--portfolios", type=int, default=ProjectionParams.portfolios)
    parser.add_argument(
        "--p0", type=float, default=ProjectionParams.baseline_validated_probability
    )
    parser.add_argument(
        "--transfer-validation",
        type=float,
        default=ProjectionParams.transfer_validation_probability,
    )
    parser.add_argument("--families", type=int, default=ProjectionParams.family_count)
    parser.add_argument(
        "--odds-multiplier",
        type=float,
        default=ProjectionParams.odds_multiplier_per_artifact,
    )
    parser.add_argument(
        "--max-applicable-artifacts",
        type=int,
        default=ProjectionParams.max_applicable_artifacts,
    )
    parser.add_argument(
        "--validated-probability-cap",
        type=float,
        default=ProjectionParams.validated_probability_cap,
    )
    parser.add_argument("--seed", type=int, default=ProjectionParams.seed)
    parser.add_argument("--indent", type=int, default=2)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    params = ProjectionParams(
        hunts=args.hunts,
        portfolios=args.portfolios,
        baseline_validated_probability=args.p0,
        transfer_validation_probability=args.transfer_validation,
        family_count=args.families,
        odds_multiplier_per_artifact=args.odds_multiplier,
        max_applicable_artifacts=args.max_applicable_artifacts,
        validated_probability_cap=args.validated_probability_cap,
        seed=args.seed,
    )
    try:
        result = run_projection(params)
    except ValueError as exc:
        raise SystemExit(f"invalid projection: {exc}") from exc
    payload = json.dumps(result, indent=args.indent, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
