from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from estate_lab.canonical import write_json
from estate_lab.errors import FloorGapError, FloorProtocolError
from estate_lab.floor import (
    build_adapter_descriptor,
    build_floor_registry,
    derived_adapter_descriptor_id,
    derived_registry_id,
    derived_submission_id,
    initialize_adapter,
    invoke_floor_adapter,
    load_floor_adapter,
    load_floor_spec,
    load_floor_submission,
    materialize_request,
    quality_tier,
    render_asyncapi,
    render_registry_markdown,
    run_floor_conformance,
    validate_floor_registry,
    validate_floor_response,
)
from estate_lab.floor_gaps import (
    build_gap_report,
    derived_gap_ledger_id,
    load_gap_ledger,
    render_gap_report_markdown,
)

HERE = Path(__file__).resolve().parents[1]
FLOOR_SPEC = HERE / "fixtures" / "floor" / "floor.example.json"
FLOOR_ADAPTER = HERE / "fixtures" / "floor" / "reference-adapter" / "adapter.json"
FLOOR_GAPS = HERE / "fixtures" / "floor" / "floor-gaps.example.json"

_SPEC = load_floor_spec(FLOOR_SPEC)
_ADAPTER = load_floor_adapter(FLOOR_ADAPTER, _SPEC)
_SUBMISSION = run_floor_conformance(_SPEC, _ADAPTER)


