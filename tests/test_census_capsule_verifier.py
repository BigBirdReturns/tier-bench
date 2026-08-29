"""Hostile witnesses for the CLAUDE-8 K3 tensor-census capsule verifier.

The completeness claim is "shards 96/96". Counting 96 unique sorted names does
not establish that: a capsule can drop one real checkpoint shard, substitute any
other unique filename, and still announce a closed denominator. These witnesses
require the EXACT generated set
``model-00001-of-000096.safetensors`` .. ``model-00096-of-000096.safetensors``.

Zero-model, zero-network.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFIER = REPO / "data" / "estate" / "k3-census-20260828" / "verify_census_capsule.py"
COMMITTED = REPO / "data" / "estate" / "k3-census-20260828" / "CENSUS-CAPSULE.json"

spec = importlib.util.spec_from_file_location("census_verify_capsule", VERIFIER)
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


class ShardDenominatorWitnesses(unittest.TestCase):
    def capsule(self) -> dict:
        return json.loads(COMMITTED.read_text(encoding="utf-8"))

    def run_capsule(self, capsule: dict) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "CENSUS-CAPSULE.json"
            p.write_text(json.dumps(capsule), encoding="utf-8")
            return V.run(p)

    def refuse(self, capsule: dict, fragment: str):
        with self.assertRaises(V.VerificationFailure) as ctx:
            self.run_capsule(capsule)
        self.assertIn(fragment, str(ctx.exception))

    def test_committed_capsule_verifies(self):
        self.assertEqual(self.run_capsule(self.capsule()), "COMMITTED_CAPSULE_VERIFIED")

    def test_substituted_shard_name_refuses(self):
        """The review's witness: drop one real shard, substitute a unique name
        that still sorts and still counts to 96."""
        c = self.capsule()
        c["rows"] = copy.deepcopy(c["rows"])
        c["rows"][40]["shard"] = "model-00041-of-000096.safetensors.bak"
        c["rows"].sort(key=lambda r: r["shard"])
        self.refuse(c, "not the exact checkpoint set")

    def test_duplicated_shard_refuses(self):
        c = self.capsule()
        c["rows"] = copy.deepcopy(c["rows"])
        c["rows"][95] = copy.deepcopy(c["rows"][94])
        self.refuse(c, "not the exact checkpoint set")

    def test_shards_out_of_canonical_order_refuse(self):
        c = self.capsule()
        c["rows"] = copy.deepcopy(c["rows"])
        c["rows"][0], c["rows"][1] = c["rows"][1], c["rows"][0]
        self.refuse(c, "not in canonical order")

    def test_short_row_count_refuses(self):
        c = self.capsule()
        c["rows"] = copy.deepcopy(c["rows"])[:95]
        self.refuse(c, "not 96")

    def test_open_denominator_refuses(self):
        c = self.capsule()
        c["denominator"] = dict(c["denominator"], missing_shards=["model-00096-of-000096.safetensors"])
        self.refuse(c, "not a closed 96/96")

    def test_totals_must_reconstruct_from_rows(self):
        c = self.capsule()
        c["rows"] = copy.deepcopy(c["rows"])
        c["rows"][0]["tensors"] += 1
        self.refuse(c, "dtype histogram does not sum")

    def test_aggregate_root_must_recompute(self):
        c = self.capsule()
        c["aggregate_root_sha256"] = "0" * 64
        self.refuse(c, "aggregate root does not recompute")


if __name__ == "__main__":
    unittest.main(verbosity=2)
