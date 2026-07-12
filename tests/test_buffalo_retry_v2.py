#!/usr/bin/env python3
"""Integrity checks for the separately versioned ARC-D retry."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "data" / "oss-replay" / "arc_d_buffalo_pilot_v2"
V1_COMMIT = "8517e3f56dd1228bf0efd007fcd8f48ec4c619a2"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _v1_prompt(item_id: str) -> bytes:
    spec = (
        f"{V1_COMMIT}:data/oss-replay/arc_d_buffalo_pilot_v1/"
        f"items/{item_id}/packet/PROMPT.md"
    )
    return subprocess.run(
        ["git", "show", spec], cwd=ROOT, check=True, capture_output=True
    ).stdout


def test_contract_extends_without_superseding_or_adjudicating_v1():
    contract = _json(V2 / "contract.json")
    assert contract["extends_protocol_id"] == "arc_d_buffalo_pilot_v1"
    assert contract["supersedes_v1"] is False
    assert contract["authority"]["harvest_gate"] == "proposed_not_operator_adopted"
    assert contract["authority"]["grading"] == "forbidden_until_gate_adoption"
    assert contract["observed_run_summary"]["graded_observations"] == 0
    assert contract["observed_run_summary"]["harvest_verdicts"] == 0


def test_capacity_preflight_is_exact_and_excluded():
    contract = _json(V2 / "contract.json")
    receipt = _json(V2 / "preflight" / "administration_receipt.json")
    prompt = contract["capacity_preflight"]["prompt"].encode()
    response = base64.b64decode(
        (V2 / "preflight" / "raw_response.utf8.b64").read_text()
    )
    assert len(prompt) == contract["capacity_preflight"]["prompt_bytes"] == 44
    assert _sha256_bytes(prompt) == contract["capacity_preflight"]["prompt_sha256"]
    assert response == b"CAPACITY_OK"
    assert _sha256_bytes(response) == receipt["response_sha256"]
    assert receipt["scientific_observation"] is False
    assert receipt["state"] == "ADMINISTRATION_ONLY_EXCLUDED"


def test_exact_v1_prompt_blobs_and_sealed_subject_responses():
    contract = _json(V2 / "contract.json")
    for item in contract["items"]:
        item_id = item["item_id"]
        prompt = _v1_prompt(item_id)
        assert len(prompt) == item["v1_prompt_bytes"]
        assert _sha256_bytes(prompt) == item["v1_prompt_sha256"]

        run = V2 / "runs" / item_id / "attempt-1"
        receipt = _json(run / "administration_receipt.json")
        event = _json(run / "event_receipt.json")
        snapshot = _json(run / "thread_snapshot.json")
        response = base64.b64decode((run / "raw_response.utf8.b64").read_text())

        assert receipt["v1_prompt_sha256"] == item["v1_prompt_sha256"]
        assert receipt["v1_prompt_bytes"] == item["v1_prompt_bytes"]
        assert receipt["scientific_state"] == "SEALED_RESPONSE_UNADJUDICATED"
        assert receipt["graded"] is False
        assert receipt["harvest_gate_applied"] is False
        assert receipt["tool_calls"] == event["tool_calls"] == 0
        assert receipt["thread_id"] == event["thread_id"] == snapshot["thread"]["id"]
        assert receipt["turn_id"] == event["turn_id"] == snapshot["turns"][0]["id"]
        assert len(response) == receipt["response_bytes"] == event["response_bytes"]
        assert _sha256_bytes(response) == receipt["response_sha256"]
        assert _sha256(run / "raw_response.utf8.b64") == receipt["base64_file_sha256"]
        assert _sha256(run / "event_receipt.json") == receipt["event_receipt_sha256"]
        assert _sha256(run / "thread_snapshot.json") == receipt["thread_snapshot_sha256"]


def test_run_and_administration_manifests_close_only_preservation():
    run = _json(V2 / "runs" / "manifest.json")
    assert run["state"] == "SEALED_RESPONSES_UNADJUDICATED"
    assert run["capacity_preflight"] == "PASS_EXCLUDED"
    assert run["subject_dispatches"] == run["responses"] == 3
    assert run["graded_observations"] == run["harvest_verdicts"] == 0

    admin = _json(V2 / "administration_manifest.json")
    for artifact in admin["artifacts"]:
        assert _sha256(V2 / artifact["path"]) == artifact["sha256"]


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
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
