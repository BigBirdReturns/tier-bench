#!/usr/bin/env python3
"""Admitted rail script: require an artifact an earlier phase produced.

Exits non-zero when the file is missing or its digest differs, so a recovery
that silently discarded phase-produced state cannot report success.
"""
import hashlib
import pathlib
import sys

rel, want = sys.argv[1], sys.argv[2]
target = pathlib.Path(rel)
if not target.is_file():
    print(f"ARTIFACT_MISSING {rel}")
    raise SystemExit(2)
actual = hashlib.sha256(target.read_bytes()).hexdigest()
if actual != want:
    print(f"ARTIFACT_DIGEST_MISMATCH {rel} expected={want} actual={actual}")
    raise SystemExit(3)
print(f"ARTIFACT_SURVIVED {rel} sha256={actual}")
