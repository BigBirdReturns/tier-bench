#!/usr/bin/env python3
"""Admitted rail operation: give the workspace a shape the controller must face.

Two dispositions have to be witnessed rather than asserted, and both need a
phase that actually produces the condition inside the sandbox:

  symlink  a repository that legitimately contains a symbolic link. The
           checkpoint law admits only what the extraction law restores, so this
           must be REFUSED at checkpoint time and the transaction held -- never
           installed as a checkpoint recovery could not restore.

  lock     a directory the controller cannot remove (mode 0500 with a file in
           it). Settlement must refuse to commit SETTLED while the workspace
           survives, instead of publishing a receipt claiming zero residue.

One relative path, one fixed shape, no other capability.
"""
import os
import pathlib
import sys

if len(sys.argv) != 3:
    print("usage: workspace_shape.py <mode> <repo-relative-path>", file=sys.stderr)
    raise SystemExit(2)
mode, rel = sys.argv[1], sys.argv[2]
if rel.startswith("/") or ".." in rel.split("/"):
    print("path escapes the workspace", file=sys.stderr)
    raise SystemExit(2)
target = pathlib.Path(rel)

if mode == "symlink":
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    target.symlink_to("README.md")
    print("WORKSPACE_SYMLINK_CREATED", rel, "->", os.readlink(rel))
elif mode == "lock":
    target.mkdir(parents=True, exist_ok=True)
    (target / "held.txt").write_text("held\n")
    os.chmod(target, 0o500)
    print("WORKSPACE_DIRECTORY_LOCKED", rel, oct(target.stat().st_mode & 0o777))
else:
    print(f"UNKNOWN_WORKSPACE_SHAPE {mode}", file=sys.stderr)
    raise SystemExit(2)
