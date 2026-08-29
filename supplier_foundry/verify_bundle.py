#!/usr/bin/env python3
"""Verify a Supplier Foundry asset bundle after every supplier is removed.

The script uses only the Python standard library and the bundled bounded glTF
verifier. With --finalize it changes only the ripOut record and qualification
identity after all independent checks pass. A second run without --finalize
verifies the final receipt without mutating it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from verify_asset import AssetError, canonical_bytes, semantic_report  # noqa: E402

MAX_JSON_BYTES = 2_000_000


class BundleError(ValueError):
    pass


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BundleError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise BundleError(f"JSON source is absent or oversized: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise BundleError(f"required bundle file is absent: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise BundleError("bundle path must be a non-empty string")
    path = (root / relative).resolve()
    resolved_root = root.resolve()
    if path != resolved_root and resolved_root not in path.parents:
        raise BundleError(f"bundle path escapes root: {relative}")
    return path


def qualification_identity(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "qualificationId"}
    return "supplierqual1_" + hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def verify(root: Path, allow_pending: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_json(root / "manifest.json")
    receipt_path = root / "qualification.json"
    receipt = load_json(receipt_path)
    if manifest.get("format") != "axm-supplier-pilot/1":
        raise BundleError("unsupported supplier manifest format")
    if receipt.get("format") != "axm-supplier-qualification/1":
        raise BundleError("unsupported qualification format")
    if receipt.get("status") != "pass":
        raise BundleError("qualification status is not pass")
    if receipt.get("pilotId") != manifest.get("id"):
        raise BundleError("qualification pilot identity does not match manifest")
    if receipt.get("capability") != (manifest.get("capability") or {}).get("id"):
        raise BundleError("qualification capability does not match manifest")
    if receipt.get("authority") != manifest.get("authority"):
        raise BundleError("qualification authority differs from the human-owned manifest")

    expected_id = qualification_identity(receipt)
    if receipt.get("qualificationId") != expected_id:
        raise BundleError("qualification identity mismatch")

    source_record = receipt.get("source") or {}
    source_path = safe_path(root, source_record.get("path"))
    if sha256_file(source_path) != source_record.get("sha256"):
        raise BundleError("source asset digest mismatch")
    source_semantic = semantic_report(source_path)
    if source_semantic.get("semanticDigest") != source_record.get("semanticDigest"):
        raise BundleError("source semantic digest mismatch")

    providers = receipt.get("providers")
    if not isinstance(providers, list) or len(providers) < 2:
        raise BundleError("qualification must contain at least two providers")
    provider_by_id: dict[str, dict[str, Any]] = {}
    for provider in providers:
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or provider_id in provider_by_id:
            raise BundleError("provider IDs must be unique strings")
        provider_by_id[provider_id] = provider
        if provider.get("status") != "pass":
            raise BundleError(f"provider is not qualified: {provider_id}")
        product = safe_path(root, provider.get("productPath"))
        if sha256_file(product) != provider.get("outputSha256"):
            raise BundleError(f"provider output digest mismatch: {provider_id}")
        semantic = semantic_report(product)
        if semantic.get("semanticDigest") != source_semantic.get("semanticDigest"):
            raise BundleError(f"provider changed bounded asset semantics: {provider_id}")
        if semantic.get("semanticDigest") != provider.get("semanticDigest"):
            raise BundleError(f"provider semantic receipt mismatch: {provider_id}")
        if provider.get("runOneSha256") != provider.get("runTwoSha256"):
            raise BundleError(f"provider product is not byte-deterministic: {provider_id}")

    selection = receipt.get("selection") or {}
    selected_id = selection.get("providerId")
    if selected_id not in provider_by_id:
        raise BundleError("selected provider is absent")
    selected = safe_path(root, selection.get("productPath"))
    if sha256_file(selected) != selection.get("sha256"):
        raise BundleError("selected product digest mismatch")
    if selection.get("sha256") != provider_by_id[selected_id].get("outputSha256"):
        raise BundleError("selected product does not match selected provider")
    if semantic_report(selected).get("semanticDigest") != source_semantic.get("semanticDigest"):
        raise BundleError("selected product changed bounded semantics")

    fallback = receipt.get("fallback") or {}
    fallback_path = safe_path(root, fallback.get("path"))
    if fallback_path != source_path:
        raise BundleError("fallback must preserve the exact source path")
    if fallback.get("sha256") != source_record.get("sha256"):
        raise BundleError("fallback source digest mismatch")
    if fallback.get("semanticDigest") != source_semantic.get("semanticDigest"):
        raise BundleError("fallback semantic digest mismatch")

    rip_out = receipt.get("ripOut") or {}
    state = rip_out.get("status")
    if state == "pending" and not allow_pending:
        raise BundleError("rip-out verification remains pending")
    if state not in ({"pending", "pass"} if allow_pending else {"pass"}):
        raise BundleError(f"unsupported rip-out status: {state}")

    return receipt, {
        "sourceSemantic": source_semantic,
        "providerCount": len(providers),
        "selectedProvider": selected_id,
        "selectedSha256": selection.get("sha256"),
    }


def finalize(root: Path, receipt: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    verifier_path = Path(__file__).resolve()
    receipt["ripOut"] = {
        "status": "pass",
        "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verifier": "supplier_foundry/verify_bundle.py",
        "verifierSha256": sha256_file(verifier_path),
        "supplierRuntimePresent": False,
        "checks": [
            "source digest and bounded semantics",
            "two provider output digests",
            "provider raw determinism",
            "provider semantic equivalence",
            "selected-product identity",
            "preserve-source fallback",
            "manifest authority equality",
            "path containment",
        ],
        "result": result,
    }
    receipt["qualificationId"] = qualification_identity(receipt)
    path = root / "qualification.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--finalize", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = args.bundle.resolve()
    try:
        receipt, result = verify(root, allow_pending=args.finalize)
        if args.finalize:
            finalize(root, receipt, result)
            receipt, result = verify(root, allow_pending=False)
    except (BundleError, AssetError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": "axm-supplier-ripout-verification/1",
                "status": "pass",
                "qualificationId": receipt["qualificationId"],
                **result,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
