#!/usr/bin/env python3
"""Admitted rail script: write a deterministic artifact into the workspace.

Cross-phase state witness. A later phase must be able to see what this phase
produced, including after the controller is killed and the transaction resumes.
"""
import hashlib
import pathlib
import sys

rel, payload = sys.argv[1], sys.argv[2]
target = pathlib.Path(rel)
target.parent.mkdir(parents=True, exist_ok=True)
body = (payload + "\n").encode()
target.write_bytes(body)
print(f"PRODUCED {rel} bytes={len(body)} sha256={hashlib.sha256(body).hexdigest()}")
