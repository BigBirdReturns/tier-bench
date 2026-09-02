"""Provider-free qualification for the HALO3 Cell Zero observation floor."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tier_runner.halo3_cell_common import Halo3Error, canonical_bytes, load_json
from tier_runner.halo3_cell_observation import (
    compile_activation,
    compile_ledger,
    admit_observation,
    seal_candidate,
    seal_grade,
    validate_activation,
    validate_candidate,
    validate_grade,
    validate_observation,
)
from tier_runner.halo3_cell_plan import compile_plan


LAB = ROOT / "labs" / "halo3-cell-zero" / "lab.json"
FINGERPRINT = ROOT / "labs" / "halo3-cell-zero" / "model_fingerprint_contract.json"


def digest(character: str) -> str:
    return character * 64


def identity_value(field: str):
    if field == "shard-sha256s":
        return [digest("1"), digest("2")]
    if field.endswith("-sha256"):
        return digest("3")
    if field == "latency-ms":
        return 100
    if field == "observed-cost-usd":
        return 0.25
    if field == "hardware-binding":
        return "host-a/gpu-0"
    if field == "source-commit":
        return "commit-" + "4" * 40
    return f"value-{field}"


def evidence_for(activation, *, producer_id: str, independent: bool = True):
    rows = []
    for index, receipt_id in enumerate(activation["required_receipt_ids"]):
        observer = "evidence-node"
        observer_kind = "controller"
        kind = "receipt"
        if any(
            token in receipt_id
            for token in (
                "human",
                "bind-event",
                "role-handoff",
                "custody-transfer",
                "human-decode",
            )
        ):
            observer = "operator"
            observer_kind = "human"
            kind = "human-event"
        elif "physical" in receipt_id or "outcome" in receipt_id:
            observer = "sensor-witness"
            observer_kind = "sensor"
            kind = "physical-outcome"
        rows.append(
            {
                "id": receipt_id,
                "kind": kind,
                "sha256": f"{index + 1:064x}",
                "observer": producer_id if not independent else observer,
                "observer_kind": observer_kind,
                "independent": independent,
                "uri": None,
            }
        )
    return rows


def metrics_for(activation, *, accepted: bool = True):
    metrics = {item: 0 for item in activation["required_metrics"]}
    if activation["cell_class"] == "fingerprint":
        metrics["accepted"] = int(accepted)
        metrics["consequential-miss"] = 0
        metrics["critical-escaped-defects"] = 0
    else:
        metrics["accepted-products"] = int(accepted)
        metrics["consequential-misses"] = 0
    return metrics


def candidate_payload(activation, *, accepted: bool = True, independent: bool = True):
    if activation["cell_class"] == "fingerprint":
        producer_id = activation["model_id"]
        producer_kind = (
            "controller" if producer_id == "deterministic-control" else "model"
        )
    else:
        producer_id = "range-executor"
        producer_kind = "system"
    return {
        "producer": {
            "id": producer_id,
            "kind": producer_kind,
            "authority": "candidate_only",
        },
        "identity": {
            field: identity_value(field)
            for field in activation["required_identity_fields"]
        },
        "trial_count": activation["minimum_trials"],
        "task_input_sha256": digest("5"),
        "candidate_output_sha256": digest("6"),
        "metrics": metrics_for(activation, accepted=accepted),
        "outcomes": {"product": "bounded-candidate"},
        "evidence": evidence_for(
            activation,
            producer_id=producer_id,
            independent=independent,
        ),
        "production_claim": False,
    }


def grade_payload(activation, *, verdict: str = "accepted"):
    return {
        "grader": {
            "id": "evidence-node",
            "kind": "controller",
            "source_sha256": digest("7"),
            "independent": True,
        },
        "hidden_fixture_sha256": digest("8"),
        "verdict": verdict,
        "reasons": ["controller-owned hidden acceptance evaluated"],
        "evaluated_receipt_ids": activation["required_receipt_ids"],
        "production_claim": False,
    }


def admitted(plan, activation, *, verdict: str = "accepted", accepted: bool = True):
    candidate = seal_candidate(
        activation,
        candidate_payload(activation, accepted=accepted),
    )
    grade = seal_grade(
        activation,
        candidate,
        grade_payload(activation, verdict=verdict),
    )
    return admit_observation(plan, activation, candidate, grade)


class Halo3ObservationFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = compile_plan(load_json(LAB), load_json(FINGERPRINT))
        cls.fable_cell = next(
            row
            for row in cls.plan["fingerprint_cells"]
            if row["model_id"] == "fable"
            and row["family_id"] == "orchestration"
            and row["condition_id"] == "baseline"
        )
        cls.kimi_cell = next(
            row
            for row in cls.plan["fingerprint_cells"]
            if row["model_id"] == "kimi3"
            and row["family_id"] == "physical-world-synthesis"
            and row["condition_id"] == "degraded"
        )
        cls.physical_stage = next(
            row
            for row in cls.plan["stage_cells"]
            if row["stage_id"] == "stage-020-single-node"
        )

    def test_activation_is_deterministic_and_hides_acceptance_text(self):
        first = compile_activation(self.plan, self.fable_cell["cell_id"])
        second = compile_activation(self.plan, self.fable_cell["cell_id"])
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(validate_activation(self.plan, first), first)
        rendered = json.dumps(first, sort_keys=True)
        self.assertNotIn(self.fable_cell["hidden_acceptance"], rendered)
        self.assertIn("acceptance_contract_sha256", first)
        self.assertEqual(first["identity_mode"], "provider_observational")

    def test_fable_candidate_and_grade_admit(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        observation = admitted(self.plan, activation)
        self.assertEqual(observation["status"], "accepted")
        self.assertEqual(observation["model_id"], "fable")
        self.assertEqual(validate_observation(self.plan, observation), observation)
        self.assertFalse(observation["production_claim"])
        self.assertFalse(observation["promotion_authorized"])

    def test_kimi_identity_requires_exact_digest_fields(self):
        activation = compile_activation(self.plan, self.kimi_cell["cell_id"])
        payload = candidate_payload(activation)
        payload["identity"]["config-sha256"] = "not-a-digest"
        with self.assertRaises(Halo3Error):
            seal_candidate(activation, payload)

    def test_missing_provider_identity_is_refused(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        payload = candidate_payload(activation)
        payload["identity"].pop("provider-request-id")
        with self.assertRaises(Halo3Error):
            seal_candidate(activation, payload)

    def test_candidate_cannot_add_status_or_self_acceptance(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        payload = candidate_payload(activation)
        payload["status"] = "accepted"
        with self.assertRaises(Halo3Error):
            seal_candidate(activation, payload)

    def test_score_fields_are_refused_at_any_depth(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        payload = candidate_payload(activation)
        payload["outcomes"]["score"] = 0.99
        with self.assertRaises(Halo3Error):
            seal_candidate(activation, payload)

    def test_minimum_trials_is_enforced(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        payload = candidate_payload(activation)
        payload["trial_count"] = activation["minimum_trials"] - 1
        with self.assertRaises(Halo3Error):
            seal_candidate(activation, payload)

    def test_grade_is_bound_to_exact_candidate(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        candidate = seal_candidate(activation, candidate_payload(activation))
        grade = seal_grade(activation, candidate, grade_payload(activation))
        changed = copy.deepcopy(candidate)
        changed["candidate_output_sha256"] = digest("9")
        with self.assertRaises(Halo3Error):
            validate_grade(activation, changed, grade)
        self.assertEqual(validate_candidate(activation, candidate), candidate)

    def test_physical_acceptance_requires_independent_outcome(self):
        activation = compile_activation(self.plan, self.physical_stage["cell_id"])
        payload = candidate_payload(activation, independent=False)
        candidate = seal_candidate(activation, payload)
        grade = seal_grade(activation, candidate, grade_payload(activation))
        with self.assertRaises(Halo3Error):
            admit_observation(self.plan, activation, candidate, grade)

    def test_human_owned_receipt_remains_human_attributed(self):
        activation = compile_activation(self.plan, self.physical_stage["cell_id"])
        payload = candidate_payload(activation)
        for row in payload["evidence"]:
            if row["id"] == "receipt-human-authority":
                row["observer"] = "evidence-node"
                row["observer_kind"] = "controller"
        candidate = seal_candidate(activation, payload)
        grade = seal_grade(activation, candidate, grade_payload(activation))
        with self.assertRaises(Halo3Error):
            admit_observation(self.plan, activation, candidate, grade)

    def test_refusal_is_preserved_without_becoming_acceptance(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        observation = admitted(
            self.plan,
            activation,
            verdict="refused",
            accepted=False,
        )
        self.assertEqual(observation["status"], "refused")
        self.assertEqual(observation["metrics"]["accepted"], 0)
        self.assertEqual(validate_observation(self.plan, observation), observation)

    def test_ledger_preserves_exact_denominator_without_ranking(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        observation = admitted(self.plan, activation)
        ledger = compile_ledger(self.plan, [observation])
        self.assertEqual(ledger["coverage"]["total_cells"], 66)
        self.assertEqual(ledger["coverage"]["measured_cells"], 1)
        self.assertEqual(ledger["coverage"]["accepted_cells"], 1)
        self.assertEqual(ledger["coverage"]["unmeasured_cells"], 65)
        self.assertFalse(ledger["complete"])
        rendered = json.dumps(ledger, sort_keys=True)
        self.assertNotIn('"score"', rendered)
        self.assertNotIn("aggregate_score", rendered)

    def test_conflicting_observations_for_one_cell_are_refused(self):
        activation = compile_activation(self.plan, self.fable_cell["cell_id"])
        first = admitted(self.plan, activation)
        payload = candidate_payload(activation)
        payload["candidate_output_sha256"] = digest("a")
        second_candidate = seal_candidate(activation, payload)
        second_grade = seal_grade(
            activation,
            second_candidate,
            grade_payload(activation),
        )
        second = admit_observation(
            self.plan,
            activation,
            second_candidate,
            second_grade,
        )
        with self.assertRaises(Halo3Error):
            compile_ledger(self.plan, [first, second])

    def test_unknown_cell_fails_closed(self):
        with self.assertRaises(Halo3Error):
            compile_activation(self.plan, "halo3fingerprint1_" + "f" * 64)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Halo3ObservationFloorTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(
        f"HALO3 OBSERVATION FLOOR TESTS PASS: "
        f"{result.testsRun}/{result.testsRun}"
    )
