# MACHINE-GENERATED characterization test (gpt-5.3-codex-spark), mutation-verified.
# module=scripts\validate_arc_d_b2_packet.py  mutation_score=5/6
# Pins CURRENT behavior; review before trusting.
from __future__ import annotations
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scripts"))
#!/usr/bin/env python3

import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Generator

import validate_arc_d_b2_packet as validator


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_file(path: Path, payload: object | bytes | str) -> None:
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        return
    if isinstance(payload, str):
        path.write_bytes(payload.encode("utf-8"))
        return
    path.write_text(_json_bytes(payload).decode("utf-8"), encoding="utf-8")


def _build_case(
    root: Path,
    *,
    official_dispatch_permitted: bool = True,
) -> tuple[Path, Path, str]:
    packet = root / "packet"
    packet.mkdir()

    prompt_text = "Solve:\n2+2?"
    response_bytes = b"4"
    admin_payload = {"graded": False, "harvest_gate_applied": False}
    admin_payload_bytes = _json_bytes(admin_payload)
    admin_payload_sha = _sha256(admin_payload_bytes)

    manifest_item_id = "item-123"
    prompt_sha = _sha256(prompt_text.encode("utf-8"))
    response_sha = _sha256(response_bytes)

    charter_payload = {
        "sealed_evidence": {
            "responses": [
                {
                    "item_id": manifest_item_id,
                    "prompt_sha256": prompt_sha,
                    "response_sha256": response_sha,
                    "response_bytes": len(response_bytes),
                    "administration_receipt_sha256": admin_payload_sha,
                }
            ]
        }
    }
    charter_bytes = _json_bytes(charter_payload)
    charter_sha256 = _sha256(charter_bytes)

    file_payloads: dict[str, object | bytes | str] = {
        "CHARTER.json": charter_bytes,
        "ADMINISTRATION_RECEIPT.json": admin_payload_bytes,
        "GRADE_PAYLOAD.schema.json": {"$id": "https://tier-bench.local/schemas/arc_d_b2_grade_payload.schema.json"},
        "GRADE_RECEIPT.schema.json": {"$id": "https://tier-bench.local/schemas/arc_d_b2_grade_receipt.schema.json"},
        "GRADING_TASK.md": "# Grade task\n",
        "ORIGINAL_ITEM.json": {"item_id": manifest_item_id},
        "ORIGINAL_PROMPT.md": prompt_text,
        "ORIGINAL_PROMPT_RECEIPT.json": {"signed": False},
        "PROBLEM.md": "# Problem text\n",
        "REFERENCE_STATUS.json": {"may_serve_as_ground_truth": False},
        "SEALED_RESPONSE.txt": response_bytes,
        "SOURCE_EXCERPT.py": "print('source excerpt')\n",
    }

    manifest_payload = {
        "schema": "tier-bench/arc-d-b2-packet@1",
        "protocol_id": "arc_d_b2",
        "packet_id": "arc_d_b2_item-123_v1",
        "item_id": manifest_item_id,
        "source_commit": "aabbccddeeff00112233445566778899",
        "charter_sha256": charter_sha256,
        "prompt_sha256": prompt_sha,
        "response_sha256": response_sha,
        "response_bytes": len(response_bytes),
        "isolation": {
            "one_response_only": True,
            "peer_grade_included": False,
            "repository_checkout_included": False,
            "reference_is_ground_truth": False,
        },
    }

    for name, payload in file_payloads.items():
        _write_file(packet / name, payload)

    manifest_payload["files"] = []
    for name in sorted(validator.EXPECTED_NAMES - {"PACKET.json"}):
        path = packet / name
        manifest_payload["files"].append({
            "path": name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path.read_bytes()),
        })

    manifest_path = packet / "PACKET.json"
    _write_file(manifest_path, manifest_payload)

    manifest_bytes = manifest_path.read_bytes()
    receipt = {
        "schema": "tier-bench/arc-d-b2-packet-export-receipt@1",
        "protocol_id": "arc_d_b2",
        "packet_id": manifest_payload["packet_id"],
        "item_id": manifest_item_id,
        "source_commit": manifest_payload["source_commit"],
        "packet_sha256": _sha256(manifest_bytes),
        "charter_sha256": charter_sha256,
        "prompt_sha256": prompt_sha,
        "response_sha256": response_sha,
        "response_bytes": len(response_bytes),
        "response_text_displayed_to_driver": False,
        "official_dispatch_permitted": official_dispatch_permitted,
    }
    receipt_path = root / "RECEIPT.json"
    _write_file(receipt_path, receipt)

    return packet, receipt_path, charter_sha256


