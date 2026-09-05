#!/usr/bin/env python3
"""Adversarial provider-free witnesses for the Stage 2 scaffold."""

from __future__ import annotations

import copy
import hashlib
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_stage2 import contracts
from astra_stage2.calibration import derive_calibration_result, validate_calibration_result
from astra_stage2.canonical import Stage2Error, sha256_object
from astra_stage2.contracts import (
    bind_empirical_control_manifest,
    validate_control_manifest,
    validate_generator_manifest,
    validate_observations,
    validate_plan,
    verify_stage1_blobs,
)
from astra_stage2.generator import (
    CHECKSUM_HEX_LENGTH,
    EXPECTED_CASE_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    build_calibration_plan,
    build_fixture_observations,
    build_generator_manifest,
    build_task,
    empirical_control_template,
    fixture_control_manifest,
    reconstruct_task,
    render_task_prompt,
)


def rehash(value: dict, field: str = "payload_sha256") -> dict:
    value[field] = sha256_object({key: child for key, child in value.items() if key != field})
    return value


def rehash_observation(row: dict) -> dict:
    return rehash(row, "record_sha256")


def run_git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


class Stage2ScaffoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.generator = build_generator_manifest()
        cls.fixture_control = fixture_control_manifest()
        cls.plan = build_calibration_plan(cls.generator, cls.fixture_control)
        cls.observations = build_fixture_observations(cls.plan)

    def _empirical_template_with_digests(self):
        template = empirical_control_template()
        for control in template["controls"]:
            identity = control["identity"]
            for field in contracts.IDENTITY_DIGEST_FIELDS:
                identity[field] = sha256_object(
                    {"field": field, "role": control["control_id"]}
                )
        return template

    def _bound_empirical_rows(self):
        bound = bind_empirical_control_manifest(self._empirical_template_with_digests())
        plan = build_calibration_plan(self.generator, bound)
        identities = {
            control["control_id"]: control["identity_sha256"]
            for control in bound["controls"]
        }
        rows = build_fixture_observations(plan)
        for row in rows:
            row["evidence_class"] = "empirical_local"
            row["control_identity_sha256"] = identities[row["control_id"]]
            rehash_observation(row)
        return bound, plan, rows

    def _validate_result(
        self,
        result: dict,
        *,
        control: dict | None = None,
        plan: dict | None = None,
        rows: list[dict] | None = None,
    ) -> dict:
        return validate_calibration_result(
            result,
            generator_manifest=self.generator,
            control_manifest=self.fixture_control if control is None else control,
            plan=self.plan if plan is None else plan,
            observations=self.observations if rows is None else rows,
            repo_root=self.repo_root,
        )

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

    def test_04_generator_tamper_and_unknown_properties_refuse(self) -> None:
        mutated = copy.deepcopy(self.generator)
        mutated["cases"][0]["expected_checksum"] = "0" * CHECKSUM_HEX_LENGTH
        rehash(mutated)
        with self.assertRaises(Stage2Error):
            validate_generator_manifest(mutated)

        unknown_manifest = copy.deepcopy(self.generator)
        unknown_manifest["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(unknown_manifest)
        with self.assertRaises(Stage2Error):
            validate_generator_manifest(unknown_manifest)

        unknown_case = copy.deepcopy(self.generator)
        unknown_case["cases"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(unknown_case)
        with self.assertRaises(Stage2Error):
            validate_generator_manifest(unknown_case)

        unfrozen_version = copy.deepcopy(self.generator)
        unfrozen_version["generator_version"] = "astra-stage2-generator-v999"
        rehash(unfrozen_version)
        with self.assertRaises(Stage2Error):
            validate_generator_manifest(unfrozen_version)

    def test_05_plan_denominator_is_648(self) -> None:
        self.assertEqual(self.plan["observation_count"], EXPECTED_OBSERVATION_COUNT)
        self.assertEqual(len(self.plan["observations"]), 648)
        validate_plan(self.plan, self.generator, self.fixture_control)

    def test_06_plan_duplicate_and_unknown_properties_refuse(self) -> None:
        mutated = copy.deepcopy(self.plan)
        mutated["observations"][1] = copy.deepcopy(mutated["observations"][0])
        rehash(mutated)
        with self.assertRaises(Stage2Error):
            validate_plan(mutated, self.generator, self.fixture_control)

        unknown_plan = copy.deepcopy(self.plan)
        unknown_plan["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(unknown_plan)
        with self.assertRaises(Stage2Error):
            validate_plan(unknown_plan, self.generator, self.fixture_control)

        unknown_row = copy.deepcopy(self.plan)
        unknown_row["observations"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(unknown_row)
        with self.assertRaises(Stage2Error):
            validate_plan(unknown_row, self.generator, self.fixture_control)

        with self.assertRaises(Stage2Error):
            validate_observations(self.observations, unknown_row, self.fixture_control)

        rewritten_generator_binding = copy.deepcopy(self.plan)
        rewritten_generator_binding["generator_manifest_sha256"] = "0" * 64
        rehash(rewritten_generator_binding)
        with self.assertRaises(Stage2Error):
            derive_calibration_result(
                copy.deepcopy(self.observations),
                rewritten_generator_binding,
                self.fixture_control,
                generator_manifest=self.generator,
                repo_root=self.repo_root,
            )

        nonderived_id_plan = copy.deepcopy(self.plan)
        nonderived_id_rows = copy.deepcopy(self.observations)
        replacement = "s2obs_" + "0" * 24
        if any(
            row["observation_id"] == replacement
            for row in nonderived_id_plan["observations"]
        ):
            replacement = "s2obs_" + "f" * 24
        nonderived_id_plan["observations"][0]["observation_id"] = replacement
        rehash(nonderived_id_plan)
        nonderived_id_rows[0]["observation_id"] = replacement
        rehash_observation(nonderived_id_rows[0])
        with self.assertRaises(Stage2Error):
            derive_calibration_result(
                nonderived_id_rows,
                nonderived_id_plan,
                self.fixture_control,
                generator_manifest=self.generator,
                repo_root=self.repo_root,
            )

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
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        self.assertEqual(result["state"], "FIXTURE_CONFORMANCE_ONLY")
        self.assertFalse(result["stage2_frozen"])
        self.assertEqual(result["candidate_thresholds"], {})
        self._validate_result(result)

    def test_10_fixture_cannot_claim_frozen(self) -> None:
        result = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        result["stage2_frozen"] = True
        rehash(result)
        with self.assertRaises(Stage2Error):
            self._validate_result(result)

    def test_11_fixture_cannot_retain_thresholds(self) -> None:
        result = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        result["candidate_thresholds"] = {"fabricated": 1.0}
        rehash(result)
        with self.assertRaises(Stage2Error):
            self._validate_result(result)

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
        rows[0]["observed_checksum"] = "0" * CHECKSUM_HEX_LENGTH
        rows[0]["accepted"] = True
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_20_unbound_and_unknown_control_manifest_properties_refuse(self) -> None:
        template = empirical_control_template()
        with self.assertRaises(Stage2Error):
            validate_control_manifest(template, require_bound_empirical=True)
        with self.assertRaises(Stage2Error):
            bind_empirical_control_manifest(template)

        ready = self._empirical_template_with_digests()
        variants = []

        unknown_manifest = copy.deepcopy(ready)
        unknown_manifest["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        variants.append(unknown_manifest)

        unknown_control = copy.deepcopy(ready)
        unknown_control["controls"][0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        variants.append(unknown_control)

        unknown_identity = copy.deepcopy(ready)
        unknown_identity["controls"][0]["identity"]["notes"] = (
            "PRIVATE_TRANSCRIPT_CANARY"
        )
        variants.append(unknown_identity)

        for variant in variants:
            with self.subTest(unexpected_path=True):
                with self.assertRaises(Stage2Error):
                    bind_empirical_control_manifest(variant)

        bound = bind_empirical_control_manifest(ready)
        bound["controls"][0]["identity"]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        bound["controls"][0]["identity_sha256"] = sha256_object(
            bound["controls"][0]["identity"]
        )
        rehash(bound)
        with self.assertRaises(Stage2Error):
            validate_control_manifest(bound, require_bound_empirical=True)

        wrong_join = self._empirical_template_with_digests()
        wrong_join["stage1_join_head"] = "f" * 40
        with self.assertRaises(Stage2Error):
            bind_empirical_control_manifest(wrong_join)

        wrong_repository = self._empirical_template_with_digests()
        wrong_repository["controls"][0]["identity"]["source_repository"] = (
            "attacker/substitute-control"
        )
        with self.assertRaises(Stage2Error):
            bind_empirical_control_manifest(wrong_repository)

        wrong_commit = self._empirical_template_with_digests()
        wrong_commit["controls"][0]["identity"]["source_commit_sha1"] = "1" * 40
        with self.assertRaises(Stage2Error):
            bind_empirical_control_manifest(wrong_commit)

    def test_21_overlapping_empirical_envelopes_are_inconclusive(self) -> None:
        bound, plan, rows = self._bound_empirical_rows()
        for row in rows:
            row["latency_ms"] = 1000.0
            row["ttft_ms"] = 250.0 if row["effort"] == "low" else 300.0
            rehash_observation(row)
        result = derive_calibration_result(
            rows,
            plan,
            bound,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        self.assertEqual(result["state"], "CALIBRATION_INCONCLUSIVE")
        self.assertFalse(result["stage2_frozen"])
        self.assertEqual(result["candidate_thresholds"], {})

    def test_22_stage1_blob_verifier_is_crlf_portable_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_git(root, "init")
            run_git(root, "config", "user.email", "stage2@example.invalid")
            run_git(root, "config", "user.name", "Stage2 Test")
            run_git(root, "config", "core.autocrlf", "false")
            path = root / "frozen.txt"
            path.write_bytes(b"exact frozen bytes\n")
            run_git(root, "add", "frozen.txt")
            run_git(root, "commit", "-m", "freeze")
            expected = run_git(root, "rev-parse", "HEAD:frozen.txt").stdout.strip()
            run_git(root, "config", "core.autocrlf", "true")
            path.write_bytes(b"exact frozen bytes\r\n")
            self.assertEqual(run_git(root, "diff", "--quiet", check=False).returncode, 0)
            original_blobs = contracts.STAGE1_BLOBS
            original_join = contracts.STAGE1_JOIN_HEAD
            try:
                contracts.STAGE1_BLOBS = {"frozen.txt": expected}
                contracts.STAGE1_JOIN_HEAD = run_git(root, "rev-parse", "HEAD").stdout.strip()
                self.assertEqual(verify_stage1_blobs(root)["frozen.txt"], expected)
                path.write_bytes(b"mutated\r\n")
                with self.assertRaises(Stage2Error):
                    verify_stage1_blobs(root)
            finally:
                contracts.STAGE1_BLOBS = original_blobs
                contracts.STAGE1_JOIN_HEAD = original_join

    def test_23_unknown_observation_property_refuses(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

    def test_24_one_correctly_marked_wrong_answer_refuses_empirical_candidate(self) -> None:
        bound, plan, rows = self._bound_empirical_rows()
        baseline = derive_calibration_result(
            rows,
            plan,
            bound,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        self.assertEqual(baseline["state"], "EMPIRICAL_CALIBRATION_CANDIDATE")
        expected_checksum = plan["observations"][0]["expected_checksum"]
        rows[0]["observed_checksum"] = "0" * CHECKSUM_HEX_LENGTH
        if rows[0]["observed_checksum"] == expected_checksum:
            rows[0]["observed_checksum"] = "f" * CHECKSUM_HEX_LENGTH
        rows[0]["accepted"] = False
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            derive_calibration_result(
                rows,
                plan,
                bound,
                generator_manifest=self.generator,
                repo_root=self.repo_root,
            )

    def test_25_every_derivation_invokes_stage1_custody(self) -> None:
        with patch(
            "astra_stage2.calibration.verify_stage1_blobs",
            side_effect=Stage2Error("forced Stage 1 custody failure"),
        ):
            with self.assertRaises(Stage2Error):
                derive_calibration_result(
                    self.observations,
                    self.plan,
                    self.fixture_control,
                    generator_manifest=self.generator,
                    repo_root=self.repo_root,
                )

    def test_26_result_binds_exact_stage1_blob_set(self) -> None:
        result = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        self.assertEqual(result["stage1_custody"]["status"], "VERIFIED")
        self.assertEqual(result["stage1_custody"]["blobs"], contracts.STAGE1_BLOBS)
        self.assertEqual(result["stage1_join_head"], contracts.STAGE1_JOIN_HEAD)
        self.assertEqual(
            result["generator_manifest_sha256"], self.generator["payload_sha256"]
        )
        self.assertEqual(result["plan_sha256"], self.plan["payload_sha256"])
        self.assertEqual(
            result["control_manifest_sha256"],
            self.fixture_control["payload_sha256"],
        )
        self._validate_result(result)

    def test_27_unknown_calibration_result_property_refuses(self) -> None:
        result = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        result["notes"] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(result)
        with self.assertRaises(Stage2Error):
            self._validate_result(result)

        nested_unknown = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        nested_unknown["envelopes"]["lotus_3b_recurrent"]["r_elasticity"][
            "notes"
        ] = "PRIVATE_TRANSCRIPT_CANARY"
        rehash(nested_unknown)
        with self.assertRaises(Stage2Error):
            self._validate_result(nested_unknown)

        valid = derive_calibration_result(
            self.observations,
            self.plan,
            self.fixture_control,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        with self.assertRaises(Stage2Error):
            validate_calibration_result(valid)

        changed_rows = copy.deepcopy(self.observations)
        changed_rows[0]["latency_ms"] += 1.0
        rehash_observation(changed_rows[0])
        with self.assertRaises(Stage2Error):
            self._validate_result(valid, rows=changed_rows)

        bound, plan, rows = self._bound_empirical_rows()
        fabricated = derive_calibration_result(
            rows,
            plan,
            bound,
            generator_manifest=self.generator,
            repo_root=self.repo_root,
        )
        fabricated["candidate_thresholds"] = {"fabricated": 999.0}
        fabricated["separation_checks"] = []
        fabricated["envelopes"] = {}
        rehash(fabricated)
        with self.assertRaises(Stage2Error):
            self._validate_result(fabricated, control=bound, plan=plan, rows=rows)


    def test_28_request_renderer_is_fixed_answer_hidden_and_bound(self) -> None:
        prompts = []
        for case in self.generator["cases"]:
            task = reconstruct_task(case)
            prompt = render_task_prompt(task)
            prompts.append(prompt)
            self.assertEqual(hashlib.sha256(prompt).hexdigest(), case["request_sha256"])
            self.assertEqual(len(prompt), case["request_bytes"])
            self.assertEqual(len(task["expected_checksum"]), CHECKSUM_HEX_LENGTH)
            mutated = copy.deepcopy(task)
            mutated["expected_checksum"] = "f" * CHECKSUM_HEX_LENGTH
            self.assertEqual(render_task_prompt(mutated), prompt)
            prompt.decode("ascii")
        self.assertEqual(len({len(prompt) for prompt in prompts}), 1)

    def test_29_blocked_order_is_complete_and_request_projection_is_exact(self) -> None:
        blocks = {}
        cases = {case["case_id"]: case for case in self.generator["cases"]}
        for row in self.plan["observations"]:
            blocks.setdefault(row["block_id"], set()).add(row["order_index"])
            case = cases[row["case_id"]]
            self.assertEqual(row["request_sha256"], case["request_sha256"])
            self.assertEqual(row["request_bytes"], case["request_bytes"])
        self.assertEqual(len(blocks), 72)
        self.assertTrue(all(order == set(range(9)) for order in blocks.values()))

    def test_30_observation_request_and_backend_evidence_fail_closed(self) -> None:
        rows = copy.deepcopy(self.observations)
        rows[0]["request_sha256"] = "0" * 64
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

        rows = copy.deepcopy(self.observations)
        rows[1]["request_id_sha256"] = rows[0]["request_id_sha256"]
        rehash_observation(rows[1])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

        rows = copy.deepcopy(self.observations)
        block = rows[0]["block_id"]
        peer = next(index for index, row in enumerate(rows[1:], 1) if row["block_id"] == block)
        rows[peer]["backend_fingerprint_sha256"] = "a" * 64
        rehash_observation(rows[peer])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)

        rows = copy.deepcopy(self.observations)
        rows[0]["final_token_ns"] = rows[0]["request_start_ns"] - 1
        rehash_observation(rows[0])
        with self.assertRaises(Stage2Error):
            validate_observations(rows, self.plan, self.fixture_control)


if __name__ == "__main__":
    unittest.main(verbosity=2)
