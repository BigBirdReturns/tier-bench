#!/usr/bin/env python3
"""Adversarial provider-free witnesses for the Stage 2 scaffold."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from astra_stage2.calibration import derive_calibration_result, validate_calibration_result
from astra_stage2.canonical import Stage2Error, git_blob_sha1_bytes, sha256_object
from astra_stage2 import contracts
from astra_stage2.contracts import (
    bind_empirical_control_manifest,
    validate_control_manifest,
    validate_generator_manifest,
    validate_observations,
    validate_plan,
    verify_stage1_blobs,
)
from astra_stage2.generator import (
    EXPECTED_CASE_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    build_task,
    empirical_control_template,
    fixture_control_manifest,
    reconstruct_task,
)


def rehash(value: dict, field: str = "payload_sha256") -> dict:
    value[field] = sha256_object({key: child for key, child in value.items() if key != field})
    return value


def rehash_observation(row: dict) -> dict:
    return rehash(row, "record_sha256")


class Stage2ScaffoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = build_generator_manifest()
        cls.fixture_control = fixture_control_manifest()
        cls.plan = build_calibration_plan(cls.generator, cls.fixture_control)
        cls.observations = build_fixture_observations(cls.plan)

    def test_01_generator_denominator_is_108(self) -> None:
        self.assertEqual(self.generator["case_count"], EXPECTED_CASE_COUNT)
        self.assertEqual(len(self.generator["cases"]), 108)
        validate_generator_manifest(self.generator)

    def test_02_generator_is_deterministic(self) -> None:
        self.assertEqual(build_generator_manifest(), self.generator)
        task_a = build_task(family="pointer_chase", k=8, r=16, replicate=2)
        task_b = build_task(family="pointer_chase", k=8, r=16, replicate=2)
        self.assertEqual(task_a, task_b)

    def test_03_every_case_reconstructs_exactly(self) -> None:
        for case in self.generator["cases"]:
            task = reconstruct_task(case)
            self.assertEqual(sha256_object(task), case["task_sha256"])
            self.assertEqual(task["expected_checksum"], case["expected_checksum"])

    def test_04_generator_tamper_refuses(self) -> None:
        mutated = copy.deepcopy(self.generator)
        mutated["cases"][0]["expected_checksum"] = "0" * 16
        rehash(mutated)
        with self.assertRaises(Stage2Error):
            validate_generator_manifest(mutated)

    def test_05_plan_denominator_is_648(self) -> None:
        self.assertEqual(self.plan["observation_count"], EXPECTED_OBSERVATION_COUNT)
        self.assertEqual(len(self.plan["observations"]), 648)
        validate_plan(self.plan, self.generator, self.fixture_control)

    def test_06_duplicate_plan_cell_refuses(self) -> None:
        mutated = copy.deepcopy(self.plan)
        mutated["observations"][1] = copy.deepcopy(mutated["observations"][0])
        rehash(mutated)
        with self.assertRaises(Stage2Error):
            validate_plan(mutated, self.generator, self.fixture_control)

    def test_07_plan_control_binding_refuses(self) -> None:
        mutated = copy.deepcopy(self.plan)
        mutated["control_manifest_sha256"] = "0" * 64
        rehash(mutated)
        with self.assertRaises(Stage2Error):
            validate_plan(mutated, self.generator, self.fixture_control)

    def test_08_fixture_observation_denominator_is_648(self) -> None:
        rows, evidence_class = validate_observations(
            self.observations, self.plan, self.fixture_control
        )
        self.assertEqual(len(rows), 648)
        self.assertEqual(evidence_class, "fixture_synthetic")

    def test_09_fixture_derivation_is_non_authoritative(self) -> None:
        result = derive_calibration_result(
            self.observations, self.plan, self.fixture_control
        )
        self.assertEqual(result["state"], "FIXTURE_CONFORMANCE_ONLY")
        self.assertFalse(result["stage2_frozen"])
        self.assertEqual(result["candidate_thresholds"], {})
        validate_calibration_result(result)

    def test_10_fixture_cannot_claim_frozen(self) -> None:
        result = derive_calibration_result(
            self.observations, self.plan, self.fixture_control
        )
        result["stage2_frozen"] = True
        rehash(result)
        with self.assertRaises(Stage2Error):
            validate_calibration_result(result)

    def test_11_fixture_cannot_retain_thresholds(self) -> None:
        result = derive_calibration_result(
            self.observations, self.plan, self.fixture_control
        )
        result["candidate_thresholds"] = {"fabricated": 1.0}
        rehash(result)
        with self.assertRaises(Stage2Error):
            validate_calibration_result(result)

    def test_12_incomplete_observation_denominator_refuses(self) -> None:
        with self.assertRaises(Stage2Error):
            validate_observations(self.observations[:-1], self.plan, self.fixture_control)

    def test_13_duplicate_observation_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[-1] = copy.deepcopy(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_14_control_identity_drift_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["control_identity_sha256"] = "f" * 64
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_15_route_identity_drift_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[1]["route_identity_sha256"] = "e" * 64
        rehash_observation(rows[1])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_16_runtime_contract_drift_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[1]["api_contract_sha256"] = "d" * 64
        rehash_observation(rows[1])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_17_raw_text_retention_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["prompt_text"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_18_nonfinite_metric_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["latency_ms"] = math.inf
        with self.assertRaises(Stage2Error):
            rehash_observation(rows[0])

    def test_19_acceptance_is_reconstructed(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["observed_checksum"] = "0" * 16
        rows[0]["accepted"] = True
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_20_unbound_empirical_manifest_refuses(self) -> None:
        template = empirical_control_template()
        with self.assertRaises(Stage2Error):
            validate_control_manifest(template, require_bound_empirical=True)
        with self.assertRaises(Stage2Error):
            bind_empirical_control_manifest(template)

    def test_21_overlapping_empirical_envelopes_are_inconclusive(self) -> None:
        template = empirical_control_template()
        for control in template["controls"]:
            identity = control["identity"]
            for field in contracts.IDENTITY_DIGEST_FIELDS:
                identity[field] = sha256_object({"field": field, "role": control["control_id"]})
        bound = bind_empirical_control_manifest(template)
        plan = build_calibration_plan(self.generator, bound)
        rows = build_fixture_observations(plan)
        for row in rows:
            row["evidence_class"] = "empirical_local"
            row["latency_ms"] = 1000.0
            row["ttft_ms"] = 250.0 if row["effort"] == "low" else 300.0
            row["control_identity_sha256"] = next(
                control["identity_sha256"]
                for control in bound["controls"]
                if control["control_id"] == row["control_id"]
            )
            rehash_observation(row)
        result = derive_calibration_result(rows, plan, bound)
        self.assertEqual(result["state"], "CALIBRATION_INCONCLUSIVE")
        self.assertFalse(result["stage2_frozen"])
        self.assertEqual(result["candidate_thresholds"], {})

    def test_22_stage1_blob_verifier_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "frozen.txt"
            path.write_bytes(b"exact frozen bytes\n")
            original = contracts.STAGE1_BLOBS
            try:
                contracts.STAGE1_BLOBS = {
                    "frozen.txt": git_blob_sha1_bytes(path.read_bytes())
                }
                self.assertEqual(
                    verify_stage1_blobs(root)["frozen.txt"],
                    git_blob_sha1_bytes(path.read_bytes()),
                )
                path.write_bytes(b"mutated\n")
                with self.assertRaises(Stage2Error):
                    verify_stage1_blobs(root)
            finally:
                contracts.STAGE1_BLOBS = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
