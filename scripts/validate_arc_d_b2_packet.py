#!/usr/bin/env python3
"""Validate an ARC-D B2 packet without displaying or interpreting its response."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_CHARTER_SHA256 = "44306491048c792cf4e1a049d8e8059d8033f4f56bb73f8b821cf1483c20a16e"

EXPECTED_NAMES = {
    "ADMINISTRATION_RECEIPT.json",
    "CHARTER.json",
    "GRADE_PAYLOAD.schema.json",
    "GRADE_RECEIPT.schema.json",
    "GRADING_TASK.md",
    "ORIGINAL_ITEM.json",
    "ORIGINAL_PROMPT.md",
    "ORIGINAL_PROMPT_RECEIPT.json",
    "PACKET.json",
    "PROBLEM.md",
    "REFERENCE_STATUS.json",
    "SEALED_RESPONSE.txt",
    "SOURCE_EXCERPT.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(packet: Path, receipt_path: Path, *, require_official: bool = True) -> list[str]:
    errors: list[str] = []
    packet = packet.resolve()
    receipt_path = receipt_path.resolve()
    if not packet.is_dir():
        return ["packet directory missing"]
    names = {path.name for path in packet.iterdir() if path.is_file()}
    if names != EXPECTED_NAMES:
        errors.append(f"packet file allowlist mismatch: {sorted(names ^ EXPECTED_NAMES)}")
    if any(path.is_dir() for path in packet.iterdir()):
        errors.append("packet must not contain subdirectories")
    if not receipt_path.is_file() or packet in receipt_path.parents:
        errors.append("coordinator receipt missing or inside grader scope")
        return errors

    manifest = _json(packet / "PACKET.json")
    receipt = _json(receipt_path)
    if manifest.get("schema") != "tier-bench/arc-d-b2-packet@1":
        errors.append("unexpected packet schema")
    if receipt.get("schema") != "tier-bench/arc-d-b2-packet-export-receipt@1":
        errors.append("unexpected export receipt schema")
    if _sha256(packet / "PACKET.json") != receipt.get("packet_sha256"):
        errors.append("packet manifest hash mismatch")
    if _sha256(packet / "CHARTER.json") != EXPECTED_CHARTER_SHA256:
        errors.append("packet does not contain the ratified charter bytes")
    if manifest.get("charter_sha256") != EXPECTED_CHARTER_SHA256:
        errors.append("manifest charter hash is not ratified")
    for key in ("packet_id", "item_id", "source_commit", "charter_sha256", "prompt_sha256", "response_sha256", "response_bytes"):
        if manifest.get(key) != receipt.get(key):
            errors.append(f"manifest/receipt mismatch: {key}")

    listed = {row["path"]: row for row in manifest.get("files", [])}
    if set(listed) != EXPECTED_NAMES - {"PACKET.json"}:
        errors.append("manifest file list differs from allowlist")
    for name, row in listed.items():
        path = packet / name
        if not path.is_file():
            errors.append(f"listed file missing: {name}")
            continue
        if path.stat().st_size != row.get("bytes") or _sha256(path) != row.get("sha256"):
            errors.append(f"listed file hash/size mismatch: {name}")
    response = packet / "SEALED_RESPONSE.txt"
    if response.is_file():
        if response.stat().st_size != manifest.get("response_bytes") or _sha256(response) != manifest.get("response_sha256"):
            errors.append("sealed response hash/size mismatch")
    if _sha256(packet / "ORIGINAL_PROMPT.md") != manifest.get("prompt_sha256"):
        errors.append("original prompt hash mismatch")
    charter = _json(packet / "CHARTER.json")
    rows = {row["item_id"]: row for row in charter.get("sealed_evidence", {}).get("responses", [])}
    row = rows.get(manifest.get("item_id"))
    if row is None:
        errors.append("item is not bound by the ratified charter")
    else:
        for key in ("prompt_sha256", "response_sha256", "response_bytes"):
            if manifest.get(key) != row.get(key):
                errors.append(f"manifest differs from charter: {key}")
        if _sha256(packet / "ADMINISTRATION_RECEIPT.json") != row.get("administration_receipt_sha256"):
            errors.append("administration receipt differs from charter")
    admin = _json(packet / "ADMINISTRATION_RECEIPT.json")
    if admin.get("graded") is not False or admin.get("harvest_gate_applied") is not False:
        errors.append("historical administration receipt was mutated")
    if _json(packet / "ORIGINAL_ITEM.json").get("item_id") != manifest.get("item_id"):
        errors.append("item metadata does not match packet item")
    if _json(packet / "GRADE_PAYLOAD.schema.json").get("$id") != "https://tier-bench.local/schemas/arc_d_b2_grade_payload.schema.json":
        errors.append("unexpected grade payload schema")
    if _json(packet / "GRADE_RECEIPT.schema.json").get("$id") != "https://tier-bench.local/schemas/arc_d_b2_grade_receipt.schema.json":
        errors.append("unexpected grade receipt schema")
    reference = _json(packet / "REFERENCE_STATUS.json")
    if reference.get("may_serve_as_ground_truth") is not False:
        errors.append("unmerged reference must not serve as ground truth")
    isolation = manifest.get("isolation", {})
    expected_isolation = {
        "one_response_only": True,
        "peer_grade_included": False,
        "repository_checkout_included": False,
        "reference_is_ground_truth": False,
    }
    if isolation != expected_isolation:
        errors.append("packet isolation flags are not fail-closed")
    if receipt.get("response_text_displayed_to_driver") is not False:
        errors.append("driver response-display attestation missing")
    if require_official and receipt.get("official_dispatch_permitted") is not True:
        errors.append("packet was not exported from the exact default-branch commit")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.packet, args.receipt, require_official=True)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    manifest = _json(args.packet / "PACKET.json")
    print(f"OK: {manifest['packet_id']} packet_sha256={_sha256(args.packet / 'PACKET.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
