from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from estate_lab.commodities import (
    build_acquisition_plan,
    derived_catalog_id,
    load_commodity_catalog,
    render_acquisition_plan_markdown,
    select_candidates,
    write_acquisition_plan,
)
from estate_lab.errors import CommodityCatalogError

HERE = Path(__file__).resolve().parents[1]
CATALOG_PATH = HERE / "fixtures" / "commodities.example.json"


class CommodityCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_commodity_catalog(CATALOG_PATH)

    def test_catalog_is_substantial_and_cross_domain(self) -> None:
        self.assertGreaterEqual(len(self.catalog.candidates), 80)
        self.assertGreaterEqual(len({item.category for item in self.catalog.candidates}), 25)
        self.assertEqual(
            {item.decision for item in self.catalog.candidates},
            {"consume", "adapt", "reference", "reject"},
        )

    def test_catalog_identity_is_content_derived(self) -> None:
        self.assertEqual(self.catalog.catalog_id, derived_catalog_id(self.catalog.raw))

    def test_consume_candidates_are_open_and_substitutable(self) -> None:
        rows = select_candidates(self.catalog, decisions=["consume"])
        self.assertGreaterEqual(len(rows), 18)
        for item in rows:
            self.assertIn(item.license_posture, {"permissive", "standard"})
            self.assertIsNotNone(item.substitution_test)
            self.assertIsNone(item.required_adapter)

    def test_adapt_candidates_name_adapter_and_ripout_test(self) -> None:
        rows = select_candidates(self.catalog, decisions=["adapt"])
        self.assertGreaterEqual(len(rows), 35)
        for item in rows:
            self.assertIsNotNone(item.required_adapter)
            self.assertIsNotNone(item.substitution_test)
            self.assertTrue(item.authority_exclusions)

    def test_priority_and_target_projection(self) -> None:
        rows = select_candidates(
            self.catalog,
            decisions=["consume", "adapt"],
            priorities=["P0"],
            targets=["axm-embodied"],
        )
        self.assertTrue(rows)
        self.assertTrue(all(item.priority == "P0" for item in rows))
        self.assertTrue(all("axm-embodied" in item.estate_targets for item in rows))
        self.assertIn("tinyusb", {item.candidate_id for item in rows})

    def test_plan_counts_match_selection(self) -> None:
        rows = select_candidates(self.catalog, categories=["hardware-in-loop"])
        plan = build_acquisition_plan(self.catalog, rows)
        self.assertEqual(plan["candidate_count"], len(rows))
        self.assertEqual(sum(plan["counts_by_decision"].values()), len(rows))
        self.assertEqual(plan["counts_by_category"], {"hardware-in-loop": len(rows)})

    def test_markdown_and_json_exports_are_deterministic(self) -> None:
        plan = build_acquisition_plan(self.catalog)
        first = render_acquisition_plan_markdown(plan)
        second = render_acquisition_plan_markdown(plan)
        self.assertEqual(first, second)
        self.assertIn("# AXM commodity acquisition plan", first)
        self.assertIn("## Control question", first)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            md_path = root / "plan.md"
            json_path = root / "plan.json"
            write_acquisition_plan(md_path, plan, markdown=True)
            write_acquisition_plan(json_path, plan, markdown=False)
            self.assertEqual(md_path.read_text(encoding="utf-8"), first)
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, plan)

    def test_public_floor_standards_are_encoded(self) -> None:
        ids = {item.candidate_id for item in self.catalog.candidates}
        for candidate_id in (
            "cloudevents",
            "asyncapi",
            "w3c-trace-context",
            "wasm-component-model",
            "oci-artifact-specs",
            "slsa",
            "spdx",
            "cyclonedx",
            "model-context-protocol",
            "agent2agent",
            "json-schema-2020-12",
        ):
            self.assertIn(candidate_id, ids)

    def test_catalog_refuses_identity_drift(self) -> None:
        raw = copy.deepcopy(self.catalog.raw)
        raw["candidates"][0]["decision_basis"] += " changed"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CommodityCatalogError):
                load_commodity_catalog(path)

    def test_catalog_refuses_consume_under_copyleft(self) -> None:
        raw = copy.deepcopy(self.catalog.raw)
        row = next(item for item in raw["candidates"] if item["id"] == "tinyusb")
        row["license_posture"] = "strong-copyleft"
        raw["catalog_id"] = derived_catalog_id(raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CommodityCatalogError):
                load_commodity_catalog(path)

    def test_catalog_refuses_unbounded_adapter(self) -> None:
        raw = copy.deepcopy(self.catalog.raw)
        row = next(item for item in raw["candidates"] if item["decision"] == "adapt")
        row["required_adapter"] = None
        raw["catalog_id"] = derived_catalog_id(raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CommodityCatalogError):
                load_commodity_catalog(path)

    def test_catalog_refuses_supplier_without_authority_exclusions(self) -> None:
        raw = copy.deepcopy(self.catalog.raw)
        raw["candidates"][0]["authority_exclusions"] = []
        raw["catalog_id"] = derived_catalog_id(raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "catalog.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CommodityCatalogError):
                load_commodity_catalog(path)


if __name__ == "__main__":
    unittest.main()
