#!/usr/bin/env python3
"""Integrity checks for the ARC-D exploratory buffalo pilot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "oss-replay" / "arc_d_buffalo_pilot_v1"
FORBIDDEN = (
    b"3221",
    b"3741",
    b"3614",
    b"3760",
    b"3766",
    b"1567",
    b"github.com",
    b"83d203a",
    b"b2adc529",
    b"18927fa",
    b"b519882",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contract_keeps_gate_proposed_and_pilot_unadjudicated():
    contract = _json(PILOT / "contract.json")
    gate = _json(PILOT / "proposed_harvest_gate.json")
    assert contract["authority"]["harvest_gate"] == "proposed_not_operator_adopted"
    assert contract["authority"]["grading"] == "forbidden_until_gate_adoption"
    assert (
        contract["successful_pilot_terminal_status"]
        == "SEALED_RESPONSE_UNADJUDICATED"
    )
    assert contract["selection"]["sampling_preregistered"] is False
    assert contract["selection"]["rate_inference_allowed"] is False
    assert gate["gate_state"] == "proposed"
    assert gate["driver_may_apply"] is False


def test_prompt_hashes_and_leakage_scan_match_frozen_bytes():
    contract = _json(PILOT / "contract.json")
    scan = _json(PILOT / "packet_leakage_scan.json")
    expected = {item["item_id"]: item for item in contract["items"]}
    scan_expected = {item["item_id"]: item for item in scan["prompt_receipts"]}

    for item_id, contract_item in expected.items():
        prompt = PILOT / "items" / item_id / "packet" / "PROMPT.md"
        receipt = _json(prompt.parent / "build_receipt.json")
        prompt_bytes = prompt.read_bytes()
        digest = _sha256(prompt)
        assert digest == contract_item["prompt_sha256"]
        assert digest == scan_expected[item_id]["prompt_sha256"]
        assert digest == receipt["prompt_sha256"]
        assert len(prompt_bytes) == contract_item["prompt_bytes"]
        assert len(prompt_bytes) == receipt["prompt_bytes"]
        assert not [fragment for fragment in FORBIDDEN if fragment in prompt_bytes]
        envelope = prompt.parent / "delivered_envelope.txt"
        assert _sha256(envelope) == receipt["delivered_envelope_sha256"]
        assert envelope.stat().st_size == receipt["delivered_envelope_bytes"]
        assert receipt["transport_transform"] == "html.escape(prompt, quote=False)"


def test_reference_proposals_cannot_close_correctness():
    references = sorted(PILOT.glob("items/*/reference/metadata.json"))
    assert len(references) == 3
    for path in references:
        reference = _json(path)
        assert reference["merged"] is False
        assert reference["submitted_reviews"] == 0
        assert reference["may_serve_as_ground_truth"] is False


def test_system_errors_are_hash_bound_partial_rows_not_observations():
    manifest = _json(PILOT / "runs" / "manifest.json")
    assert manifest["state"] == "PARTIAL_SYSTEM_ERROR"
    assert manifest["attempts"] == 3
    assert manifest["responses"] == 0
    assert manifest["scientific_observations"] == 0

    for row in manifest["administration_receipts"]:
        receipt_path = PILOT / row["path"]
        receipt = _json(receipt_path)
        run_dir = receipt_path.parent
        packet_dir = PILOT / "items" / row["item_id"] / "packet"
        assert _sha256(receipt_path) == row["sha256"]
        assert receipt["thread_status"] == "systemError"
        assert receipt["assistant_response_present"] is False
        assert receipt["scientific_state"] == "PARTIAL_NOT_AN_OBSERVATION"
        assert receipt["retry_permitted_under_frozen_stopping_rule"] is False
        assert _sha256(packet_dir / "PROMPT.md") == receipt["prompt_sha256"]
        assert (packet_dir / "PROMPT.md").stat().st_size == receipt["prompt_bytes"]
        assert (
            _sha256(packet_dir / "delivered_envelope.txt")
            == receipt["delivered_envelope_sha256"]
        )
        assert (
            (packet_dir / "delivered_envelope.txt").stat().st_size
            == receipt["delivered_envelope_bytes"]
        )
        assert _sha256(run_dir / "raw_response.txt") == receipt["response_sha256"]
        assert (run_dir / "raw_response.txt").stat().st_size == 0
        assert _sha256(run_dir / "events.jsonl") == receipt["event_snapshot_sha256"]
        assert (
            _sha256(run_dir / "thread_snapshot.json")
            == receipt["thread_snapshot_sha256"]
        )
        assert _sha256(run_dir / "outcome.json") == receipt["outcome_sha256"]


def test_simulation_manifest_binds_nonempirical_outputs():
    manifest = _json(PILOT / "simulations" / "manifest.json")
    assert manifest["evidence_class"] == "ILLUSTRATIVE_PROJECTION"
    assert manifest["empirical"] is False
    assert manifest["cost"] == "UNMEASURED"
    assert "harmful transfer" in manifest["unmodeled_channels"]

    for scenario in manifest["scenarios"]:
        path = PILOT / "simulations" / scenario["file"]
        projection = _json(path)
        assert _sha256(path) == scenario["sha256"]
        assert projection["evidence_class"] == "ILLUSTRATIVE_PROJECTION"
        assert projection["empirical"] is False
        assert projection["work_accounting"]["cost"]["state"] == "UNMEASURED"


def _run_standalone() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except Exception as exc:  # pragma: no cover
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
