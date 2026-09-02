#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import frontier_qualification as fq


HEAD = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
DIGEST = "4" * 64


class FrontierQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, name: str, value: object) -> Path:
        return self.write(name, json.dumps(value, sort_keys=True) + "\n")

    def fixture_args(self) -> argparse.Namespace:
        paths = self.root / "paths.z"
        paths.write_bytes(b"scripts/frontier_qualification.py\0tests/test_frontier_qualification.py\0")
        test_log = self.write(
            "tests.log",
            "test_alpha ... ok\n\n----------------------------------------------------------------------\nRan 1 test in 0.001s\n\nOK\n",
        )
        run_result = self.write_json(
            "run-result.json",
            {
                "campaign_id": "mock",
                "completed": True,
                "planned_request_count": 1,
                "provider_error_count": 0,
                "receipt_count": 1,
                "termination_reason": "completed",
            },
        )
        verification = self.write_json(
            "verification.json",
            {
                "campaign_id": "mock",
                "verified": True,
                "termination_reason": "completed",
                "receipt_count": 1,
                "exact_requests_rebuilt": 1,
                "raw_request_bodies_authenticated": 1,
                "raw_response_bodies_authenticated": 1,
                "usage_objects_rederived": 1,
                "identity_objects_rederived": 1,
                "identity_mismatch_count": 0,
            },
        )
        verification_value = json.loads(verification.read_text(encoding="utf-8"))
        summary = self.write_json(
            "summary.json",
            {
                "campaign_id": "mock",
                "receipt_count": 1,
                "verification": verification_value,
                "summary_sha256": DIGEST,
            },
        )
        plan = self.write_json("plan.json", {"campaign_id": "mock", "request_count": 1})
        receipts = self.write("receipts.jsonl", "{}\n")
        passive = self.write_json("passive.json", {"observation_sha256": DIGEST})
        manifest = self.write_json(
            "manifests/mock.json",
            {
                "schema": fq.MANIFEST_SCHEMA,
                "campaign_id": "mock",
                "execution": {"allow_live": False, "max_estimated_usd": 0},
                "subject": {"provider": "mock", "adapter": "mock"},
            },
        )
        return argparse.Namespace(
            repository="owner/repo",
            event_name="pull_request",
            workflow="frontier-fingerprint",
            workflow_ref="owner/repo/.github/workflows/frontier-fingerprint.yml@refs/pull/1/merge",
            run_id="123",
            run_attempt="1",
            pr_number="1",
            source_head_sha=HEAD,
            checked_out_sha=HEAD,
            tree_sha=TREE,
            base_sha=BASE,
            changed_paths_z=paths,
            test_log=[test_log],
            run_result=run_result,
            verification=verification,
            summary=summary,
            plan=plan,
            receipts=receipts,
            passive=[passive],
            manifest_root=manifest.parent,
            out=self.root / "receipt.json",
        )

    def test_committed_schemas_bind_runtime_identifiers(self) -> None:
        qualification = json.loads(
            (ROOT / "schemas" / "frontier-fingerprint-qualification.schema.json").read_text(
                encoding="utf-8"
            )
        )
        index = json.loads(
            (
                ROOT
                / "schemas"
                / "frontier-fingerprint-qualification-index.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            qualification["properties"]["schema"]["const"],
            fq.QUALIFICATION_SCHEMA,
        )
        self.assertEqual(index["properties"]["schema"]["const"], fq.INDEX_SCHEMA)

    def test_parse_test_log_derives_count(self) -> None:
        args = self.fixture_args()
        self.assertEqual(fq.parse_test_log(args.test_log[0])["count"], 1)

    def test_parse_test_log_rejects_ambiguous_counts(self) -> None:
        path = self.write("bad.log", "Ran 1 test in 0.1s\nRan 2 tests in 0.2s\n")
        with self.assertRaises(fq.QualificationError):
            fq.parse_test_log(path)

    def test_receipt_binds_exact_checked_out_head(self) -> None:
        args = self.fixture_args()
        args.checked_out_sha = "f" * 40
        with self.assertRaises(fq.QualificationError):
            fq.build_receipt(args)

    def test_receipt_rejects_live_manifest(self) -> None:
        args = self.fixture_args()
        self.write_json(
            "manifests/mock.json",
            {
                "schema": fq.MANIFEST_SCHEMA,
                "campaign_id": "mock",
                "execution": {"allow_live": True, "max_estimated_usd": 1},
                "subject": {"provider": "mock", "adapter": "mock"},
            },
        )
        with self.assertRaises(fq.QualificationError):
            fq.build_receipt(args)

    def test_receipt_rejects_campaign_count_drift(self) -> None:
        args = self.fixture_args()
        verification = json.loads(args.verification.read_text(encoding="utf-8"))
        verification["usage_objects_rederived"] = 0
        args.verification.write_text(json.dumps(verification), encoding="utf-8")
        with self.assertRaises(fq.QualificationError):
            fq.build_receipt(args)

    def test_receipt_rejects_public_text_canary(self) -> None:
        args = self.fixture_args()
        args.plan.write_text(json.dumps({"marker": "SENSITIVE_CANARY"}), encoding="utf-8")
        with self.assertRaises(fq.QualificationError):
            fq.build_receipt(args)

    def test_receipt_rejects_recognized_provider_credential(self) -> None:
        args = self.fixture_args()
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "present"}, clear=False):
            with self.assertRaises(fq.QualificationError):
                fq.build_receipt(args)

    def test_receipt_payload_hash_is_recomputable(self) -> None:
        receipt = fq.build_receipt(self.fixture_args())
        fq.verify_payload_hash(receipt)
        receipt["qualification"] = "FAIL"
        with self.assertRaises(fq.QualificationError):
            fq.verify_payload_hash(receipt)

    def test_render_is_derived_and_ends_with_control_question(self) -> None:
        receipt = fq.build_receipt(self.fixture_args())
        rendered = fq.render_comment(
            receipt,
            artifact_id="99",
            artifact_url="https://github.com/owner/repo/actions/runs/123/artifacts/99",
            artifact_digest=DIGEST,
            publication_artifact_id="100",
            publication_artifact_url="https://github.com/owner/repo/actions/runs/123/artifacts/100",
            publication_artifact_digest="5" * 64,
            comment_id="77",
        )
        self.assertIn(HEAD, rendered)
        self.assertIn("`1` receipts", rendered)
        self.assertIn("PR comment `77`", rendered)
        self.assertIn("**Control question:**", rendered)
        self.assertTrue(rendered.endswith("artifact?\n"))

    def test_render_rejects_partial_publication_identity(self) -> None:
        receipt = fq.build_receipt(self.fixture_args())
        with self.assertRaises(fq.QualificationError):
            fq.render_comment(
                receipt,
                artifact_id="99",
                artifact_url="https://github.com/owner/repo/actions/runs/123/artifacts/99",
                artifact_digest=DIGEST,
                publication_artifact_id="100",
            )

    def test_index_binds_returned_comment_and_artifact_ids(self) -> None:
        receipt = fq.build_receipt(self.fixture_args())
        receipt_path = self.write_json("receipt.json", receipt)
        args = argparse.Namespace(
            receipt=receipt_path,
            artifact_id="99",
            artifact_url="https://github.com/owner/repo/actions/runs/123/artifacts/99",
            artifact_digest=DIGEST,
            comment_id="77",
            comment_url="https://github.com/owner/repo/pull/1#issuecomment-77",
        )
        index = fq.build_index(args)
        self.assertEqual(index["evidence_artifact"]["id"], 99)
        self.assertEqual(index["pr_comment"]["id"], 77)
        fq.verify_payload_hash(index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
