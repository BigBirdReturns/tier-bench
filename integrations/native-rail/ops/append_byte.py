#!/usr/bin/env python3
"""Admitted rail operation: append one space to a file inside the workspace.

This is the deliberate-defect injector used to prove that a validation failure
renders the transaction red. It is classified EFFECTFUL in the operation
registry, so the crash-recovery law refuses to silently re-run it.

It is deliberately incapable of anything else: one relative path, one byte.
"""
import pathlib
import sys

if len(sys.argv) != 2:
    print("usage: append_byte.py <repo-relative-path>", file=sys.stderr)
    raise SystemExit(2)
rel = sys.argv[1]
if rel.startswith("/") or ".." in rel.split("/"):
    print("path escapes the workspace", file=sys.stderr)
    raise SystemExit(2)
p = pathlib.Path(rel)
if not p.is_file():
    print(f"target missing: {rel}", file=sys.stderr)
    raise SystemExit(2)
p.write_text(p.read_text() + " ")
print("DELIBERATE_DEFECT_INJECTED")
