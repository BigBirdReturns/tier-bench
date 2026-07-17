"""Model-free tests for the content-addressed v0.3 continuation manifest."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sol_root_matched_config"
sys.path.insert(0, str(EXPERIMENT))

from build_machine_continuation_v0_3 import DEFAULT_OUTPUT, blob, build_manifest, commit_oid, verify_manifest  # noqa: E402


REACHABILITY = EXPERIMENT / "reachability_receipt_v0_3.json"


def main() -> int:
    git = os.environ.get("GIT_EXE", "git")
    observed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    source = observed["source"]["artifact_commit"]
    expected = build_manifest(git, source)
    assert observed == expected
    receipt = verify_manifest(git, DEFAULT_OUTPUT)
    assert receipt["all_pass"] is True
    assert receipt["provider_calls"] == 0
    assert all(ref["commit"] == source and ref["hash_basis"] == "git_blob_bytes" for ref in observed["evidence_refs"])
    checks = 1

    parent = Path(tempfile.mkdtemp(prefix="sol-root-machine-continuation-"))
    try:
        broken = parent / "000.000.json"
        tampered = json.loads(json.dumps(observed))
        tampered["evidence_refs"][0]["blob_sha256"] = "0" * 64
        broken.write_text(json.dumps(tampered), encoding="utf-8")
        assert verify_manifest(git, broken)["all_pass"] is False
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    checks += 1

    reachability = json.loads(REACHABILITY.read_text(encoding="utf-8"))
    assert reachability["schema"] == "tier-bench/sol-root-matched-config/reachability-receipt@0.3"
    assert reachability["state"] == "reachable_unverified"
    assert reachability["artifact_commit"] == source
    handoff = commit_oid(git, reachability["handoff_commit"])
    assert handoff == reachability["remote_oid_observed"]
    manifest_blob = blob(git, handoff, reachability["manifest"]["path"])
    assert hashlib.sha256(manifest_blob).hexdigest() == reachability["manifest"]["blob_sha256"]
    assert reachability["push"] == {"force": False, "fast_forward_guard": True, "pr_opened": False, "merge_performed": False}
    assert reachability["canonical_custody_closed"] is False
    assert reachability["provider_calls"] == 0
    checks += 1

    print(f"OK - {checks} machine-continuation checks; zero provider calls, zero scientific observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
