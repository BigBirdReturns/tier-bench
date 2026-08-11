from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FILES = {
    "source": ROOT / "SOURCE_HEADS.json",
    "ownership": ROOT / "OWNERSHIP_MAP.json",
    "renaming": ROOT / "RENAMING_PLAN.json",
    "residue": ROOT / "RESIDUE_LEDGER.json",
    "receipt": ROOT / "MIGRATION_RECEIPT.json",
}

class MigrationError(RuntimeError):
    pass

def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def load_strict(path: Path) -> dict[str, Any]:
    def hook(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise MigrationError(f"duplicate key {key!r} in {path}")
            out[key] = value
        return out
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, UnicodeError, ValueError) as exc:
        raise MigrationError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"{path} is not an object")
    return value

def verify_self_hash(value: dict[str, Any], path: Path) -> None:
    observed = value.get("receipt_sha256")
    if not isinstance(observed, str) or not re.fullmatch(r"[0-9a-f]{64}", observed):
        raise MigrationError(f"{path} has malformed receipt_sha256")
    body = dict(value)
    body.pop("receipt_sha256")
    expected = hashlib.sha256(canonical(body)).hexdigest()
    if observed != expected:
        raise MigrationError(f"{path} receipt mismatch: expected {expected}, observed {observed}")

def verify_artifact(path: Path, expected_sha: str) -> dict[str, Any]:
    data = path.read_bytes()
    observed = hashlib.sha256(data).hexdigest()
    if observed != expected_sha:
        raise MigrationError(f"artifact digest mismatch: expected {expected_sha}, observed {observed}")
    with zipfile.ZipFile(path) as outer:
        names = set(outer.namelist())
        required = {"SOURCE_HEADS.json", "SURFACE_CENSUS.json", "SHA256SUMS", "axm-arc-tier-bench-donors.bundle"}
        if not required.issubset(names):
            raise MigrationError(f"artifact lacks required files: {sorted(required - names)}")
        ledger = outer.read("SHA256SUMS").decode("utf-8")
        checked = 0
        for line in ledger.splitlines():
            digest, rel = line.split("  ", 1)
            payload = outer.read(rel)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise MigrationError(f"artifact internal digest mismatch: {rel}")
            checked += 1
        source = json.loads(outer.read("SOURCE_HEADS.json"))
    return {"outer_sha256": observed, "internal_files_verified": checked, "source_format": source["format"]}

def verify(artifact: Path | None = None) -> dict[str, Any]:
    docs = {name: load_strict(path) for name, path in FILES.items()}
    for name, value in docs.items():
        verify_self_hash(value, FILES[name])

    source = docs["source"]
    ownership = docs["ownership"]
    renaming = docs["renaming"]
    residue = docs["residue"]
    receipt = docs["receipt"]

    expected_heads = {
        "execution-product": "202fd8cfb03ec038ae0da2bfedb0bc5727b12e7d",
        "loopback-credential-service": "0e90b9adf63a863f986003ec169fa81dc25514db",
        "windows-isolation-diagnostic": "2f02e948e1db34d80243831081cc50ccf4653fd4",
    }
    observed_heads = {row["name"]: row["commit"] for row in source["heads"]}
    if observed_heads != expected_heads:
        raise MigrationError("source head set differs")
    loopback = next(row for row in source["heads"] if row["name"] == "loopback-credential-service")
    if loopback.get("terminal_receipt") != "ASOIAF_LOOPBACK_TLS_TERMINAL_RECEIPT_V2":
        raise MigrationError("loopback donor is not V2-published")
    if ownership["destination_repository"] != "BigBirdReturns/tier-bench":
        raise MigrationError("destination repository differs")
    if any("asoiaf" in plane["destination"].casefold() for plane in ownership["planes"]):
        raise MigrationError("destination path retains ASOIAF namespace")
    if len(renaming["module_map"]) < 18:
        raise MigrationError("renaming plan is incomplete")
    if any(row["removal_authorized"] for row in residue["rows"] if row["object"] != "axm-arc exporter PR #301"):
        raise MigrationError("non-disposable residue gained removal authority")
    if receipt["state"] != "SOURCE_CUSTODY_SEALED_DESTINATION_STAGED":
        raise MigrationError("migration stage differs")
    if receipt["source_code_imported"] or receipt["destination_qualified"] or receipt["old_home_cleanup_authorized"]:
        raise MigrationError("stage receipt overclaims migration")
    for key, expected in [
        ("source_heads_sha256", source["receipt_sha256"]),
        ("ownership_map_sha256", ownership["receipt_sha256"]),
        ("renaming_plan_sha256", renaming["receipt_sha256"]),
        ("residue_ledger_sha256", residue["receipt_sha256"]),
    ]:
        if receipt[key] != expected:
            raise MigrationError(f"receipt binding differs for {key}")

    result = {
        "status": "PASS",
        "state": receipt["state"],
        "source_head_count": len(source["heads"]),
        "plane_count": len(ownership["planes"]),
        "rename_count": len(renaming["module_map"]),
        "residue_count": len(residue["rows"]),
        "source_code_imported": False,
        "destination_qualified": False,
        "cleanup_authorized": False,
    }
    if artifact is not None:
        result["artifact"] = verify_artifact(artifact, receipt["source_export_sha256"])
    return result

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.artifact), indent=2, sort_keys=True))
        return 0
    except (MigrationError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"migration-verifier: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
