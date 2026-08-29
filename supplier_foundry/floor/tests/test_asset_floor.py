from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("asset_floor", ROOT / "asset_floor.py")
asset_floor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(asset_floor)


class AssetFloorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = asset_floor.load_json(ROOT / "catalog.json")
        self.valve = asset_floor.load_json(ROOT / "examples/underdrain-valve.asset-intent.json")
        self.toad = asset_floor.load_json(ROOT / "examples/underdrain-boss-toad.asset-intent.json")

    def test_catalog_and_examples_validate(self) -> None:
        indexes = asset_floor.validate_catalog(self.catalog)
        self.assertGreaterEqual(len(indexes["capabilities"]), 20)
        self.assertGreaterEqual(len(indexes["gaps"]), 15)
        self.assertTrue(asset_floor.validate_intent(self.valve, self.catalog).startswith("assetint1_"))
        self.assertTrue(asset_floor.validate_intent(self.toad, self.catalog).startswith("assetint1_"))

    def test_identity_is_order_independent(self) -> None:
        reversed_intent = dict(reversed(list(self.valve.items())))
        reversed_intent["style"] = dict(reversed(list(reversed_intent["style"].items())))
        self.assertEqual(
            asset_floor.digest("assetint1", self.valve, omitted_keys={"intentId"}),
            asset_floor.digest("assetint1", reversed_intent, omitted_keys={"intentId"}),
        )

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicate.json"
            path.write_text('{"format":"x","format":"y"}', encoding="utf-8")
            with self.assertRaises(asset_floor.ContractError):
                asset_floor.load_json(path)

    def test_floats_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "float.json"
            path.write_text('{"value":0.25}', encoding="utf-8")
            with self.assertRaises(asset_floor.ContractError):
                asset_floor.load_json(path)

    def test_supplier_cannot_acquire_authority(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["suppliers"][0]["authority"]["selection"] = "provider"
        with self.assertRaises(asset_floor.ContractError):
            asset_floor.validate_catalog(catalog)

    def test_intent_cannot_name_a_provider(self) -> None:
        intent = copy.deepcopy(self.valve)
        intent["provider"] = "provider.trellis2"
        intent["intentId"] = asset_floor.digest("assetint1", intent, omitted_keys={"intentId"})
        with self.assertRaises(asset_floor.ContractError):
            asset_floor.validate_intent(intent, self.catalog)

    def test_interaction_must_reference_a_declared_part(self) -> None:
        intent = copy.deepcopy(self.valve)
        intent["gameplay"]["interactions"][0]["partId"] = "part.not-present"
        intent["intentId"] = asset_floor.digest("assetint1", intent, omitted_keys={"intentId"})
        with self.assertRaises(asset_floor.ContractError):
            asset_floor.validate_intent(intent, self.catalog)

    def test_required_gate_set_cannot_be_shrunk(self) -> None:
        intent = copy.deepcopy(self.toad)
        intent["acceptance"]["requiredGates"] = intent["acceptance"]["requiredGates"][:-1]
        intent["intentId"] = asset_floor.digest("assetint1", intent, omitted_keys={"intentId"})
        with self.assertRaises(asset_floor.ContractError):
            asset_floor.validate_intent(intent, self.catalog)

    def _qualification(self, intent: dict, default_state: str = "pass") -> dict:
        gates = []
        for gate_id in intent["acceptance"]["requiredGates"]:
            gates.append({
                "id": gate_id,
                "state": default_state,
                "evidenceRefs": [f"receipt:{gate_id}"] if default_state == "pass" else [],
                "limits": [],
            })
        return {
            "format": asset_floor.QUALIFICATION_FORMAT,
            "qualificationId": None,
            "intentId": intent["intentId"],
            "authority": "evidence_only",
            "aggregateScore": None,
            "gates": gates,
        }

    def test_hard_gate_failure_blocks_high_other_results(self) -> None:
        qualification = self._qualification(self.valve)
        # The valve profile uses gameplay_semantics as a hard gate.
        # which is hard and cannot be averaged away.
        row = next(row for row in qualification["gates"] if row["id"] == "gameplay_semantics")
        row["state"] = "fail"
        row["evidenceRefs"] = ["receipt:gameplay_semantics-failure"]
        disposition = asset_floor.classify_qualification(qualification, self.valve, self.catalog)
        self.assertEqual(disposition["disposition"], "rejected")
        self.assertEqual(disposition["failedGates"], ["gameplay_semantics"])

    def test_open_gate_holds_and_warning_restricts_to_pilot(self) -> None:
        qualification = self._qualification(self.valve)
        human = next(row for row in qualification["gates"] if row["id"] == "human_acceptance")
        human["state"] = "open"
        human["evidenceRefs"] = []
        self.assertEqual(
            asset_floor.classify_qualification(qualification, self.valve, self.catalog)["disposition"],
            "held",
        )

        qualification = self._qualification(self.valve)
        style = next(row for row in qualification["gates"] if row["id"] == "style_consistency")
        style["state"] = "warn"
        style["evidenceRefs"] = ["receipt:style-warning"]
        self.assertEqual(
            asset_floor.classify_qualification(qualification, self.valve, self.catalog)["disposition"],
            "pilot_only",
        )

    def test_all_gates_plus_human_acceptance_are_required_for_product_acceptance(self) -> None:
        qualification = self._qualification(self.valve)
        disposition = asset_floor.classify_qualification(qualification, self.valve, self.catalog)
        self.assertEqual(disposition["disposition"], "product_accepted")
        self.assertEqual(disposition["authority"], "classification_only")

    def test_report_keeps_gaps_and_supplier_coverage_separate(self) -> None:
        report = asset_floor.compile_report(self.catalog, [self.valve, self.toad])
        self.assertEqual(report["format"], asset_floor.REPORT_FORMAT)
        self.assertEqual(report["authority"], "measurement_only")
        self.assertNotIn("readinessScore", report)
        gap_ids = {row["id"] for row in report["gaps"]}
        self.assertIn("gap.style-family-consistency", gap_ids)
        self.assertIn("gap.gameplay-readability", gap_ids)
        self.assertIn("asset.validate.visual/v1", report["coverage"]["noQualifiedProviderCapabilities"])

    def test_catalog_identity_reconstructs(self) -> None:
        expected = asset_floor.digest("assetfloor1", self.catalog, omitted_keys={"catalogId"})
        self.assertEqual(self.catalog["catalogId"], expected)


if __name__ == "__main__":
    unittest.main()
