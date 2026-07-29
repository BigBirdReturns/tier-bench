from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("action_player_floor", ROOT / "floor.py")
assert SPEC and SPEC.loader
floor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(floor)


class ActionPlayerFloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = floor.load_json(ROOT / "catalog.json")
        cls.intent = floor.load_json(ROOT / "examples" / "underdrain.player-intent.json")
        cls.witnesses = floor.load_json(ROOT / "examples" / "negative-witnesses.json")
        cls.changes = floor.load_json(ROOT / "examples" / "change-proposals.json")
        cls.expected_report = floor.load_json(ROOT / "examples" / "floor-report.json")

    def test_worked_floor_validates(self) -> None:
        indexes = floor.validate_catalog(self.catalog)
        self.assertEqual(len(indexes["gates"]), 23)
        self.assertEqual(len(indexes["driftClasses"]), 15)
        self.assertEqual(floor.validate_intent(self.intent, self.catalog), self.intent["intentId"])
        self.assertEqual(
            [floor.validate_witness(value, self.catalog) for value in self.witnesses],
            [value["witnessId"] for value in self.witnesses],
        )
        self.assertEqual(
            [floor.validate_change(value) for value in self.changes],
            [value["changeId"] for value in self.changes],
        )

    def test_report_reconstructs_byte_for_byte(self) -> None:
        actual = floor.build_report(self.catalog, [self.intent], self.witnesses, self.changes)
        self.assertEqual(actual, self.expected_report)
        self.assertIsNone(actual["aggregateReadinessScore"])
        self.assertFalse(actual["coverage"]["productAccepted"])
        self.assertEqual(actual["counts"]["qualifiedCommodityCells"], 0)

    def test_canonical_identity_ignores_key_order(self) -> None:
        reordered = dict(reversed(list(self.intent.items())))
        self.assertEqual(
            floor.digest("playerintent1", self.intent, {"intentId"}),
            floor.digest("playerintent1", reordered, {"intentId"}),
        )

    def test_duplicate_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"format":"x","format":"y"}', encoding="utf-8")
            with self.assertRaises(floor.ContractError):
                floor.load_json(path)

    def test_floats_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "float.json"
            path.write_text('{"value":0.5}', encoding="utf-8")
            with self.assertRaises(floor.ContractError):
                floor.load_json(path)

    def test_provider_cannot_enter_player_intent(self) -> None:
        value = copy.deepcopy(self.intent)
        value["provider"] = "Cinemachine"
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "provider-specific"):
            floor.validate_intent(value, self.catalog)

    def test_mandatory_mechanic_must_follow_teach_and_practice(self) -> None:
        value = copy.deepcopy(self.intent)
        value["mechanicLearning"] = [
            value["mechanicLearning"][2],
            value["mechanicLearning"][0],
            value["mechanicLearning"][1],
        ]
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "order"):
            floor.validate_intent(value, self.catalog)

    def test_master_requires_alternate_completion(self) -> None:
        value = copy.deepcopy(self.intent)
        master = next(row for row in value["mechanicLearning"] if row["id"] == "master")
        del master["alternateCompletionPolicy"]
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "alternateCompletionPolicy"):
            floor.validate_intent(value, self.catalog)

    def test_runtime_and_author_cannot_self_accept(self) -> None:
        value = copy.deepcopy(self.intent)
        value["acceptance"]["runtimeMayIssueHumanReceipt"] = True
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "runtime may not"):
            floor.validate_intent(value, self.catalog)

        value = copy.deepcopy(self.intent)
        value["acceptance"]["authorMaySelfAccept"] = True
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "self-accept"):
            floor.validate_intent(value, self.catalog)

    def test_change_owner_is_derived_from_touches(self) -> None:
        value = copy.deepcopy(self.changes[0])
        value["proposedOwner"] = "world"
        value["changeId"] = floor.digest("playerchange1", value, {"changeId"})
        with self.assertRaisesRegex(floor.ContractError, "must be 'arc'"):
            floor.validate_change(value)

    def test_cross_organ_change_requires_exact_subtasks(self) -> None:
        value = copy.deepcopy(self.changes[2])
        value["subtasks"] = value["subtasks"][:-1]
        value["changeId"] = floor.digest("playerchange1", value, {"changeId"})
        with self.assertRaisesRegex(floor.ContractError, "do not match"):
            floor.validate_change(value)

    def test_parallel_runtime_witness_remains_required(self) -> None:
        names = {row["name"] for row in self.witnesses}
        self.assertIn("witness.parallel-shine-runtime", names)
        witness = next(row for row in self.witnesses if row["name"] == "witness.parallel-shine-runtime")
        self.assertIn("drift.parallel-runtime", witness["expectedDriftClasses"])
        self.assertIn("do not call the build Arc-accepted", witness["requiredRefusal"])

    def test_fixture_as_product_witness_preserves_conformance_value(self) -> None:
        witness = next(row for row in self.witnesses if row["name"] == "witness.primitive-fixture-as-product")
        self.assertIn("does not invalidate its deterministic conformance evidence", witness["evidenceLimit"])

    def test_unknown_gate_is_refused(self) -> None:
        value = copy.deepcopy(self.intent)
        value["requiredGates"].append("gate.imaginary")
        value["intentId"] = floor.digest("playerintent1", value, {"intentId"})
        with self.assertRaisesRegex(floor.ContractError, "unknown gate"):
            floor.validate_intent(value, self.catalog)


if __name__ == "__main__":
    unittest.main()
