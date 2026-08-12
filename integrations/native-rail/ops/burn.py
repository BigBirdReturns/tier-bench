#!/usr/bin/env python3
"""Admitted rail script: deliberately exceed one enforced resource ceiling.

Each mode drives exactly one ceiling so the qualification can prove the ceiling
bites rather than merely being declared. Reaching a `*_COMPLETED` line means the
ceiling did NOT bite, which the witness treats as a failure. A ceiling enforced
in userspace reports `*_BLOCKED_AT`; a ceiling enforced by a kernel signal or by
controller teardown produces no completion line at all.
"""
import os
import sys
import time

mode, amount = sys.argv[1], int(sys.argv[2])

if mode == "output":
    line = b"x" * 4095 + b"\n"
    written = 0
    target = amount * 1024 * 1024
    out = sys.stdout.buffer
    while written < target:
        out.write(line)
        written += len(line)
    out.flush()
    print(f"OUTPUT_COMPLETED {written}")

elif mode == "memory":
    blocks = []
    try:
        for _ in range(amount):
            blocks.append(bytearray(1024 * 1024))
    except MemoryError:
        print(f"MEMORY_BLOCKED_AT {len(blocks)}MiB", flush=True)
        raise SystemExit(4)
    print(f"MEMORY_COMPLETED {len(blocks)}MiB")

elif mode == "disk":
    chunk = b"z" * (1024 * 1024)
    written = 0
    try:
        with open("tbrail-burn.bin", "wb") as fh:
            for _ in range(amount):
                fh.write(chunk)
                fh.flush()
                written += 1
    except OSError as exc:
        print(f"DISK_BLOCKED_AT {written}MiB {exc.__class__.__name__}", flush=True)
        raise SystemExit(4)
    print(f"DISK_COMPLETED {written}MiB")

elif mode == "cpu":
    deadline = time.time() + amount
    x = 0
    while time.time() < deadline:
        x = (x * 1103515245 + 12345) % (1 << 61)
    print(f"CPU_COMPLETED {amount}s x={x}")

elif mode == "pids":
    import resource
    # Informational only. The phase task ceiling is the cgroup `pids.max` of the
    # scope this phase runs in, NOT RLIMIT_NPROC -- that rlimit is charged per
    # account and could never express a per-phase ceiling, so the rail no longer
    # sets it. A blocked fork here is the cgroup refusing, not the rlimit.
    print(f"PIDS_RLIMIT_NPROC {resource.getrlimit(resource.RLIMIT_NPROC)} "
          f"(informational; ceiling is cgroup pids.max)", flush=True)
    children = []
    try:
        for _ in range(amount):
            pid = os.fork()
            if pid == 0:
                time.sleep(30)
                os._exit(0)
            children.append(pid)
    except OSError as exc:
        print(f"PIDS_BLOCKED_AT {len(children)} {exc.__class__.__name__}", flush=True)
        # Hold the scope open. This process is PID 1 of the sandbox's own PID
        # namespace, so the moment it exits the kernel reaps the whole namespace,
        # the scope loses its last task and the cgroup -- with the pids.events
        # counter that just fired -- is removed before the controller can read
        # it. The ceiling has to be witnessed from the live cgroup, so the phase
        # stays alive for a bounded window after the refusal.
        sys.stdout.flush()
        time.sleep(8)
        raise SystemExit(4)
    print(f"PIDS_COMPLETED {len(children)}", flush=True)
    time.sleep(60)

else:
    print(f"UNKNOWN_BURN_MODE {mode}")
    raise SystemExit(2)
