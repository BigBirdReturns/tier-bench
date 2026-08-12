#!/usr/bin/env python3
"""Admitted rail operation: spawn a long-lived grandchild, then block.

Used only to prove timeout teardown reaches descendants, not just the direct
child. The parent exits its own wait via timeout; a rail that only killed the
direct child would leave this grandchild alive.
"""
import subprocess
import sys
import time

if len(sys.argv) != 2:
    print("usage: spawn_descendant.py <seconds>", file=sys.stderr)
    raise SystemExit(2)
seconds = int(sys.argv[1])
if not 1 <= seconds <= 600:
    print("seconds out of admitted range", file=sys.stderr)
    raise SystemExit(2)

child = subprocess.Popen([sys.executable, "-B", "-c",
                          f"import time; time.sleep({seconds})"])
print(f"spawned descendant pid={child.pid}", flush=True)
time.sleep(seconds)
