from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "migration" / "axm-arc-execution-train-v1" / "verify_migration.py"
spec = importlib.util.spec_from_file_location("execution_migration", MODULE_PATH)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

class ExecutionMigrationTests(unittest.TestCase):
    def test_static_stage_passes(self):
        result = migration.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_head_count"], 3)
        self.assertFalse(result["source_code_imported"])
        self.assertFalse(result["destination_qualified"])

    def test_exact_product_donor(self):
        data = migration.load_strict(migration.FILES["source"])
        rows = {row["name"]: row for row in data["heads"]}
        self.assertEqual(rows["execution-product"]["commit"], "202fd8cfb03ec038ae0da2bfedb0bc5727b12e7d")
        self.assertEqual(rows["execution-product"]["pr"], 294)

    def test_loopback_is_v2_published(self):
        data = migration.load_strict(migration.FILES["source"])
        row = next(row for row in data["heads"] if row["name"] == "loopback-credential-service")
        self.assertEqual(row["terminal_receipt"], "ASOIAF_LOOPBACK_TLS_TERMINAL_RECEIPT_V2")
        self.assertEqual(row["receipt_artifact"], 9098010414)

    def test_windows_probe_stays_diagnostic(self):
        data = migration.load_strict(migration.FILES["source"])
        row = next(row for row in data["heads"] if row["name"] == "windows-isolation-diagnostic")
        self.assertEqual(row["standing"], "diagnostic-only")
        self.assertIn("historical", row["destination"])

    def test_lore_stays_out_of_generic_core(self):
        data = migration.load_strict(migration.FILES["ownership"])
        self.assertIn("ASOIAF question dossier", data["domain_adapter_boundary"]["stays_with_axm_canon_asoiaf"])
        self.assertIn("private book payload", data["forbidden_imports"])
        for plane in data["planes"]:
            self.assertNotIn("asoiaf", plane["destination"].casefold())

    def test_tier_bench_public_names_are_declared(self):
        data = migration.load_strict(migration.FILES["renaming"])
        mapping = dict(data["module_map"])
        self.assertEqual(mapping["asoiaf-answer-work-order"], "work-order")
        self.assertEqual(mapping["asoiaf-answer-actor-capability-broker"], "actor-capability-broker")
        self.assertGreaterEqual(len(mapping), 18)

    def test_no_old_home_cleanup_is_authorized(self):
        data = migration.load_strict(migration.FILES["residue"])
        for row in data["rows"]:
            if row["object"] != "axm-arc exporter PR #301":
                self.assertFalse(row["removal_authorized"])

    def test_receipt_binds_every_ledger(self):
        docs = {name: migration.load_strict(path) for name, path in migration.FILES.items()}
        receipt = docs["receipt"]
        self.assertEqual(receipt["source_heads_sha256"], docs["source"]["receipt_sha256"])
        self.assertEqual(receipt["ownership_map_sha256"], docs["ownership"]["receipt_sha256"])
        self.assertEqual(receipt["renaming_plan_sha256"], docs["renaming"]["receipt_sha256"])
        self.assertEqual(receipt["residue_ledger_sha256"], docs["residue"]["receipt_sha256"])

    def test_tamper_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "SOURCE_HEADS.json"
            data = migration.load_strict(migration.FILES["source"])
            data["heads"][0]["commit"] = "0" * 40
            target.write_text(json.dumps(data), encoding="utf-8")
            loaded = migration.load_strict(target)
            with self.assertRaises(migration.MigrationError):
                migration.verify_self_hash(loaded, target)

    def test_duplicate_json_key_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "dup.json"
            target.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(migration.MigrationError):
                migration.load_strict(target)

if __name__ == "__main__":
    unittest.main()
