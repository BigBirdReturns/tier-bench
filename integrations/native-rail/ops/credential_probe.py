#!/usr/bin/env python3
"""Admitted rail operation: prove the worker holds no credential and no network.

Under v2 this is a structural claim, not merely an environment claim: the
sandbox never mounts the controller's home directory, so credential material is
absent from the worker's filesystem view entirely.
"""
import os
import pathlib
import socket
import subprocess

BANNED_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "SSH_AUTH_SOCK",
              "GIT_ASKPASS", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
              "AWS_ACCESS_KEY_ID")
CREDENTIAL_PATHS = ("/home/octo/.config/gh", "/home/octo/.ssh",
                    "/home/octo/.netrc", "/home/octo/.git-credentials",
                    "/root/.config/gh")

banned = [k for k in BANNED_ENV if k in os.environ]
print("banned_env_present=", banned)

visible = [p for p in CREDENTIAL_PATHS if pathlib.Path(p).exists()]
print("credential_paths_visible=", visible)

home_mounted = pathlib.Path("/home/octo").exists()
print("controller_home_mounted=", home_mounted)

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

ok = (not banned and not visible and not home_mounted
      and net == "BLOCKED" and clone.returncode != 0)
print("CREDENTIAL_ISOLATION_HOLDS" if ok else "CREDENTIAL_LEAK")
raise SystemExit(0 if ok else 1)
