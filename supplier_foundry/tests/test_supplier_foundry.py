from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import qualify
import verify_asset
import verify_bundle


class SupplierFoundryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ROOT / "fixtures" / "two-triangles.gltf"
        self.manifest = qualify.load_json(ROOT / "supplier_manifest.json")

    def test_fixture_has_two_named_world_space_triangles(self) -> None:
        report = verify_asset.semantic_report(self.fixture)
        self.assertEqual(report["format"], "axm-asset-semantics/1")
        self.assertEqual(report["sceneCount"], 1)
        self.assertEqual(report["triangleCount"], 2)
        self.assertEqual(report["bounds"], {"min": [0.0, 0.0, 0.0], "max": [3.0, 1.0, 0.0]})
        self.assertEqual(set(report["namedNodes"]), {"TriangleA", "TriangleB"})
        self.assertTrue(report["semanticDigest"].startswith("assetsem1_"))

    def test_unreachable_duplicate_mesh_does_not_change_semantic_receipt(self) -> None:
        original = json.loads(self.fixture.read_text(encoding="utf-8"))
        baseline = verify_asset.semantic_report(self.fixture)["semanticDigest"]
        original["meshes"].append(json.loads(json.dumps(original["meshes"][2])))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extra-unused.gltf"
            path.write_text(json.dumps(original), encoding="utf-8")
            self.assertEqual(verify_asset.semantic_report(path)["semanticDigest"], baseline)

    def test_reachable_geometry_mutation_changes_semantic_receipt(self) -> None:
        original = json.loads(self.fixture.read_text(encoding="utf-8"))
        uri = original["buffers"][0]["uri"]
        header, encoded = uri.split(",", 1)
        payload = bytearray(base64.b64decode(encoded))
        # Change TriangleA's second vertex x coordinate from 1.0 to 1.5.
        payload[12:16] = (1.5).hex().encode()[:0]  # keep the mutation explicit below
        import struct
        struct.pack_into("<f", payload, 12, 1.5)
        original["buffers"][0]["uri"] = header + "," + base64.b64encode(payload).decode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutated.gltf"
            path.write_text(json.dumps(original), encoding="utf-8")
            self.assertNotEqual(
                verify_asset.semantic_report(path)["semanticDigest"],
                verify_asset.semantic_report(self.fixture)["semanticDigest"],
            )

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.gltf"
            path.write_text('{"asset":{"version":"2.0"},"asset":{"version":"2.0"}}', encoding="utf-8")
            with self.assertRaises(verify_asset.AssetError):
                verify_asset.semantic_report(path)

    def test_manifest_preserves_non_authority(self) -> None:
        qualify.validate_manifest(self.manifest)
        authority = self.manifest["authority"]
        self.assertEqual(authority["supplierSelection"], "measurement recommendation only")
        for key, value in authority.items():
            if key != "supplierSelection":
                self.assertEqual(value, "none")

    def test_manifest_authority_expansion_is_refused(self) -> None:
        value = json.loads(json.dumps(self.manifest))
        value["authority"]["estateScheduling"] = "owned"
        with self.assertRaises(qualify.QualificationError):
            qualify.validate_manifest(value)

    def test_qualification_identity_is_stable_and_sensitive(self) -> None:
        value = {"format": "axm-supplier-qualification/1", "status": "pass", "ripOut": {"status": "pending"}}
        first = qualify.qualification_identity(value)
        second = qualify.qualification_identity(json.loads(json.dumps(value)))
        self.assertEqual(first, second)
        value["status"] = "fail"
        self.assertNotEqual(first, qualify.qualification_identity(value))

    def test_path_escape_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(verify_bundle.BundleError):
                verify_bundle.safe_path(root, "../outside")

    def test_network_quarantine_requirement_fails_closed(self) -> None:
        prior_required = os.environ.get("AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE")
        prior_wrapper = os.environ.get("AXM_SUPPLIER_NETWORK_WRAPPER")
        try:
            os.environ["AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE"] = "1"
            os.environ.pop("AXM_SUPPLIER_NETWORK_WRAPPER", None)
            with self.assertRaises(qualify.QualificationError):
                qualify.network_wrapper()
        finally:
            if prior_required is None:
                os.environ.pop("AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE", None)
            else:
                os.environ["AXM_SUPPLIER_REQUIRE_NETWORK_QUARANTINE"] = prior_required
            if prior_wrapper is None:
                os.environ.pop("AXM_SUPPLIER_NETWORK_WRAPPER", None)
            else:
                os.environ["AXM_SUPPLIER_NETWORK_WRAPPER"] = prior_wrapper


if __name__ == "__main__":
    unittest.main()
