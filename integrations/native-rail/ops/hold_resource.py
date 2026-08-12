#!/usr/bin/env python3
"""Admitted rail operation: hold the lease for a bounded number of seconds.

Replaces an inline `python3 -c "...time.sleep..."` phase. The controller passes
one already-validated integer; this script accepts nothing else.
"""
import sys
import time

if len(sys.argv) != 2:
    print("usage: hold_resource.py <seconds>", file=sys.stderr)
    raise SystemExit(2)
seconds = int(sys.argv[1])
if not 1 <= seconds <= 120:
    print("seconds out of admitted range", file=sys.stderr)
    raise SystemExit(2)
time.sleep(seconds)
print(f"held {seconds}s")
