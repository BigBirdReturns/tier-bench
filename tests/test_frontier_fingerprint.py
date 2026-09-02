#!/usr/bin/env python3
"""Provider-free conformance and adversarial tests for frontier fingerprinting."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontier_fingerprint.adapters import (  # noqa: E402
    MockAdapter,
    TransportResult,
    normalize_anthropic,
    normalize_openai,
    selected_response_headers,
)
from frontier_fingerprint.canonical import (  # noqa: E402
    canonical_json_bytes,
    load_json,
    read_jsonl,
    sha256_object,
    write_json_atomic,
    write_jsonl_atomic,
)
from frontier_fingerprint.contracts import (  # noqa: E402
    COMPARISON_SCHEMA,
    ContractError,
    LIVE_ACK,
    api_contract_hash,
    validate_manifest,
)
from frontier_fingerprint.engine import (  # noqa: E402
    build_plan,
    execute_campaign,
    reseal_receipts_for_test,
    verify_run,
)
from frontier_fingerprint.passive import observe_transcript  # noqa: E402
from frontier_fingerprint.probes import build_schedule  # noqa: E402
from frontier_fingerprint.report import compare_summaries, summarize_run  # noqa: E402

FIXTURES = ROOT / "experiments" / "frontier_fingerprint"


class FrontierFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(FIXTURES / "mock-smoke.json")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def run_mock(self, manifest: dict | None = None, adapter: MockAdapter | None = None) -> Path:
        run_dir = self.base / f"run-{len(list(self.base.glob('run-*')))}"
        execute_campaign(manifest or self.manifest, run_dir, mock_adapter=adapter)
        return run_dir

    def test_example_manifests_validate(self) -> None:
        for name in (
            "mock-smoke.json",
            "fable-5-baseline.example.json",
            "fable-5-1.example.json",
            "sol-current-baseline.example.json",
            "astral-candidate.example.json",
        ):
            with self.subTest(name=name):
                validate_manifest(load_json(FIXTURES / name))

    def test_anthropic_requires_pinned_api_version(self) -> None:
        manifest = load_json(FIXTURES / "fable-5-1.example.json")
        del manifest["subject"]["api_contract"]["request_headers"]["anthropic-version"]
        with self.assertRaisesRegex(ContractError, "anthropic-version"):
            validate_manifest(manifest)

    def test_openai_requires_responses_contract_revision(self) -> None:
        manifest = load_json(FIXTURES / "astral-candidate.example.json")
        manifest["subject"]["api_contract"]["revision"] = "floating-latest"
        with self.assertRaisesRegex(ContractError, "responses-\\*"):
            validate_manifest(manifest)

    def test_plan_contains_no_prompt_or_response_text(self) -> None:
        plan = build_plan(self.manifest)
        encoded = json.dumps(plan, sort_keys=True)
        self.assertNotIn("amber000000", encoded)
        self.assertNotIn("Reply with", encoded)
        self.assertNotIn("AXM_ANCHOR_", encoded)
        self.assertEqual(plan["latency_design"]["latency_role"], "corroborating_only")
        self.assertEqual(plan["request_count"], len(build_schedule(self.manifest)))

    def test_cache_threshold_schedule_primes_then_reuses_each_size(self) -> None:
        schedule = [s for s in build_schedule(self.manifest) if s["probe_kind"] == "cache_threshold"]
        self.assertEqual(
            [item["condition"] for item in schedule],
            [
                "threshold-32-prime",
                "threshold-32-warm",
                "threshold-64-prime",
                "threshold-64-warm",
                "threshold-128-prime",
                "threshold-128-warm",
            ],
        )

    def test_cache_schedule_is_interleaved_and_repeated(self) -> None:
        schedule = [s for s in build_schedule(self.manifest) if s["probe_kind"] == "cache_reuse"]
        blocks: dict[int, list[str]] = {}
        for item in schedule:
            blocks.setdefault(item["block"], []).append(item["condition"])
        self.assertEqual(blocks[0], ["prime", "warm", "mutated"])
        self.assertEqual(blocks[1], ["prime", "mutated", "warm"])
        self.assertGreaterEqual(len(blocks), 4)

    def test_mock_run_authenticates_exact_bodies(self) -> None:
        run_dir = self.run_mock()
        verification = verify_run(run_dir)
        self.assertTrue(verification["verified"])
        self.assertEqual(
            verification["raw_response_bodies_authenticated"],
            verification["receipt_count"],
        )
        self.assertEqual(
            verification["usage_objects_rederived"], verification["receipt_count"]
        )

    def test_response_body_tamper_fails(self) -> None:
        run_dir = self.run_mock()
        receipt = read_jsonl(run_dir / "receipts.jsonl")[0]
        body_path = run_dir / receipt["response"]["body_path"]
        body = json.loads(body_path.read_text())
        body["usage"]["cache_read_input_tokens"] = 999999
        body_path.write_text(json.dumps(body), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "response body hash"):
            verify_run(run_dir)

    def test_resealed_envelope_cannot_override_provider_body(self) -> None:
        run_dir = self.run_mock()
        receipts = read_jsonl(run_dir / "receipts.jsonl")
        receipts[0]["response"]["usage"]["cache_read_input_tokens"] = 777
        receipts[0]["response"]["usage_sha256"] = sha256_object(
            receipts[0]["response"]["usage"]
        )
        write_jsonl_atomic(run_dir / "receipts.jsonl", reseal_receipts_for_test(receipts))
        with self.assertRaisesRegex(ContractError, "usage mismatch"):
            verify_run(run_dir)

    def test_request_body_tamper_fails(self) -> None:
        run_dir = self.run_mock()
        receipt = read_jsonl(run_dir / "receipts.jsonl")[0]
        path = run_dir / receipt["request"]["body_path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ContractError, "request body hash"):
            verify_run(run_dir)


    def test_resealed_request_envelope_cannot_override_frozen_generator(self) -> None:
        run_dir = self.run_mock()
        receipts = read_jsonl(run_dir / "receipts.jsonl")
        request_path = run_dir / receipts[0]["request"]["body_path"]
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["prefix"] = "z" * len(request["prefix"])
        rewritten = canonical_json_bytes(request)
        request_path.write_bytes(rewritten)
        receipts[0]["request"]["body_sha256"] = __import__("hashlib").sha256(rewritten).hexdigest()
        receipts[0]["request"]["body_bytes"] = len(rewritten)
        write_jsonl_atomic(run_dir / "receipts.jsonl", reseal_receipts_for_test(receipts))
        with self.assertRaisesRegex(ContractError, "exact deterministic request body"):
            verify_run(run_dir)

    def test_missing_raw_body_fails_closed(self) -> None:
        run_dir = self.run_mock()
        receipt = read_jsonl(run_dir / "receipts.jsonl")[0]
        (run_dir / receipt["response"]["body_path"]).unlink()
        with self.assertRaisesRegex(ContractError, "raw evidence body is missing"):
            verify_run(run_dir)

    def test_receipts_retain_no_prompt_or_response_text(self) -> None:
        run_dir = self.run_mock()
        encoded = (run_dir / "receipts.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("Reply with", encoded)
        self.assertNotIn("AXM_ANCHOR_", encoded)
        self.assertNotIn('"output_text"', encoded)
        receipts = read_jsonl(run_dir / "receipts.jsonl")
        self.assertTrue(
            all(not receipt["evidence_binding"]["public_prompt_text_retained"] for receipt in receipts)
        )


    def test_request_id_headers_are_hash_only(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["subject"]["api_contract"]["response_headers_to_capture"].append("x-request-id")
        captured = selected_response_headers(
            manifest,
            {"x-request-id": "provider-linkable-value", "x-mock-contract": "mock-v1"},
        )
        self.assertNotIn("provider-linkable-value", json.dumps(captured))
        self.assertRegex(captured["x-request-id"], r"^sha256:[0-9a-f]{64}$")

    def test_provider_error_stopping_rule_prevents_runaway_dispatch(self) -> None:
        class FailingMock:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, request_body: bytes) -> TransportResult:
                self.calls += 1
                return TransportResult(
                    503,
                    {"x-mock-contract": "mock-v1"},
                    canonical_json_bytes({"error": {"type": "unavailable"}}),
                    1.0,
                    "HTTPError:503",
                )

        adapter = FailingMock()
        run_dir = self.run_mock(adapter=adapter)  # type: ignore[arg-type]
        receipts = read_jsonl(run_dir / "receipts.jsonl")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["status"], "provider_error")
        verification = verify_run(run_dir)
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["termination_reason"], "provider_error_limit")


    def test_run_record_stopping_reason_is_verified(self) -> None:
        run_dir = self.run_mock()
        record = load_json(run_dir / "run.json")
        record["termination_reason"] = "provider_error_limit"
        write_json_atomic(run_dir / "run.json", record)
        with self.assertRaisesRegex(ContractError, "termination reason"):
            verify_run(run_dir)

    def test_response_model_binding_mismatch_is_receipt_level(self) -> None:
        run_dir = self.run_mock(adapter=MockAdapter(identity_mismatch=True))
        receipts = read_jsonl(run_dir / "receipts.jsonl")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["status"], "identity_mismatch")
        self.assertEqual(
            receipts[0]["response"]["identity"]["model_binding_status"], "mismatch"
        )
        verification = verify_run(run_dir)
        self.assertEqual(verification["identity_mismatch_count"], 1)

    def test_identity_signal_strength_is_adapter_specific(self) -> None:
        anthropic = normalize_anthropic(
            {
                "id": "msg_1",
                "model": "fable-5.1-real-id",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "content": [{"type": "text", "text": "ACK"}],
            },
            "fable-5.1-real-id",
        )
        openai = normalize_openai(
            {
                "id": "resp_1",
                "model": "astral-real-id",
                "system_fingerprint": "fp_abc",
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 8},
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
                "output_text": "ACK",
            },
            "astral-real-id",
        )
        self.assertEqual(anthropic.identity["signal_strength"], "weak")
        self.assertEqual(openai.identity["signal_strength"], "strong")

    def test_anthropic_nested_cache_creation_is_normalized(self) -> None:
        normalized = normalize_anthropic(
            {
                "model": "m",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 20,
                        "ephemeral_1h_input_tokens": 30,
                    },
                    "cache_read_input_tokens": 40,
                    "output_tokens": 5,
                },
                "content": [],
            },
            "m",
        )
        self.assertEqual(normalized.usage["cache_creation_input_tokens"], 50)

    def test_openai_cached_tokens_shape_is_normalized(self) -> None:
        normalized = normalize_openai(
            {
                "model": "m",
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 80},
                    "output_tokens": 10,
                    "total_tokens": 110,
                },
            },
            "m",
        )
        self.assertEqual(normalized.usage["cache_read_input_tokens"], 80)
        self.assertIsNone(normalized.usage["cache_creation_input_tokens"])

    def test_summary_uses_counters_as_primary_and_latency_as_corroborating(self) -> None:
        run_dir = self.run_mock()
        summary = summarize_run(run_dir)
        self.assertEqual(
            summary["cache_accounting"]["evidence_rank"],
            "primary_provider_reported_usage",
        )
        self.assertEqual(summary["latency"]["role"], "corroborating_only")
        self.assertEqual(summary["latency"]["cache_verdict_from_latency"], "prohibited")
        self.assertGreaterEqual(summary["latency"]["paired_block_count"], 4)
        self.assertEqual(
            summary["cache_threshold"]["lowest_observed_positive_warm_read_threshold_units"],
            32,
        )
        self.assertEqual(
            summary["api_contract_observations"]["contract_header_change_count"], 0
        )

    def test_summary_identity_is_not_collapsed_across_adapters(self) -> None:
        run_dir = self.run_mock()
        summary = summarize_run(run_dir)
        self.assertIn("mock", summary["identity"])
        self.assertEqual(summary["identity"]["mock"]["cross_adapter_drift_verdict"], "prohibited")

    def test_passive_claude_lane_retains_no_text(self) -> None:
        observed = observe_transcript(
            FIXTURES / "fixtures" / "passive-claude.jsonl",
            adapter="claude_code_jsonl",
        )
        encoded = json.dumps(observed, sort_keys=True)
        self.assertNotIn("SENSITIVE_CANARY_CLAUDE_DO_NOT_RETAIN", encoded)
        self.assertNotIn("SECOND_SECRET_CANARY", encoded)
        self.assertFalse(observed["retention_audit"]["transcript_text_retained"])
        self.assertGreater(observed["structural_compaction_marker_count"], 0)
        self.assertEqual(len(observed["abrupt_context_drop_candidates"]), 1)

    def test_passive_openai_lane_retains_no_text_and_tracks_fingerprint(self) -> None:
        observed = observe_transcript(
            FIXTURES / "fixtures" / "passive-openai.jsonl",
            adapter="codex_jsonl",
        )
        encoded = json.dumps(observed, sort_keys=True)
        self.assertNotIn("SENSITIVE_CANARY_OPENAI_DO_NOT_RETAIN", encoded)
        self.assertNotIn("ANOTHER_PRIVATE_STRING", encoded)
        self.assertEqual(observed["identity"]["system_fingerprint_change_count"], 1)
        self.assertEqual(len(observed["abrupt_context_drop_candidates"]), 1)

    def test_passive_output_does_not_retain_source_path(self) -> None:
        observed = observe_transcript(
            FIXTURES / "fixtures" / "passive-openai.jsonl",
            adapter="codex_jsonl",
        )
        self.assertFalse(observed["source_path_retained"])
        self.assertNotIn("source_path", observed)

    def test_live_dispatch_requires_all_three_gates(self) -> None:
        manifest = load_json(FIXTURES / "fable-5-1.example.json")
        with self.assertRaisesRegex(ContractError, "--live"):
            execute_campaign(
                manifest,
                self.base / "live-a",
                environ={"TIER_FABLE_51_MODEL": "real-model"},
            )
        with self.assertRaisesRegex(ContractError, "allow_live"):
            execute_campaign(
                manifest,
                self.base / "live-b",
                cli_live=True,
                environ={
                    "TIER_FABLE_51_MODEL": "real-model",
                    "TIER_FRONTIER_LIVE": LIVE_ACK,
                },
            )

    def test_live_manifest_requires_pricing_and_positive_ceiling(self) -> None:
        manifest = load_json(FIXTURES / "fable-5-1.example.json")
        manifest["execution"]["allow_live"] = True
        with self.assertRaisesRegex(ContractError, "pricing"):
            validate_manifest(manifest)
        manifest["pricing"] = {
            "input_per_million": 1,
            "cache_write_per_million": 1,
            "cache_read_per_million": 1,
            "output_per_million": 1,
        }
        with self.assertRaisesRegex(ContractError, "positive estimated cost ceiling"):
            validate_manifest(manifest)

    def test_comparison_matrix_freezes_probe_suite(self) -> None:
        matrix = load_json(FIXTURES / "comparison-matrix.json")
        self.assertEqual(matrix["schema"], COMPARISON_SCHEMA)
        for pair in matrix["pairs"]:
            self.assertIn("probe_suite_sha256", pair["required_equal"])
            self.assertIn("api_contract_sha256", pair["required_equal"])
            self.assertIn("usage_semantics_id", pair["required_equal"])

    def test_compare_accepts_exact_matched_contract(self) -> None:
        left_dir = self.run_mock()
        left = summarize_run(left_dir)
        left_path = self.base / "left.json"
        write_json_atomic(left_path, left)

        right_manifest = copy.deepcopy(self.manifest)
        right_manifest["campaign_id"] = "frontier-mock-smoke-v2"
        right_dir = self.run_mock(right_manifest)
        right = summarize_run(right_dir)
        right_path = self.base / "right.json"
        write_json_atomic(right_path, right)
        matrix = {
            "schema": COMPARISON_SCHEMA,
            "matrix_id": "mock-pair-v1",
            "pairs": [
                {
                    "id": "pair",
                    "left_campaign_id": self.manifest["campaign_id"],
                    "right_campaign_id": right_manifest["campaign_id"],
                    "required_equal": [
                        "api_contract_sha256",
                        "usage_semantics_id",
                        "probe_suite_sha256",
                    ],
                }
            ],
        }
        result = compare_summaries(matrix, [left_path, right_path])
        self.assertTrue(result["pairs"][0]["matched_contract"])
        self.assertEqual(result["pairs"][0]["token_metric_comparison"], "allowed")

    def test_compare_refuses_cross_semantics_token_delta(self) -> None:
        left_dir = self.run_mock()
        left = summarize_run(left_dir)
        left_path = self.base / "left.json"
        write_json_atomic(left_path, left)

        right = copy.deepcopy(left)
        right["campaign_id"] = "different-semantics"
        right["usage_semantics_id"] = "another-provider-semantics"
        right_path = self.base / "right.json"
        write_json_atomic(right_path, right)
        matrix = {
            "schema": COMPARISON_SCHEMA,
            "matrix_id": "refusal-v1",
            "pairs": [
                {
                    "id": "pair",
                    "left_campaign_id": left["campaign_id"],
                    "right_campaign_id": right["campaign_id"],
                    "required_equal": ["usage_semantics_id"],
                }
            ],
        }
        result = compare_summaries(matrix, [left_path, right_path])
        self.assertFalse(result["pairs"][0]["matched_contract"])
        self.assertEqual(result["pairs"][0]["token_metric_comparison"], "refused")

    def test_api_contract_hash_changes_when_version_changes(self) -> None:
        manifest = load_json(FIXTURES / "fable-5-baseline.example.json")
        before = api_contract_hash(manifest)
        manifest["subject"]["api_contract"]["request_headers"]["anthropic-version"] = "2099-01-01"
        after = api_contract_hash(manifest)
        self.assertNotEqual(before, after)

    def test_cli_provider_free_smoke(self) -> None:
        run_dir = self.base / "cli-run"
        summary_path = self.base / "cli-summary.json"
        commands = [
            [
                sys.executable,
                str(ROOT / "scripts" / "frontier_fingerprint.py"),
                "run",
                "--manifest",
                str(FIXTURES / "mock-smoke.json"),
                "--out",
                str(run_dir),
            ],
            [
                sys.executable,
                str(ROOT / "scripts" / "frontier_fingerprint.py"),
                "verify",
                "--run-dir",
                str(run_dir),
            ],
            [
                sys.executable,
                str(ROOT / "scripts" / "frontier_fingerprint.py"),
                "summarize",
                "--run-dir",
                str(run_dir),
                "--out",
                str(summary_path),
            ],
        ]
        for command in commands:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(summary_path.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
