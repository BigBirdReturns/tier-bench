#!/usr/bin/env python3
"""Verify the self-contained Anchor Crate source and reference-product ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("labs/community-home-lab/anchor-crate/bundle_manifest.json"),
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    manifest_path = (repo / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"anchor bundle: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    if manifest.get("schema") != "tier-bench/anchor-crate-bundle-manifest@1":
        print("anchor bundle: invalid schema", file=sys.stderr)
        return 2
    errors = []
    seen = set()
    for row in manifest.get("files", []):
        path_text = row.get("path")
        if not isinstance(path_text, str) or not path_text or path_text in seen:
            errors.append(f"invalid or duplicate path: {path_text!r}")
            continue
        seen.add(path_text)
        relative = Path(path_text)
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"unsafe path: {path_text}")
            continue
        path = repo / relative
        if not path.is_file():
            errors.append(f"missing file: {path_text}")
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row.get("sha256"):
            errors.append(f"hash mismatch: {path_text}")
        if len(payload) != row.get("bytes"):
            errors.append(f"size mismatch: {path_text}")
    if manifest.get("production_claim") is not False or manifest.get("promotion_authorized") is not False:
        errors.append("manifest must remain non-production and non-promotional")
    print(json.dumps({"ok": not errors, "files": len(seen), "errors": errors}, indent=2, sort_keys=True))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
