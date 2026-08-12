#!/usr/bin/env python3
"""Admitted rail operation: prove the worker holds no credential and no network.

This is a structural claim, not merely an environment claim: the sandbox never
mounts the controller's home directory, so credential material is absent from
the worker's filesystem view entirely.

It is also an ENVIRONMENT CLOSURE claim. The controller can legitimately hold a
narrow publication token; the launch chain must not pass it on. The environment
is reported exactly -- every key, and a scan of the raw `/proc/self/environ`
bytes for the qualification's sentinel marker -- so the witness can assert that
the operation's environment is the declared worker set and nothing else, rather
than that no secret happened to be present on the controller that day.

Nothing here names a host, an account or a deployment path: the probe discovers
what is mounted instead of being told what to expect.
"""
import os
import pathlib
import re
import socket
import subprocess

# The qualification injects controller-side variables whose VALUES carry this
# marker. It is a compile-time constant, never an argument: argv is code.
SENTINEL = "TBRAIL-SENTINEL-"

# The declared worker set, plus PWD: `bwrap --clearenv` preserves PWD by
# documented design, and it names the guest working directory, not the host.
DECLARED = {"PATH", "LANG", "HOME", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE",
            "GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
            "PWD"}
SECRETISH = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY|"
                       r"_KEY$|^GH_|^GITHUB_|^AWS_|^SSH_|ASKPASS|NETRC|SESSION)",
                       re.IGNORECASE)

keys = sorted(os.environ)
print("env_keys=", keys)
undeclared = [k for k in keys if k not in DECLARED]
print("undeclared_env_keys=", undeclared)
secretish = [k for k in keys if SECRETISH.search(k)]
print("secretish_env_keys=", secretish)
sentinel_env = sorted(k for k, v in os.environ.items() if SENTINEL in str(v))
print("sentinel_env_keys=", sentinel_env)

raw = b""
try:
    raw = pathlib.Path("/proc/self/environ").read_bytes()
except OSError:
    pass
sentinel_raw = SENTINEL.encode() in raw
print("proc_environ_bytes=", len(raw))
print("proc_environ_sentinel_present=", sentinel_raw)

# Credential material is discovered, not enumerated from a known deployment.
mounted_homes = []
if pathlib.Path("/home").is_dir():
    mounted_homes = sorted(str(p) for p in pathlib.Path("/home").iterdir())
credential_paths = []
for base in ([pathlib.Path(p) for p in mounted_homes]
             + [pathlib.Path("/root"), pathlib.Path(os.environ.get("HOME", "/w/home"))]):
    for leaf in (".config/gh", ".ssh", ".netrc", ".git-credentials",
                 ".config/gcloud", ".aws"):
        p = base / leaf
        if p.exists():
            credential_paths.append(str(p))
print("host_homes_mounted=", mounted_homes)
print("credential_paths_visible=", sorted(set(credential_paths)))

net = "BLOCKED"
try:
    socket.setdefaulttimeout(3)
    socket.create_connection(("1.1.1.1", 53))
    net = "REACHABLE"
except OSError:
    pass
print("network=", net)

clone = subprocess.run(
    ["git", "clone", "--depth", "1",
     "https://github.com/BigBirdReturns/estate.git", "/tmp/should-not-exist"],
    capture_output=True, text=True)
print("private_clone_rc=", clone.returncode)

ok = (not undeclared and not secretish and not sentinel_env and not sentinel_raw
      and not mounted_homes and not credential_paths
      and net == "BLOCKED" and clone.returncode != 0)
print("CREDENTIAL_ISOLATION_HOLDS" if ok else "CREDENTIAL_LEAK")
raise SystemExit(0 if ok else 1)