@contextlib.contextmanager
def _patched_expected_charter(sha: str) -> Generator[None, None, None]:
    original = validator.EXPECTED_CHARTER_SHA256
    validator.EXPECTED_CHARTER_SHA256 = sha
    try:
        yield
    finally:
        validator.EXPECTED_CHARTER_SHA256 = original


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_validate_accepts_happy_path() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        with _patched_expected_charter(charter_sha):
            assert validator.validate(packet, receipt) == []


def test_validate_rejects_missing_packet_directory() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        missing_packet = Path(workspace) / "missing"
        receipt = Path(workspace) / "RECEIPT.json"
        receipt.write_text("{}", encoding="utf-8")
        assert validator.validate(missing_packet, receipt) == ["packet directory missing"]


def test_validate_rejects_missing_or_invalid_receipt() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, _, _ = _build_case(Path(workspace))
        missing_receipt = Path(workspace) / "MISSING.json"
        assert validator.validate(packet, missing_receipt) == ["coordinator receipt missing or inside grader scope"]


def test_validate_rejects_receipt_inside_packet() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, _, _ = _build_case(Path(workspace))
        receipt_inside = packet / "PACKET.json"
        assert validator.validate(packet, receipt_inside) == ["coordinator receipt missing or inside grader scope"]


def test_validate_rejects_unratified_charter_bytes() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, _ = _build_case(Path(workspace))
        assert validator.validate(packet, receipt) == [
            "packet does not contain the ratified charter bytes",
            "manifest charter hash is not ratified",
        ]


def test_validate_rejects_file_allowlist_mismatch() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        (packet / "UNEXPECTED.txt").write_text("extra", encoding="utf-8")
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["packet file allowlist mismatch: ['UNEXPECTED.txt']"]


def test_validate_rejects_subdirectories() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        (packet / "tmp").mkdir()
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["packet must not contain subdirectories"]


def test_validate_rejects_bad_packet_schema() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        manifest = _load_json(packet / "PACKET.json")
        manifest["schema"] = "bad"
        _write_file(packet / "PACKET.json", manifest)
        receipt_payload = _load_json(receipt)
        receipt_payload["packet_sha256"] = _sha256((packet / "PACKET.json").read_bytes())
        _write_file(receipt, receipt_payload)
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["unexpected packet schema"]


def test_validate_rejects_packet_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        receipt_payload = _load_json(receipt)
        receipt_payload["packet_sha256"] = "deadbeef"
        _write_file(receipt, receipt_payload)
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["packet manifest hash mismatch"]


def test_validate_rejects_file_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        (packet / "PROBLEM.md").write_text("# Tampered\n", encoding="utf-8")
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["listed file hash/size mismatch: PROBLEM.md"]


def test_validate_rejects_prompt_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        tampered_prompt = b"tampered"
        (packet / "ORIGINAL_PROMPT.md").write_bytes(tampered_prompt)
        manifest = _load_json(packet / "PACKET.json")
        for row in manifest["files"]:
            if row["path"] == "ORIGINAL_PROMPT.md":
                row["bytes"] = len(tampered_prompt)
                row["sha256"] = _sha256(tampered_prompt)
                break
        _write_file(packet / "PACKET.json", manifest)
        receipt_payload = _load_json(receipt)
        receipt_payload["packet_sha256"] = _sha256((packet / "PACKET.json").read_bytes())
        _write_file(receipt, receipt_payload)
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["original prompt hash mismatch"]