class FloorSpecificationTests(unittest.TestCase):
    spec = _SPEC
    adapter = _ADAPTER

    def test_floor_is_public_and_substantial(self) -> None:
        self.assertEqual(self.spec.floor_version, "1.0.0")
        self.assertGreaterEqual(len(self.spec.raw["vectors"]), 15)
        self.assertEqual(len(self.spec.raw["profiles"]), 8)
        self.assertGreaterEqual(len(self.spec.raw["bindings"]), 8)
        self.assertIn("domain or game law", self.spec.raw["authority_boundary"]["refuses"])

    def test_reference_descriptor_binds_source_bytes(self) -> None:
        artifact = self.adapter.raw["supply"]["artifacts"][0]
        source = self.adapter.source_path.parent / artifact["path"]
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), artifact["sha256"])
        self.assertEqual(self.adapter.descriptor_id, derived_adapter_descriptor_id(self.adapter.raw))

    def test_descriptor_tamper_refuses(self) -> None:
        raw = copy.deepcopy(self.adapter.raw)
        raw["authority"]["may_grant"] = True
        raw["descriptor_id"] = derived_adapter_descriptor_id(raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "adapter.json"
            write_json(path, raw)
            with self.assertRaises(FloorProtocolError):
                load_floor_adapter(path, self.spec)

    def test_floor_identity_tamper_refuses(self) -> None:
        raw = copy.deepcopy(self.spec.raw)
        raw["summary"] += " changed"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "floor.json"
            write_json(path, raw)
            with self.assertRaises(FloorProtocolError):
                load_floor_spec(path)

    def test_asyncapi_projection_is_stable(self) -> None:
        first = render_asyncapi(self.spec)
        second = render_asyncapi(self.spec)
        self.assertEqual(first, second)
        self.assertIn(self.spec.floor_id, first)
        self.assertIn("asyncapi: 3.0.0", first)


class FloorConformanceTests(unittest.TestCase):
    spec = _SPEC
    adapter = _ADAPTER
    submission = _SUBMISSION

    def test_reference_adapter_passes_all_claimed_profiles(self) -> None:
        submission = self.submission
        self.assertEqual(submission.result, "pass")
        self.assertEqual(submission.tier, "gold")
        self.assertEqual(set(submission.verified_profiles), set(self.adapter.profiles))
        self.assertEqual(submission.submission_id, derived_submission_id(submission.raw))
        self.assertTrue(all(row["status"] == "passed" for row in submission.raw["tests"]))

    def test_conformance_identity_is_stable(self) -> None:
        self.assertEqual(self.submission.submission_id, derived_submission_id(self.submission.raw))
        roundtrip = json.loads(json.dumps(self.submission.raw, sort_keys=True))
        self.assertEqual(self.submission.submission_id, derived_submission_id(roundtrip))

    def test_conformance_submission_roundtrip_is_self_verifying(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "submission.json"
            write_json(path, self.submission.raw)
            loaded = load_floor_submission(path)
            self.assertEqual(loaded.submission_id, self.submission.submission_id)
            self.assertEqual(loaded.raw, self.submission.raw)

    def test_generated_starter_uses_same_public_vector(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "adapter"
            adapter = initialize_adapter(
                directory,
                adapter_id="org.example.generated-adapter",
                name="Generated Test Adapter",
                floor_version=self.spec.floor_version,
            )
            adapter = load_floor_adapter(adapter.source_path, self.spec)
            vector = next(row for row in self.spec.raw["vectors"] if row["id"] == "core-health")
            request = materialize_request(self.spec, adapter, vector)
            response = invoke_floor_adapter(adapter, request)
            validate_floor_response(adapter, request, response, vector["expect"])
            self.assertEqual(response["health"]["state"], "ready")

    def test_platinum_requires_independent_and_substitution_evidence(self) -> None:
        profiles = tuple(self.adapter.profiles)
        self.assertEqual(quality_tier(self.spec, profiles), "gold")
        receipt = "a" * 64
        self.assertEqual(
            quality_tier(
                self.spec,
                profiles,
                independent_verifier=True,
                substitution_receipt_sha256=receipt,
            ),
            "platinum",
        )

    def test_semantic_mutating_adapter_fails_conformance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "adapter.py"
            source.write_text(
                """
import json, sys
from pathlib import Path
req=json.loads(Path(sys.argv[1]).read_text())
res={'format':'axm-interaction-response/1','request_id':req.get('request_id'),'adapter_id':'org.example.bad-adapter','kind':req.get('kind'),'accepted':True,'reason':None,'outcome':'accepted','semantic_digest':'0'*64,'observations':{}}
projection={k:v for k,v in res.items() if k!='response_id'}
import hashlib
res['response_id']='floorres1_'+hashlib.sha256(json.dumps(projection,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:32]
Path(sys.argv[2]).write_text(json.dumps(res))
""".strip()
                + "\n",
                encoding="utf-8",
            )
            descriptor = build_adapter_descriptor(
                adapter_id="org.example.bad-adapter",
                name="Bad Adapter",
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                floor_version=self.spec.floor_version,
            )
            descriptor["floor"]["profiles"] = ["core@1"]
            descriptor["descriptor_id"] = derived_adapter_descriptor_id(descriptor)
            write_json(root / "adapter.json", descriptor)
            adapter = load_floor_adapter(root / "adapter.json", self.spec)
            submission = run_floor_conformance(self.spec, adapter)
            self.assertEqual(submission.result, "fail")
            self.assertEqual(submission.tier, "declared")


class FloorRegistryTests(unittest.TestCase):
    spec = _SPEC
    adapter = _ADAPTER
    submission = _SUBMISSION

    def test_registry_admits_passing_submission(self) -> None:
        registry = build_floor_registry(self.spec, [self.submission])
        self.assertEqual(registry["registry_id"], derived_registry_id(registry))
        self.assertEqual(registry["entry_count"], 1)
        self.assertEqual(validate_floor_registry(registry, self.spec), registry)
        markdown = render_registry_markdown(registry)
        self.assertIn(self.adapter.adapter_id, markdown)
        self.assertIn(self.submission.submission_id, markdown)

    def test_registry_refuses_failed_submission(self) -> None:
        raw = copy.deepcopy(self.submission.raw)
        raw["result"] = "fail"
        raw["tests"][0]["status"] = "failed"
        raw["submission_id"] = derived_submission_id(raw)
        failed = load_floor_submission_from_raw(raw)
        with self.assertRaises(FloorProtocolError):
            build_floor_registry(self.spec, [failed])

    def test_registry_refuses_identity_drift(self) -> None:
        registry = build_floor_registry(self.spec, [self.submission])
        registry["entry_count"] = 2
        with self.assertRaises(FloorProtocolError):
            validate_floor_registry(registry, self.spec)


class FloorGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = load_gap_ledger(FLOOR_GAPS)

    def test_gap_ledger_is_substantial_and_executable(self) -> None:
        self.assertGreaterEqual(len(self.ledger.gaps), 40)
        self.assertEqual(self.ledger.ledger_id, derived_gap_ledger_id(self.ledger.raw))
        report = build_gap_report(self.ledger)
        self.assertGreater(report["counts_by_status"]["closed"], 20)
        self.assertGreater(report["counts_by_status"]["open"], 10)
        self.assertTrue(report["closure_queue"])
        self.assertIn("Closure queue", render_gap_report_markdown(report))

    def test_gap_identity_tamper_refuses(self) -> None:
        raw = copy.deepcopy(self.ledger.raw)
        raw["gaps"][0]["title"] += " changed"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gaps.json"
            write_json(path, raw)
            with self.assertRaises(FloorGapError):
                load_gap_ledger(path)

    def test_closed_gap_cannot_depend_on_open_gap(self) -> None:
        raw = copy.deepcopy(self.ledger.raw)
        closed = next(row for row in raw["gaps"] if row["status"] == "closed")
        open_gap = next(row for row in raw["gaps"] if row["status"] == "open")
        closed["dependencies"] = [open_gap["id"]]
        raw["ledger_id"] = derived_gap_ledger_id(raw)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gaps.json"
            write_json(path, raw)
            with self.assertRaises(FloorGapError):
                load_gap_ledger(path)


def load_floor_submission_from_raw(raw: dict):
    from estate_lab.floor import load_floor_submission_from_value

    return load_floor_submission_from_value(raw)


if __name__ == "__main__":
    unittest.main()
