#!/usr/bin/env python3
"""Response-blind tests for deterministic ARC-D B2 packet export."""
from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import export_arc_d_b2_packets as exporter  # noqa: E402
import validate_arc_d_b2_packet as validator  # noqa: E402

ITEMS = (
    "attrs_1567_setattr_mro",
    "httpx_3614_base_url_query",
    "httpx_3221_ipv6_no_proxy",
)


@contextmanager
def _scratch():
    path = ROOT / ".test-tmp" / f"arc-d-b2-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _export(parent: Path, item_id: str, suffix: str = "one"):
    out = parent / f"packet-{suffix}"
    receipt = parent / f"receipt-{suffix}.json"
    data = exporter.export_packet(
        item_id,
        out,
        receipt,
        require_default_branch=False,
    )
    return out, receipt, data


def test_all_three_exports_validate_without_response_output():
    with _scratch() as parent:
        for index, item_id in enumerate(ITEMS):
            out, receipt, data = _export(parent, item_id, str(index))
            assert validator.validate(out, receipt, require_official=False) == []
            assert "packet was not exported from the exact default-branch commit" in validator.validate(out, receipt)
            assert data["response_text_displayed_to_driver"] is False
            assert data["official_dispatch_permitted"] is False


def test_packet_is_deterministic_and_one_response_only():
    with _scratch() as parent:
        out_a, _, first = _export(parent, ITEMS[0], "a")
        out_b, _, second = _export(parent, ITEMS[0], "b")
        assert first["packet_sha256"] == second["packet_sha256"]
        assert (out_a / "SEALED_RESPONSE.txt").read_bytes() == (out_b / "SEALED_RESPONSE.txt").read_bytes()
        names = {path.name for path in out_a.iterdir()}
        assert names == validator.EXPECTED_NAMES
        assert not any("base64" in name.lower() or "peer" in name.lower() for name in names)


def test_reference_is_explicitly_non_authoritative():
    with _scratch() as parent:
        for index, item_id in enumerate(ITEMS):
            out, _, _ = _export(parent, item_id, str(index))
            reference = json.loads((out / "REFERENCE_STATUS.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "PACKET.json").read_text(encoding="utf-8"))
            assert reference["may_serve_as_ground_truth"] is False
            assert manifest["isolation"]["reference_is_ground_truth"] is False


def test_validator_detects_response_tamper_without_printing_content():
    with _scratch() as parent:
        out, receipt, _ = _export(parent, ITEMS[1])
        with (out / "SEALED_RESPONSE.txt").open("ab") as handle:
            handle.write(b"x")
        errors = validator.validate(out, receipt, require_official=False)
        assert "sealed response hash/size mismatch" in errors
        assert "listed file hash/size mismatch: SEALED_RESPONSE.txt" in errors


def test_export_never_overwrites_packet_or_receipt():
    with _scratch() as parent:
        out, receipt, _ = _export(parent, ITEMS[2])
        try:
            exporter.export_packet(ITEMS[2], out, parent / "other.json", require_default_branch=False)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing packet must be rejected")
        try:
            exporter.export_packet(ITEMS[2], parent / "other", receipt, require_default_branch=False)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing receipt must be rejected")


def test_packet_and_payload_schemas_do_not_loosen_ratified_receipt():
    packet = json.loads((ROOT / "schemas" / "arc_d_b2_packet.schema.json").read_text(encoding="utf-8"))
    payload = json.loads((ROOT / "schemas" / "arc_d_b2_grade_payload.schema.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "schemas" / "arc_d_b2_grade_receipt.schema.json").read_text(encoding="utf-8"))
    assert packet["additionalProperties"] is False
    assert payload["additionalProperties"] is False
    assert payload["$defs"]["finding"] == receipt["$defs"]["finding"]
    assert payload["properties"]["response_disposition"] == receipt["properties"]["response_disposition"]
    path_pattern = packet["properties"]["files"]["items"]["properties"]["path"]["pattern"]
    assert all(re.fullmatch(path_pattern, name) for name in validator.EXPECTED_NAMES - {"PACKET.json"})


def _run_standalone() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
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