def test_validate_rejects_unbound_item_id() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        manifest = _load_json(packet / "PACKET.json")
        manifest["item_id"] = "different-item"
        _write_file(packet / "PACKET.json", manifest)
        receipt_payload = _load_json(receipt)
        receipt_payload["item_id"] = "different-item"
        _write_file(packet / "ORIGINAL_ITEM.json", {"item_id": "different-item"})
        manifest_payload_path = packet / "PACKET.json"
        manifest_payload = _load_json(manifest_payload_path)
        for row in manifest_payload["files"]:
            if row["path"] == "ORIGINAL_ITEM.json":
                original_item_bytes = (packet / "ORIGINAL_ITEM.json").read_bytes()
                row["bytes"] = len(original_item_bytes)
                row["sha256"] = _sha256(original_item_bytes)
                break
        _write_file(manifest_payload_path, manifest_payload)
        receipt_payload["packet_sha256"] = _sha256(manifest_payload_path.read_bytes())
        _write_file(receipt, receipt_payload)
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["item is not bound by the ratified charter"]


def test_validate_detects_administration_mutation() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        _write_file(packet / "ADMINISTRATION_RECEIPT.json", {"graded": True, "harvest_gate_applied": False})
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == [
            "listed file hash/size mismatch: ADMINISTRATION_RECEIPT.json",
            "administration receipt differs from charter",
            "historical administration receipt was mutated",
        ]


def test_validate_detects_reference_and_receipt_errors() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        ref_payload = _load_json(packet / "REFERENCE_STATUS.json")
        ref_payload["may_serve_as_ground_truth"] = True
        _write_file(packet / "REFERENCE_STATUS.json", ref_payload)
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == [
            "listed file hash/size mismatch: REFERENCE_STATUS.json",
            "unmerged reference must not serve as ground truth",
        ]


def test_validate_respects_require_official_false() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(
            Path(workspace),
            official_dispatch_permitted=False,
        )
        with _patched_expected_charter(charter_sha):
            assert validator.validate(packet, receipt, require_official=False) == []


def test_validate_rejects_official_dispatch_requirement() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(
            Path(workspace),
            official_dispatch_permitted=False,
        )
        with _patched_expected_charter(charter_sha):
            errors = validator.validate(packet, receipt)
        assert errors == ["packet was not exported from the exact default-branch commit"]


def test_main_prints_ok_for_valid_input() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, receipt, charter_sha = _build_case(Path(workspace))
        with _patched_expected_charter(charter_sha):
            original_argv = list(sys.argv)
            sys.argv = ["validate_arc_d_b2_packet.py", str(packet), "--receipt", str(receipt)]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main()
            sys.argv = original_argv
        expected_hash = _sha256((packet / "PACKET.json").read_bytes())
        assert exit_code == 0
        assert stdout.getvalue() == f"OK: arc_d_b2_item-123_v1 packet_sha256={expected_hash}\n"


def test_main_prints_errors_for_invalid_input() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        packet, _, _ = _build_case(Path(workspace))
        missing_receipt = Path(workspace) / "MISSING.json"
        original_argv = list(sys.argv)
        sys.argv = ["validate_arc_d_b2_packet.py", str(packet), "--receipt", str(missing_receipt)]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = validator.main()
        sys.argv = original_argv
        assert exit_code == 1
        assert stdout.getvalue() == "ERROR: coordinator receipt missing or inside grader scope\n"


def main() -> None:
    tests = [
        test_validate_accepts_happy_path,
        test_validate_rejects_missing_packet_directory,
        test_validate_rejects_missing_or_invalid_receipt,
        test_validate_rejects_receipt_inside_packet,
        test_validate_rejects_unratified_charter_bytes,
        test_validate_rejects_file_allowlist_mismatch,
        test_validate_rejects_subdirectories,
        test_validate_rejects_bad_packet_schema,
        test_validate_rejects_packet_hash_mismatch,
        test_validate_rejects_file_hash_mismatch,
        test_validate_rejects_prompt_hash_mismatch,
        test_validate_rejects_unbound_item_id,
        test_validate_detects_administration_mutation,
        test_validate_detects_reference_and_receipt_errors,
        test_validate_respects_require_official_false,
        test_validate_rejects_official_dispatch_requirement,
        test_main_prints_ok_for_valid_input,
        test_main_prints_errors_for_invalid_input,
    ]

    for test in tests:
        test()

    print("OK")


if __name__ == "__main__":
    main()
